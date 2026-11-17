"""聚合点播服务：把 N 个采集站合成**一个** Apple-CMS 接口。

TVBox 里只要加一个站点（type=1，api 指向本服务），就能：
  · 分类浏览：多个站的内容混在同一个列表里（按片名去重）
  · 详情页：同一条影片把多个源的线路都列出来（线路1/2/3…），播不动直接换线
  · 搜索：一次搜索打到所有站，结果按片名合并

协议（标准苹果 CMS / TVBox type=1）：
  GET /api.php/provide/vod/?ac=list                  → 分类 + 第 1 页
  GET /api.php/provide/vod/?ac=videolist&t=1&pg=2    → 分类翻页
  GET /api.php/provide/vod/?ac=detail&ids=g1a2b3c4   → 详情（多线路合并）
  GET /api.php/provide/vod/?wd=庆余年                 → 搜索（跨站合并）

用法：
    py tools/agg_server.py --port 8008 --sites 8
    py tools/agg_server.py --port 8008 --from dist/index_home.json --sites 10
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 9) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}

GROUPS = [
    {"type_id": 1, "type_name": "电影", "kw": ("电影", "片", "movie")},
    {"type_id": 2, "type_name": "电视剧", "kw": ("剧", "tv", "连续")},
    {"type_id": 3, "type_name": "综艺", "kw": ("综艺", "秀", "variety")},
    {"type_id": 4, "type_name": "动漫", "kw": ("动漫", "动画", "anime")},
]

LOCK = threading.Lock()
GROUP_CACHE: dict[str, dict] = {}      # gid -> {"name":.., "items":[(site_idx, vod_id, name)]}
DETAIL_CACHE: dict[str, dict] = {}     # gid -> {"ts":.., "item":{...}}
SEARCH_CACHE: dict[str, dict] = {}     # 归一关键词 -> {"ts":.., "items":[...]}
CLASS_CACHE: dict[int, dict] = {}      # site_idx -> {"ts":.., "classes":[(id,name)]}


def norm_name(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）", "", str(s or ""))
    s = re.sub(r"(国语|粤语|中字|高清|超清|蓝光|完整版|未删减|4K|1080P|HD|TC|HDTV)", "", s, flags=re.I)
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    return s.lower()


class Aggregator:
    def __init__(self, sites: list[dict], timeout: float = 9.0, workers: int = 12):
        self.sites = sites
        self.timeout = timeout
        self.workers = workers
        self.session = requests.Session()
        self.session.trust_env = False
        self._pool = []

    # ---------- 底层请求 ----------
    def _get(self, url: str, timeout: float | None = None) -> dict | None:
        try:
            r = self.session.get(url, headers=UA, timeout=timeout or self.timeout, verify=False)
            if r.status_code != 200:
                return None
            r.encoding = "utf-8" if "utf-8" in (r.headers.get("Content-Type") or "") else "utf-8"
            return r.json()
        except Exception:
            return None

    @staticmethod
    def _api(site: dict, query: str) -> str:
        base = str(site.get("api") or "").strip()
        if "?" not in base:
            base = base.rstrip("/") + "/"
            sep = "?"
        else:
            sep = "&" if not base.endswith(("?", "&")) else ""
        return f"{base}{sep}{query}"

    # ---------- 分类 ----------
    def classes(self, idx: int) -> list[tuple]:
        now = time.time()
        c = CLASS_CACHE.get(idx)
        if c and now - c["ts"] < 3600:
            return c["classes"]
        data = self._get(self._api(self.sites[idx], "ac=list"))
        out = []
        for it in (data or {}).get("class") or []:
            tid = it.get("type_id")
            name = str(it.get("type_name") or "")
            if tid is None:
                continue
            out.append((tid, name))
        if not out:
            for it in (data or {}).get("list") or []:
                for t in it.get("vod_class") or []:
                    pass
        CLASS_CACHE[idx] = {"ts": now, "classes": out}
        return out

    def map_type(self, idx: int, gid: int) -> str | None:
        """把我们的分类号映射到某个站自己的 type_id。"""
        if gid == 0:
            return None
        want = next((g for g in GROUPS if g["type_id"] == gid), None)
        if not want:
            return None
        for tid, name in self.classes(idx):
            low = name.lower()
            if any(k in low for k in want["kw"]):
                return str(tid)
        return None

    # ---------- 列表 / 搜索 ----------
    def _fetch_list(self, idx: int, tid: str | None, pg: int) -> list[dict]:
        q = f"ac=videolist&pg={pg}" + (f"&t={tid}" if tid else "")
        data = self._get(self._api(self.sites[idx], q))
        return [x for x in (data or {}).get("list") or [] if isinstance(x, dict) and x.get("vod_id") is not None]

    def _remember(self, items: list[tuple[int, str, str]], pic: str = "") -> str:
        """把一组同名片源登记成一个 gid。"""
        key = norm_name(items[0][2])
        digits = hashlib.md5(key.encode("utf-8")).hexdigest()[:6]
        gid = f"g{digits}"
        with LOCK:
            GROUP_CACHE[gid] = {"name": items[0][2], "items": items, "pic": pic, "ts": time.time()}
        return gid

    def listing(self, gid: int, pg: int) -> list[dict]:
        if gid == 0:
            idxs = range(len(self.sites))
        else:
            idxs = [i for i in range(len(self.sites)) if self.map_type(i, gid)]
        rows: list[tuple] = []
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(self._fetch_list, i, self.map_type(i, gid), pg): i for i in idxs}
            for f in cf.as_completed(futs):
                i = futs[f]
                try:
                    got = f.result()
                except Exception:
                    continue
                for x in got:
                    rows.append((i, str(x.get("vod_id")), str(x.get("vod_name") or ""), x))

        buckets: dict[str, list] = {}
        for i, vid, name, raw in rows:
            k = norm_name(name)
            if not k:
                continue
            buckets.setdefault(k, []).append((i, vid, name, raw))

        out = []
        for k, group in buckets.items():
            group.sort(key=lambda t: 0 if t[3].get("vod_pic") else 1)
            best = group[0][3]
            pic = next((g[3].get("vod_pic") for g in group if g[3].get("vod_pic")), "")
            gid2 = self._remember([(i, vid, name) for i, vid, name, _ in group], pic)
            remarks = best.get("vod_remarks") or f"{len(group)} 源"
            out.append({
                "vod_id": gid2,
                "vod_name": best.get("vod_name") or k,
                "vod_pic": pic,
                "vod_remarks": f"{remarks}｜{len(group)}源" if len(group) > 1 else remarks,
                "vod_year": str(best.get("vod_year") or ""),
                "vod_area": str(best.get("vod_area") or ""),
            })
        out.sort(key=lambda x: -len(GROUP_CACHE.get(x["vod_id"], {}).get("items", [])))
        return out

    def search(self, wd: str) -> list[dict]:
        import concurrent.futures as cf
        key = norm_name(wd)
        cached = SEARCH_CACHE.get(key)
        if cached and time.time() - cached["ts"] < 300:
            return cached["items"]

        rows: list[tuple] = []
        # 搜索要快：并发 8、单站 3.5 秒，超时的站直接放弃（下次会更快回来）
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(self._fetch_list_search, i, wd): i for i in range(len(self.sites))}
            try:
                for f in cf.as_completed(futs, timeout=6.5):
                    i = futs[f]
                    try:
                        got = f.result()
                    except Exception:
                        continue
                    for x in got:
                        rows.append((i, str(x.get("vod_id")), str(x.get("vod_name") or ""), x))
            except cf.TimeoutError:
                pass
        buckets: dict[str, list] = {}
        for i, vid, name, raw in rows:
            k = norm_name(name)
            if not k or key and key not in k and k not in key:
                continue
            buckets.setdefault(k, []).append((i, vid, name, raw))
        out = []
        for k, group in buckets.items():
            group.sort(key=lambda t: 0 if t[3].get("vod_pic") else 1)
            best = group[0][3]
            pic2 = next((g[3].get("vod_pic") for g in group if g[3].get("vod_pic")), "")
            gid2 = self._remember([(i, vid, name) for i, vid, name, _ in group], pic2)
            out.append({
                "vod_id": gid2,
                "vod_name": best.get("vod_name") or k,
                "vod_pic": pic2,
                "vod_remarks": f"{len(group)}源",
                "vod_year": str(best.get("vod_year") or ""),
            })
        out.sort(key=lambda x: -len(GROUP_CACHE.get(x["vod_id"], {}).get("items", [])))
        with LOCK:
            SEARCH_CACHE[key] = {"ts": time.time(), "items": out}
        return out

    def _fetch_list_search(self, idx: int, wd: str) -> list[dict]:
        data = self._get(self._api(self.sites[idx], f"wd={requests.utils.quote(wd)}"))
        return [x for x in (data or {}).get("list") or [] if isinstance(x, dict) and x.get("vod_id") is not None]

    # ---------- 详情 ----------
    def detail(self, ids: str) -> list[dict]:
        """TVBox 会一次性把整页 id 都发过来（可能上百个）。

        批量请求（>3 个）走「轻量」路径：每组只取第一个源的线路，保证几秒内返回；
        用户真正点开某一集时是单 id 请求，这时才做多源合并（线路1/2/3…）。
        """
        gids = [x.strip() for x in ids.split(",") if x.strip()]
        light = len(gids) > 3
        out = []
        for gid in gids:
            with LOCK:
                g = GROUP_CACHE.get(gid)
            if not g:
                continue
            ck = gid + ("|L" if light else "|F")
            cached = DETAIL_CACHE.get(ck)
            if cached and time.time() - cached["ts"] < 600:
                out.append(cached["item"])
                continue
            if light:
                # 批量预览：不回源，只给卡片信息；用户点开时会再发单 id 请求
                base0 = {"vod_id": gid, "vod_name": g["name"], "vod_pic": g.get("pic") or "",
                         "vod_remarks": f"{len(g['items'])} 源", "vod_year": "", "vod_area": ""}
                with LOCK:
                    DETAIL_CACHE[ck] = {"ts": time.time(), "item": base0}
                out.append(base0)
                continue
            rows = self._details_of(g["items"][:6], timeout=self.timeout)
            if not rows:
                continue
            base = rows[0][1]
            froms, urls = [], []
            seen_sig: set[str] = set()
            for idx, raw in rows:
                name = str(self.sites[idx].get("name") or f"源{idx}")[:8]
                pf = str(raw.get("vod_play_from") or "")
                pu = str(raw.get("vod_play_url") or "")
                if not pu:
                    continue
                for i, (f1, u1) in enumerate(zip(pf.split("$$$"), pu.split("$$$"))):
                    if not u1.strip():
                        continue
                    sig = u1.split("#")[0].split("$")[-1].strip()
                    if sig and sig in seen_sig:
                        continue
                    if sig:
                        seen_sig.add(sig)
                    froms.append(f"{name}·{(f1 or '线'+str(i+1))[:8]}")
                    urls.append(u1)
                if len(froms) >= 8:
                    break
            if not urls:
                continue
            item = dict(base)
            item.pop("vod_play_from", None)
            item.pop("vod_play_url", None)
            item.update({
                "vod_id": gid,
                "vod_name": base.get("vod_name") or g["name"],
                "vod_play_from": "$$$".join(froms),
                "vod_play_url": "$$$".join(urls),
                "vod_remarks": f"{len(urls)} 线路" if not light else (base.get("vod_remarks") or ""),
            })
            with LOCK:
                DETAIL_CACHE[gid] = {"ts": time.time(), "item": item}
            out.append(item)
        return out

    def _details_of(self, items: list[tuple[int, str, str]], timeout: float | None = None) -> list[tuple[int, dict]]:
        import concurrent.futures as cf
        out = []
        with cf.ThreadPoolExecutor(max_workers=min(12, max(2, len(items)))) as ex:
            futs = {}
            for i, vid, _n in items:
                futs[ex.submit(self._fetch_detail, i, vid, timeout)] = i
            for f in cf.as_completed(futs):
                try:
                    raw = f.result()
                except Exception:
                    continue
                if raw and raw.get("vod_play_url"):
                    out.append((futs[f], raw))
        return out

    def _fetch_detail(self, idx: int, vid: str, timeout: float | None = None) -> dict | None:
        data = self._get(self._api(self.sites[idx], f"ac=detail&ids={vid}"), timeout=timeout)
        lst = (data or {}).get("list") or []
        return lst[0] if lst else None


AGG: Aggregator | None = None
CONFIG_DOC: dict | None = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 打印到 stdout，便于排查
        sys.stderr.write("[req] %s %s\n" % (self.command, self.path))
        sys.stderr.flush()

    def _send(self, obj: dict, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        assert AGG is not None
        path = urlsplit(self.path).path
        # 顺带把「聚合点播在前」的整份配置也发出去，TVBox 里只填一个地址即可
        if path in ("/", "/index.json", "/index_agg.json"):
            if CONFIG_DOC is None:
                self._send({"code": 0, "msg": "no config"}, 404)
                return
            self._send(CONFIG_DOC)
            return
        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        ac = q.get("ac") or ""
        try:
            # 搜索优先：TVBox 发的是 ?wd=关键字&ac=detail，别被 detail 分支吃掉
            if q.get("wd"):
                items = AGG.search(q["wd"])
                self._send({"code": 1, "msg": "数据列表", "page": 1, "pagecount": 1,
                            "limit": "20", "total": len(items), "list": items})
                return
            if ac in ("list", "videolist", ""):
                pg = int(q.get("pg") or q.get("page") or 1)
                gid = int(q.get("t") or 0)
                items = AGG.listing(gid, pg)
                self._send({
                    "code": 1, "msg": "数据列表", "page": pg, "pagecount": 9999,
                    "limit": "20", "total": len(items) * 9999,
                    "class": [{"type_id": g["type_id"], "type_name": g["type_name"]} for g in GROUPS]
                             + [{"type_id": 0, "type_name": "全部"}],
                    "list": items,
                })
                return
            if ac == "detail":
                ids = q.get("ids") or q.get("id") or ""
                self._send({"code": 1, "msg": "数据列表", "page": 1, "pagecount": 1,
                            "limit": "20", "total": 1, "list": AGG.detail(ids)})
                return
            self._send({"code": 0, "msg": "unsupported"}, 200)
        except Exception as e:  # 任何异常都返回合法 JSON，避免 TVBox 直接报错
            self._send({"code": 0, "msg": f"err {type(e).__name__}", "list": []})


def load_sites(args) -> list[dict]:
    if args.sites_file:
        raw = open(args.sites_file, encoding="utf-8").read()
        doc = json.loads(raw)
        sites = doc.get("sites") if isinstance(doc, dict) else doc
        return [s for s in sites if isinstance(s, dict) and str(s.get("api", "")).startswith("http")]
    doc = json.load(open(args.from_file, encoding="utf-8"))
    out = []
    for s in doc.get("sites") or []:
        if s.get("type") != 1 or not str(s.get("api", "")).startswith("http"):
            continue
        if "provide/vod" not in str(s["api"]) and "api.php" not in str(s["api"]):
            continue
        out.append({"name": s.get("name"), "api": s["api"]})
        if len(out) >= args.sites:
            break
    return out


def lan_ip() -> str:
    """探测本机在局域网里的地址（给电视盒子填配置用）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def build_config(api_base: str, base_cfg: str, limit_sites: int) -> dict:
    """把「聚合点播」作为第一个站点，后面接上主配置里的常用站。"""
    idx = json.load(open(base_cfg, encoding="utf-8"))
    doc = {
        "sites": [{
            "key": "aggvod",
            "name": "聚合点播·多源",
            "type": 1,
            "api": api_base,
            "searchable": 1,
            "quickSearch": 1,
            "filterable": 1,
        }] + (idx.get("sites") or [])[:limit_sites],
        "parses": (idx.get("parses") or [])[:30],
        "lives": (idx.get("lives") or [])[:40],
    }
    for k in ("doh", "ijk", "headers", "flags", "ads", "hosts", "timeout", "ua", "wallpaper", "warning"):
        if idx.get(k):
            doc[k] = idx[k]
    return doc


