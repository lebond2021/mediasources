"""探测直播源：判断哪些 URL 真的是「频道列表」，按可用频道数排序，并合成一份总播放列表。

真机现象：dist/index_lives.json 里 1471 条是单条 m3u8 流、只有 331 条 m3u / 260 条 txt 是列表，
TVBox 默认取第 1 条，而第 1 条上游只剩一条测试频道 → 直播页看起来「没有源」。
所以这里做三件事：
1. 逐条抓取，解析出频道数（m3u 的 #EXTINF、txt 的 `名称,地址`）；
2. 抽样验证频道地址是否真的能连上，算出存活率；
3. 把所有可用频道去重合并成一份总列表 `dist/live_all.m3u`，作为直播配置的第一条源。

用法：
    py tools/probe_lives.py --workers 64 --timeout 8 --top 400 --sample 6
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tvh.http import Fetcher  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

EXTINF = re.compile(r"^#EXTINF:.*?,(.*)$")
ATTR_GROUP = re.compile(r'group-title="([^"]*)"', re.I)
TXT_LINE = re.compile(r"^\s*([^#][^,]*?)\s*,\s*(https?://\S+)\s*$")
URL_ONLY = re.compile(r"^\s*(https?://\S+)\s*$")
# 单条流（.m3u8/.mp4/...）不是「频道列表」，先跳过：1483 条里一半是这类，能省一半时间
STREAM_EXT = (".m3u8", ".mp4", ".flv", ".ts", ".mkv")
DEFAULT_ALL_URL = "https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/live_all.m3u"


def parse_playlist(text: str) -> list[dict]:
    """把 m3u / txt 播放列表解析成 [{name, url, group}]。"""
    out: list[dict] = []
    if not text:
        return out
    lines = [ln.strip() for ln in text.splitlines()]
    group = ""
    pending: dict | None = None
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("#EXTM3U"):
            continue
        if ln.startswith("#EXTINF"):
            m = EXTINF.search(ln)
            g = ATTR_GROUP.search(ln)
            group = (g.group(1) if g else group) or ""
            pending = {"name": (m.group(1).strip() if m else "")[:60], "group": group}
            continue
        if ln.startswith("#"):
            # #genre#分组标记，或其它注释
            if "genre" in ln.lower() and "," in ln:
                group = ln.split(",", 1)[-1].strip()
            continue
        if not ln.lower().startswith(("http://", "https://")):
            continue
        if pending:
            out.append({"name": pending.get("name") or "", "url": ln,
                        "group": pending.get("group") or group})
            pending = None
            continue
        m = TXT_LINE.match(ln)
        if m:
            out.append({"name": m.group(1)[:60], "url": m.group(2), "group": group})
            continue
        if URL_ONLY.match(ln):
            out.append({"name": "", "url": ln, "group": group})
    return out


def looks_playlist(text: str) -> bool:
    head = text[:4000]
    return "#EXTM3U" in head or "#EXTINF" in head or bool(TXT_LINE.search(head))


def check_url(fetcher: Fetcher, url: str, timeout: int) -> bool:
    """轻量验证：能建立连接并拿到 2xx/3xx 就算活。"""
    try:
        r = fetcher.get(url, use_cache=False, cache_ttl=0, binary=True, allow_redirects=True)
    except Exception:  # noqa: BLE001
        return False
    if r.error:
        return False
    if r.status and 200 <= r.status < 400:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--top", type=int, default=400, help="保留多少条列表型直播源")
    ap.add_argument("--sample", type=int, default=6, help="每条源抽检几个频道")
    ap.add_argument("--min-channels", type=int, default=5)
    ap.add_argument("--per-host", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="只探测前 N 条候选（小批量测试用）")
    ap.add_argument("--out", default="index_lives.json", help="输出的直播配置文件名（在 dist/ 下）")
    ap.add_argument("--all-out", default="live_all.m3u", help="合并总列表文件名（在 dist/ 下）")
    ap.add_argument("--all-url", default=DEFAULT_ALL_URL,
                    help="聚合总列表发布后的公网地址，写进直播配置的第一条")
    ap.add_argument("--no-stream-skip", action="store_true", help="也探测 .m3u8 单条流")
    args = ap.parse_args()

    src = os.path.join(DIST, "index_lives.json")
    doc = json.load(open(src, encoding="utf-8"))
    lives = doc.get("lives") or []
    if not args.no_stream_skip:
        before = len(lives)
        lives = [x for x in lives
                 if not str(x.get("url", "")).lower().split("?")[0].endswith(STREAM_EXT)]
        print(f"跳过单条流 {before - len(lives)} 条")
    if args.limit:
        lives = lives[: args.limit]
    print(f"待探测直播源: {len(lives)}", flush=True)

    fetcher = Fetcher(cache_dir=os.path.join(ROOT, "data", "cache"),
                      timeout=args.timeout, retries=1, per_host=args.per_host)

    def probe(item: dict) -> dict | None:
        url = item.get("url") or ""
        r = fetcher.get(url, use_cache=False, cache_ttl=0)
        if r.error or not r.text:
            return None
        if not looks_playlist(r.text):
            return None
        chans = parse_playlist(r.text)
        if len(chans) < args.min_channels:
            return None
        # 抽样验证频道地址（--sample 0 时跳过，只看频道数）
        if args.sample <= 0:
            alive, total = 0, 0
        else:
            step = max(1, len(chans) // args.sample)
            sample = chans[::step][: args.sample]
            alive = sum(1 for c in sample if check_url(fetcher, c["url"], args.timeout))
            total = len(sample)
        return {
            "name": item.get("name") or "",
            "url": url,
            "type": item.get("type", 0),
            "channels": chans,
            "n": len(chans),
            "sample_alive": alive,
            "sample": total,
            "ratio": (alive / total) if total else 0.0,
        }

    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe, it): it for it in lives}
        for f in as_completed(futs):
            done += 1
            if done % 100 == 0:
                print(f"  进度 {done}/{len(lives)}  命中 {len(results)}", flush=True)
            try:
                r = f.result()
            except Exception:  # noqa: BLE001
                r = None
            if r:
                results.append(r)

    results.sort(key=lambda x: (-x["ratio"], -x["n"]))
    print(f"列表型直播源: {len(results)}（其中抽样全活的 {sum(1 for r in results if r['ratio'] >= 1)}）")
    for r in results[:10]:
        print(f"  {r['ratio']:.0%} {r['n']:5d} 频道  {r['name'][:16]:16s} {r['url'][:70]}")

    # 合并总播放列表（按 url 去重，保留首个名称/分组）
    merged: dict[str, dict] = {}
    for r in results:
        g = r["name"] or "聚合"
        for c in r["channels"]:
            u = c["url"].strip()
            if u in merged:
                continue
            merged[u] = {"name": (c["name"] or u.rsplit("/", 1)[-1])[:60],
                         "url": u, "group": c.get("group") or g}
    print(f"合并后频道: {len(merged)}")

    m3u = os.path.join(DIST, args.all_out)
    with open(m3u, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in merged.values():
            f.write(f'#EXTINF:-1 group-title="{c["group"]}",{c["name"]}\n{c["url"]}\n')
    print(f"→ {m3u}  {os.path.getsize(m3u)//1024}KB")

    # 重写 index_lives.json：第一条是我们自己合成的总列表，后面是按质量排序的列表型源
    keep = results[: args.top]
    new_lives = [{"name": f"聚合频道（{len(merged)} 个）", "type": 0,
                  "url": args.all_url, "playerType": 1}]
    for r in keep:
        if r["url"] == args.all_url:
            continue
        new_lives.append({"name": (r["name"] or "直播源")[:24], "type": 0, "url": r["url"]})
    doc["lives"] = new_lives
    out = os.path.join(DIST, args.out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f"→ {out}  lives={len(new_lives)}  第一条={args.all_url}", flush=True)

    rep = {
        "probed": len(lives),
        "playlists": len(results),
        "channels_merged": len(merged),
        "kept": len(new_lives),
        "top": [{"name": r["name"], "url": r["url"], "channels": r["n"],
                 "ratio": round(r["ratio"], 2)} for r in results[:30]],
    }
    with open(os.path.join(DIST, "live_probe.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
