"""按实测质量裁剪配置：只留高清 + 快的源。

输入：
  dist/index_all.json           全量站点（含 csp 站点与站点级 jar）
  data/state/site_quality*.json  rate_sites.py 的实测结果（kbps / 分辨率 / 延迟）
输出：
  dist/index.json               主配置（实测优选 + 少量高引用 csp）
  dist/index_lite.json          精简版（更快，给电视盒子）
  data/state/curated.json       选站明细，便于复查

选站规则：
  采集站（type=1）——必须有实测记录，url_ok=1，速率 ≥ --min-kbps；
                     分辨率 ≥720p 或速率 ≥1.5MB/s 视为高清，优先。
  csp 站（type=3/4/9）——无法离线测播放，按「同一类名被多少个配置引用」取前 N，
                     且类名必须在该站点的 jar 里（配置里已有 jar 字段）。
  其它类型（0/2/5/6/7/8）——同样必须有实测记录。
  成人站直接丢弃。

用法：
  py tools/curate.py --min-kbps 300 --max-total 220
  py tools/curate.py --dry-run
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADULT_RE = re.compile(r"(🔞|🈲|18禁|成人|色情|情色|福利|麻豆|自拍|偷拍|av资源|avzy|souav|ysxq|ckbh|porn|xxx|jav|hentai|sex|约炮|裸|黑料|吃瓜|网红|午夜|三级|探花)", re.I)
CSP_KEEP_CLASSES = 24          # 只保留最流行的 N 个 csp 类
SPEED_TAG = re.compile(r"\s*\[\d+\s*ms[^\]]*\]")


def load_json(path: str, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def load_quality() -> dict[str, dict]:
    """把多个 site_quality*.json 合并成 api -> 最好的一条记录。"""
    best: dict[str, dict] = {}
    for p in glob.glob(os.path.join(ROOT, "data", "state", "site_quality*.json")):
        doc = load_json(p) or {}
        for rec in doc.get("sites") or []:
            api = str(rec.get("api") or "")
            if not api:
                continue
            cur = best.get(api)
            if cur is None or (rec.get("kbps", 0) > cur.get("kbps", 0)):
                best[api] = rec
    return best


def load_hosts() -> dict[str, str]:
    """api -> 播放线路域名（用来识别同一后端的马甲站）。"""
    out: dict[str, str] = {}
    for p in glob.glob(os.path.join(ROOT, "data", "state", "site_hosts*.json")):
        doc = load_json(p) or {}
        for rec in doc.get("sites") or []:
            api, host = str(rec.get("api") or ""), str(rec.get("host") or "")
            if api and host:
                out[api] = host
    return out


def load_content() -> dict[str, str]:
    """api -> 内容类型（main/movie/drama/anime/sports/adult/mixed/empty）。"""
    out: dict[str, str] = {}
    p = os.path.join(ROOT, "data", "state", "site_content.json")
    doc = load_json(p) or {}
    for rec in doc.get("sites") or []:
        api = str(rec.get("api") or "")
        if api:
            out[api] = str(rec.get("kind") or "")
    return out


GOOD_KINDS = {"main", "movie", "drama", "anime"}


def res_label(rec: dict) -> str:
    h = int(rec.get("res") or 0)
    kbps = float(rec.get("kbps") or 0)
    if h >= 2000:
        res = "4K"
    elif h >= 1000:
        res = "1080P"
    elif h >= 700:
        res = "720P"
    elif kbps >= 1200:
        res = "高清"
    else:
        res = ""
    if kbps >= 1024:
        sp = f"{kbps/1024:.1f}MB/s"
    else:
        sp = f"{kbps:.0f}KB/s"
    return f"{res} {sp}".strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", default=os.path.join(ROOT, "dist", "index_all.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "index.json"))
    ap.add_argument("--lite-out", default=os.path.join(ROOT, "dist", "index_lite.json"))
    ap.add_argument("--report", default=os.path.join(ROOT, "data", "state", "curated.json"))
    ap.add_argument("--min-kbps", type=float, default=300.0)
    ap.add_argument("--min-kbps-lite", type=float, default=800.0)
    ap.add_argument("--max-measured", type=int, default=150, help="实测采集站最多保留多少个")
    ap.add_argument("--max-csp", type=int, default=80, help="csp 站最多保留多少个")
    ap.add_argument("--max-total", type=int, default=220)
    ap.add_argument("--lite", type=int, default=45)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = load_json(args.from_file) or {}
    sites = [s for s in (doc.get("sites") or []) if isinstance(s, dict) and s.get("api")]
    quality = load_quality()
    print(f"全量站点 {len(sites)}，实测记录 {len(quality)}")

    # 1) 实测过的采集站（同时要求内容不是成人站）
    content = load_content()
    measured: list[tuple[float, dict, dict]] = []
    for s in sites:
        rec = quality.get(str(s["api"]))
        if not rec or not rec.get("url_ok"):
            continue
        if rec.get("kbps", 0) < args.min_kbps:
            continue
        kind = content.get(str(s["api"]), "")
        if kind and kind not in GOOD_KINDS:
            continue
        if ADULT_RE.search(f"{s.get('name')} {s.get('api')}"):
            continue
        measured.append((float(rec.get("kbps") or 0), s, rec))
    measured.sort(key=lambda t: (0 if content.get(t[1]["api"]) in ("movie", "drama", "anime") else 1,
                                0 if (t[2].get("res") or 0) >= 720 else 1,
                                -t[0], t[2].get("ms", 9999)))
    measured = measured[:args.max_measured]

    picked: list[dict] = []
    seen_key: set[str] = set()
    seen_api: set[str] = set()
    seen_host: set[str] = set()
    hosts = load_hosts()
    for kbps, s, rec in measured:
        api = str(s["api"])
        if api in seen_api:
            continue
        seen_api.add(api)
        # 同一播放线路域名 = 同一后端，只留最快的那一个
        host = hosts.get(api) or str(rec.get("host") or "")
        if host and host in seen_host:
            continue
        if host:
            seen_host.add(host)
        out = dict(s)
        name = SPEED_TAG.sub("", str(out.get("name") or ""))
        out["name"] = f"{name} [{res_label(rec)}]"
        out["_rank"] = float(rec.get("kbps") or 0)
        key = str(out.get("key") or name)[:64]
        if key in seen_key:
            continue
        seen_key.add(key)
        picked.append(out)

    # 2) csp 站：按类名流行度取前 N（配置里必须已经有站点级 jar）
    cls_counter: Counter[str] = Counter()
    for s in sites:
        api = str(s.get("api") or "")
        if api.startswith("csp_"):
            cls_counter[api.split("@")[0]] += 1
    hot = {c for c, _ in cls_counter.most_common(CSP_KEEP_CLASSES)}

    csp_rows = [s for s in sites
                if str(s.get("api") or "").startswith("csp_")
                and s.get("jar")
                and str(s["api"]).split("@")[0] in hot]
    csp_rows.sort(key=lambda s: (0 if s.get("alive") else 1))
    n_csp = 0
    for s in csp_rows:
        if n_csp >= args.max_csp or len(picked) >= args.max_total:
            break
        name = SPEED_TAG.sub("", str(s.get("name") or ""))
        if ADULT_RE.search(f"{name} {s.get('api')}"):
            continue
        key = str(s.get("key") or name)[:64]
        if key in seen_key:
            continue
        seen_key.add(key)
        out = dict(s)
        out["name"] = name
        picked.append(out)
        n_csp += 1

    # 3) 清掉成人站与残留速度标签；实测站按速率排前面
    final: list[dict] = []
    for s in picked:
        name = SPEED_TAG.sub("", str(s.get("name") or "")).strip()
        if ADULT_RE.search(f"{name} {s.get('api')}"):
            continue
        if "[" in name and ("KB/s" in name or "MB/s" in name):
            s["name"] = name
        else:
            s["name"] = name
        final.append(s)
    final.sort(key=lambda s: -float(s.pop("_rank", 0)))

    def build(subset: list[dict]) -> dict:
        o = {
            "sites": subset,
            "parses": (doc.get("parses") or [])[:60],
            "lives": (doc.get("lives") or [])[:30],
        }
        for k in ("doh", "ijk", "headers", "flags", "ads", "hosts", "timeout", "ua", "wallpaper", "warning", "spider"):
            if doc.get(k):
                o[k] = doc[k]
        return o

    lite_rows: list[dict] = []
    scored: list[tuple[float, dict]] = []
    for s in final:
        m = re.search(r"\[(?:4K |1080P |720P |高清 )?([\d.]+)(MB|KB)/s\]", str(s.get("name") or ""))
        if not m:
            continue
        v = float(m.group(1)) * (1024 if m.group(2) == "MB" else 1)
        scored.append((v, s))
    scored.sort(key=lambda t: -t[0])
    for v, s in scored:
        if len(lite_rows) >= args.lite:
            break
        if v >= args.min_kbps_lite or len(lite_rows) < args.lite:
            lite_rows.append(s)

    main_doc = build(final)
    lite_doc = build(lite_rows)
    print(f"主配置 {len(main_doc['sites'])} 站（实测 {len(measured)} + csp {n_csp}）；精简 {len(lite_doc['sites'])} 站")
    for s in final[:10]:
        print("   ", s.get("name"))

    if args.dry_run:
        return 0

    json.dump(main_doc, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(lite_doc, open(args.lite_out, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({
        "ts": __import__("time").time(),
        "measured": len(measured), "csp": n_csp, "total": len(final), "lite": len(lite_rows),
        "min_kbps": args.min_kbps,
        "sites": [{"name": s.get("name"), "api": s.get("api"), "key": s.get("key")} for s in final],
    }, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {args.out}  {os.path.getsize(args.out)//1024} KB")
    print(f"→ {args.lite_out}  {os.path.getsize(args.lite_out)//1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
