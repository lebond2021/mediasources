"""把全网直播源合并成「一频道多源」的播放列表，并逐条测速，慢的与低清的直接丢掉。

真机结论驱动的设计：
- TVBox 的 m3u 解析器支持「一个 #EXTINF 后面跟多条 URL」= 同一频道的多个源，
  播不动时按顺序自动换源。所以同频道必须合并成一条，而不是像以前那样 2101 个频道铺满整屏。
- 频道名非常脏（`CCTV1`/`CCTV-1`/`央视一套`/`CCTV1高清`/`cctv1 1080p`），必须归一化后才能合并。
- 只有能测出速度、且速度达标的源才保留；测速时对 m3u8 会顺着 master playlist 取最高码率的变体，
  再拉一段真实分片算 KB/s，而不是只看 HTTP 200。

用法：
    py tools/build_live.py --sources data/state/live_sources.json \
        --workers 96 --min-kbps 300 --per-channel 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tvbox-aggregator/1.0"}
TIMEOUT = (4, 6)
CAP = 400 * 1024          # 测速最多读 400KB
DEADLINE = 6.0            # 单条源最多花 6 秒

EXTINF = re.compile(r"^#EXTINF:.*?,(.*)$")
ATTR_GROUP = re.compile(r'group-title="([^"]*)"', re.I)
ATTR_RES = re.compile(r'RESOLUTION=(\d+)x(\d+)', re.I)
ATTR_BW = re.compile(r'BANDWIDTH=(\d+)', re.I)
TXT_LINE = re.compile(r"^\s*([^#][^,]*?)\s*,\s*(https?://\S+)\s*$")

# ---------- 频道名归一 ----------

QUALITY_WORDS = [
    "蓝光", "超清", "高清", "标清", "原画", "超高清", "4k", "8k", "uhd", "fhd", "hd",
    "1080p", "1080i", "720p", "576p", "480p", "h264", "h265", "hevc", "50fps", "60fps",
    "hdr", "杜比", "立体声",
]
JUNK_WORDS = [
    "购物", "测试", "福利", "加群", "广告", "空", "无信号", "加密", "未授权", "请勿",
    "频道名为", "本次列表", "更新时间", "失效", "备用", "代", "售", "代理", "招租",
    "试看", "样片", "演示", "sample", "test", "adult", "18+",
    # 房间号类（一起看/斗鱼/虎牙/B站）不是电视频道，混进来只会让列表变乱
    "一起看", "斗鱼", "虎牙", "哔哩", "b站", "bilibili", "yy", "轮播", "房间", "主播",
    "直播中", "回放", "点播", "剧集", "电影",
]
CITY_WORDS = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安",
              "重庆", "天津", "长沙", "郑州", "济南", "青岛", "大连", "沈阳", "哈尔滨",
              "长春", "福州", "厦门", "昆明", "贵阳", "南宁", "海口", "合肥", "南昌",
              "太原", "石家庄", "呼和浩特", "乌鲁木齐", "银川", "西宁", "兰州", "拉萨"]
LOCAL_KINDS = ("新闻", "综合", "都市", "影视", "生活", "公共", "经济", "少儿", "体育",
               "文艺", "科教", "纪实", "国际", "电视台")
CCTV_WORDS = {"综合": "1", "财经": "2", "综艺": "3", "中文国际": "4", "体育": "5",
              "电影": "6", "军事农业": "7", "电视剧": "8", "纪录": "9", "科教": "10",
              "戏曲": "11", "社会与法": "12", "新闻": "13", "少儿": "14", "音乐": "15",
              "奥林匹克": "16", "农业农村": "17"}

SATELLITE = ["湖南", "浙江", "江苏", "东方", "北京", "安徽", "广东", "深圳", "湖北",
             "山东", "四川", "重庆", "天津", "辽宁", "河南", "河北", "江西", "福建",
             "东南", "贵州", "云南", "广西", "黑龙江", "吉林", "陕西", "甘肃", "宁夏",
             "青海", "新疆", "西藏", "内蒙古", "海南", "厦门", "三沙", "延边", "港澳"]

CCTV_ORDER = [str(i) for i in range(1, 18)] + ["5+", "4K", "8K"]


def clean_name(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"[\(\)\[\]【】<>《》]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    low = s.lower()
    for w in QUALITY_WORDS:
        low = low.replace(w, " ")
    s = re.sub(r"\s+", " ", low).strip(" -_|·")
    return s


def is_junk(name: str) -> bool:
    low = name.lower()
    return any(w in low for w in JUNK_WORDS)


def norm_channel(raw: str) -> tuple[str, str] | None:
    """返回 (频道标准名, 分组)；认不出来返回 None。"""
    s = clean_name(raw)
    if not s or len(s) > 40 or is_junk(s):
        return None

    # CCTV / 央视 / 中央
    m = re.search(r"cctv[\s\-_]*(\d{1,2})\s*(\+|plus|k)?", s)
    if not m:
        m = re.search(r"(?:央视|中央)[\s\-_]*(\d{1,2})\s*套?", s)
    if not m:
        for word, num in CCTV_WORDS.items():
            if f"cctv{num}" in s or f"中央{word}" in s or f"央视{word}" in s:
                return f"CCTV{num}", "央视"
    if m:
        num = m.group(1).lstrip("0") or "1"
        if num == "5" and (m.group(2) or "").lower() in ("+", "plus"):
            return "CCTV5+", "央视"
        if num.isdigit() and 1 <= int(num) <= 17:
            return f"CCTV{num}", "央视"

    # 卫视只认真实上星台，别把「普陀卫视」这种野鸡名当频道
    m = re.search(r"([\u4e00-\u9fa5]{2,6}?)[\s\-_]*(?:卫视|卫星电视)", s)
    if m:
        prov = m.group(1)
        for p in SATELLITE:
            if p in prov:
                return f"{p}卫视", "卫视"
        return None
    for p in SATELLITE:
        if s.startswith(p) and ("卫视" in s or "台" in s):
            return f"{p}卫视", "卫视"

    # 凤凰 / 港澳
    if "凤凰" in s:
        if "中文" in s:
            return "凤凰卫视中文台", "港澳"
        if "资讯" in s:
            return "凤凰卫视资讯台", "港澳"
        if "香港" in s:
            return "凤凰卫视香港台", "港澳"
        return "凤凰卫视", "港澳"

    # 地方台 / 其它：只保留「城市 + 台别」这种真实电视台名
    for city in CITY_WORDS:
        if s.startswith(city):
            if any(k in s for k in LOCAL_KINDS + ("卫视",)):
                return s[:12], "地方"
            break
    return None


# ---------- 播放列表解析 ----------

def parse_playlist(text: str) -> list[dict]:
    out: list[dict] = []
    if not text:
        return out
    group = ""
    pending = None
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("#EXTM3U"):
            continue
        if ln.startswith("#EXTINF"):
            m = EXTINF.search(ln)
            g = ATTR_GROUP.search(ln)
            group = (g.group(1) if g else group) or ""
            pending = {"name": (m.group(1).strip() if m else "")[:80], "group": group}
            continue
        if ln.startswith("#"):
            if "genre" in ln.lower() and "," in ln:
                group = ln.split(",", 1)[-1].strip()
            continue
        if not ln.lower().startswith(("http://", "https://")):
            continue
        # 源站常写 `url$LR•IPV4•10『线路8』`：$ 后面是线路名，不是地址的一部分
        url = ln.split("$", 1)[0].strip()
        if pending:
            out.append({"name": pending["name"], "url": url, "group": pending["group"]})
            pending = None
            continue
        m = TXT_LINE.match(ln)
        if m:
            out.append({"name": m.group(1)[:80], "url": url, "group": group})
        else:
            out.append({"name": "", "url": url, "group": group})
    return out


def looks_playlist(text: str) -> bool:
    head = text[:4000]
    return "#EXTM3U" in head or "#EXTINF" in head or bool(TXT_LINE.search(head))


def fetch_text(url: str, max_bytes: int = 4 * 1024 * 1024, max_sec: float = 8.0) -> str:
    """抓播放列表，限大小与时长——有些 .php 源会一直吐数据不结束。"""
    t0 = time.time()
    try:
        r = requests.get(url, timeout=(4, 6), headers=UA, stream=True, verify=False)
    except Exception:  # noqa: BLE001
        return ""
    if r.status_code >= 400:
        r.close()
        return ""
    buf = bytearray()
    try:
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) >= max_bytes or time.time() - t0 > max_sec:
                break
    except Exception:  # noqa: BLE001
        pass
    finally:
        r.close()
    enc = r.encoding or "utf-8"
    try:
        return buf.decode(enc, "ignore")
    except Exception:  # noqa: BLE001
        return buf.decode("utf-8", "ignore")


# ---------- 测速 ----------

def measure(url: str) -> dict | None:
    """顺着 m3u8 走到真实分片，读一段算速度；返回 {kbps, res, kind, media}。"""
    t1 = time.time()
    try:
        r = requests.get(url, timeout=(3, 5), headers=UA, stream=True, verify=False)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code >= 400:
        r.close()
        return None
    head = b""
    try:
        for chunk in r.iter_content(32768):
            head += chunk
            if len(head) >= 24000 or time.time() - t1 > 4:
                break
    except Exception:  # noqa: BLE001
        pass
    finally:
        r.close()

    text = head.decode("utf-8", "ignore")
    res = ""
    if "#EXTM3U" not in text:
        # 裸流：head 就是要测的数据
        el = max(0.001, time.time() - t1)
        if len(head) < 24000:
            return None
        kbps = len(head) / 1024 / el
        low = url.lower()
        res = "4K" if "4k" in low else ("1080P" if "1080" in low else
                                        ("720P" if "720" in low else ""))
        return {"kbps": round(kbps), "res": res, "kind": "stream", "media": url}

    # m3u8：挑最高码率变体，没有则取第一个分片
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    best, best_bw = "", -1
    for i, ln in enumerate(lines):
        if ln.startswith("#EXT-X-STREAM-INF"):
            m = ATTR_BW.search(ln)
            bw = int(m.group(1)) if m else 0
            nxt = next((x for x in lines[i + 1:] if not x.startswith("#")), "")
            if nxt and bw > best_bw:
                best, best_bw = nxt, bw
                mr = ATTR_RES.search(ln)
                if mr:
                    h = int(mr.group(2))
                    res = "4K" if h >= 2000 else ("1080P" if h >= 1000 else
                                                  ("720P" if h >= 700 else "SD"))
    if not best:
        best = next((x for x in lines if not x.startswith("#")), "")
    if not best:
        return None
    media = requests.compat.urljoin(url, best)

    got, t2 = 0, time.time()
    try:
        r2 = requests.get(media, timeout=(3, 5), headers=UA, stream=True, verify=False)
        if r2.status_code >= 400:
            r2.close()
            return None
        for chunk in r2.iter_content(65536):
            got += len(chunk)
            if got >= CAP or time.time() - t2 > 4:
                break
        r2.close()
    except Exception:  # noqa: BLE001
        return None
    el = max(0.001, time.time() - t2)
    if got < 24000:
        return None
    if not res:
        low = url.lower()
        res = "4K" if "4k" in low else ("1080P" if "1080" in low else
                                        ("720P" if "720" in low else ""))
    return {"kbps": round(got / 1024 / el), "res": res, "kind": "m3u8", "media": media}


# ---------- 主流程 ----------

def load_sources(path: str) -> list[dict]:
    doc = json.load(open(path, encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    return doc.get("lives") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=os.path.join(ROOT, "data", "state", "live_sources.json"))
    ap.add_argument("--workers", type=int, default=96)
    ap.add_argument("--min-kbps", type=int, default=300, help="低于这个速度的源直接丢掉")
    ap.add_argument("--per-channel", type=int, default=3, help="每个频道最多保留几个源")
    ap.add_argument("--candidates", type=int, default=8, help="每个频道测速前最多留几个候选")
    ap.add_argument("--extra", default=os.path.join(ROOT, "seeds", "live_seeds.txt"),
                    help="精选播放列表种子（每行一个 URL）")
    ap.add_argument("--probe-lists", type=int, default=400, help="最多展开多少个播放列表")
    ap.add_argument("--out-m3u", default="live_all.m3u")
    args = ap.parse_args()

    if not os.path.exists(args.sources):
        print(f"缺少 {args.sources}（先跑 py -m tvh build）")
        return 1
    sources = load_sources(args.sources)
    print(f"候选直播源: {len(sources)}", flush=True)

    # 1) 展开播放列表 → 频道
    pool: list[dict] = []          # {name, url}
    single = [s for s in sources if str(s.get("url", "")).lower().split("?")[0].endswith(
        (".m3u8", ".mp4", ".flv", ".ts"))]
    lists = [s for s in sources if s not in single]
    lists = lists[: args.probe_lists]
    if args.extra and os.path.exists(args.extra):
        extra = [ln.strip() for ln in open(args.extra, encoding="utf-8")
                 if ln.strip() and not ln.strip().startswith("#")]
        have = {s["url"] for s in lists}
        lists = [{"name": "seed", "url": u} for u in extra if u not in have] + lists
    print(f"展开播放列表 {len(lists)} 个（含精选种子），单条流 {len(single)} 条", flush=True)

    with ThreadPoolExecutor(max_workers=min(args.workers, 64)) as ex:
        futs = {ex.submit(fetch_text, s["url"]): s for s in lists}
        for f in as_completed(futs):
            s = futs[f]
            try:
                text = f.result()
            except Exception:  # noqa: BLE001
                text = ""
            if not looks_playlist(text):
                continue
            for ch in parse_playlist(text):
                if ch.get("name"):
                    pool.append({"name": ch["name"], "url": ch["url"]})
    for s in single:
        pool.append({"name": s.get("name") or "", "url": s.get("url") or ""})

    # 2) 名称归一 + 按 (频道, url) 去重
    by_channel: dict[str, dict] = {}
    seen_url: set[str] = set()
    for it in pool:
        url = (it.get("url") or "").strip()
        if not url.startswith("http") or url in seen_url:
            continue
        got = norm_channel(it.get("name") or "")
        if not got:
            continue
        name, group = got
        seen_url.add(url)
        rec = by_channel.setdefault(name, {"name": name, "group": group, "urls": []})
        rec["urls"].append(url)
    total_urls = sum(len(v["urls"]) for v in by_channel.values())
    print(f"归一后频道: {len(by_channel)}   候选地址: {total_urls}", flush=True)

    # 2.5) 每个频道先按启发式筛出少量候选，避免几万条全测速
    def pre_score(u: str) -> int:
        low = u.lower()
        s = 0
        if low.startswith("https://"):
            s += 3
        if ".m3u8" in low:
            s += 2
        if any(k in low for k in ("1080", "4k", "uhd", "hd")):
            s += 1
        host = low.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if not re.fullmatch(r"[\d.]+", host):
            s += 1
        if any(k in low for k in ("test", "demo", "sample", "127.0.0.1", "localhost")):
            s -= 4
        return s

    for rec in by_channel.values():
        if len(rec["urls"]) > args.candidates:
            rec["urls"] = sorted(rec["urls"], key=pre_score, reverse=True)[: args.candidates]
    total_urls = sum(len(v["urls"]) for v in by_channel.values())
    print(f"预筛后待测地址: {total_urls}（每频道 ≤{args.candidates}）", flush=True)

    # 3) 并发测速（每个地址一次）
    flat = [(name, u) for name, rec in by_channel.items() for u in rec["urls"]]
    speed: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(measure, u): u for _, u in flat}
        for f in as_completed(futs):
            u = futs[f]
            done += 1
            if done % 200 == 0:
                print(f"  测速 {done}/{len(flat)}  通过 {len(speed)}", flush=True)
            try:
                r = f.result()
            except Exception:  # noqa: BLE001
                r = None
            if r and r["kbps"] >= args.min_kbps:
                speed[u] = r

    # 4) 每频道取最快的 N 个
    out: list[dict] = []
    for name, rec in by_channel.items():
        cand = [(u, speed[u]) for u in rec["urls"] if u in speed]
        cand.sort(key=lambda x: -x[1]["kbps"])
        cand = cand[: args.per_channel]
        if not cand:
            continue
        out.append({"name": name, "group": rec["group"],
                    "urls": [u for u, _ in cand],
                    "kbps": [m["kbps"] for _, m in cand],
                    "res": [m["res"] for _, m in cand]})

    order = {"央视": 0, "卫视": 1, "港澳": 2, "地方": 3}
    def sort_key(c: dict):
        g = c["group"]
        n = c["name"]
        if g == "央视":
            num = n.replace("CCTV", "")
            idx = CCTV_ORDER.index(num) if num in CCTV_ORDER else 99
            return (0, idx)
        if g == "卫视":
            return (1, SATELLITE.index(n.replace("卫视", "")) if n.replace("卫视", "") in SATELLITE else 99)
        return (order.get(g, 3), n)
    out.sort(key=sort_key)

    # 5) 写 m3u：一条 EXTINF + 多行 URL = 同频道多源
    m3u = os.path.join(DIST, args.out_m3u)
    with open(m3u, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in out:
            res = next((r for r in c["res"] if r), "")
            tag = f" {res}" if res else ""
            f.write(f'#EXTINF:-1 group-title="{c["group"]}",{c["name"]}{tag}\n')
            for u in c["urls"]:
                f.write(f"{u}\n")
    print(f"\n→ {m3u}  频道 {len(out)}  源 {sum(len(c['urls']) for c in out)}  "
          f"{os.path.getsize(m3u)//1024}KB", flush=True)

    rep = {
        "channels": len(out),
        "sources": sum(len(c["urls"]) for c in out),
        "by_group": {g: sum(1 for c in out if c["group"] == g) for g in ("央视", "卫视", "港澳", "地方")},
        "tested": len(flat),
        "passed": len(speed),
        "min_kbps": args.min_kbps,
        "detail": [{"name": c["name"], "group": c["group"], "n": len(c["urls"]),
                    "kbps": c["kbps"], "res": c["res"]} for c in out],
    }
    with open(os.path.join(DIST, "live_channels.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    for c in out[:12]:
        print(f"  {c['group']:3s} {c['name']:12s} {len(c['urls'])}源 "
              f"{'/'.join(str(k) for k in c['kbps'])} KB/s {c['res']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