def main() -> int:
    global AGG, CONFIG_DOC
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8008)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--sites", type=int, default=8)
    ap.add_argument("--from", dest="from_file", default=os.path.join(ROOT, "dist", "index_home.json"))
    ap.add_argument("--sites-file", default=os.path.join(ROOT, "data", "agg_sites.json"))
    ap.add_argument("--config-from", default=os.path.join(ROOT, "dist", "index.json"),
                    help="在这个主配置基础上生成一份「聚合点播在前」的配置")
    ap.add_argument("--append-sites", type=int, default=300, help="配置里额外附带多少个普通站点")
    ap.add_argument("--public", default="", help="对外地址（如 https://xxx.trycloudflare.com），留空则用局域网 IP")
    args = ap.parse_args()

    sites = load_sites(args)
    if not sites:
        print("没有可用采集站")
        return 1
    AGG = Aggregator(sites)

    host = args.public.rstrip("/") if args.public else f"http://{lan_ip()}:{args.port}"
    api_base = host + "/api.php/provide/vod/"
    try:
        CONFIG_DOC = build_config(api_base, args.config_from, args.append_sites)
        cfg_note = f"{host}/  （TVBox 配置地址，直接填这个）"
    except Exception as e:
        CONFIG_DOC = None
        cfg_note = f"（生成配置失败：{type(e).__name__}）"

    print(f"聚合 {len(sites)} 个采集站")
    print(f"  接口   {api_base}")
    print(f"  配置   {cfg_note}")
    for s in sites:
        print("   -", s.get("name"), str(s.get("api"))[:60])
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
