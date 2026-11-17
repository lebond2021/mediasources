"""把 build_live.py 的产物组装成 TVBox 直播配置 dist/index_lives.json。

结构：
  lives[0] = 我们合并去重后的总频道表 live_all.m3u（一频道多源，播不动自动换源）
  lives[1..n] = 精选播放列表作为备用入口（万一总表某个频道挂了，用户还能选整份列表）

用法：
    py tools/emit_lives.py --all-url https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/live_all.m3u
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
DEFAULT_ALL_URL = "https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/live_all.m3u"

BACKUP_LISTS = [
    ("Guovin/iptv-api 聚合", "https://cdn.jsdelivr.net/gh/Guovin/iptv-api@gd/output/result.m3u"),
    ("iptv-org 中国", "https://iptv-org.github.io/iptv/countries/cn.m3u"),
    ("YanG-1989 Gather", "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u"),
    ("Kimentanm aptv", "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u"),
    ("vbskycn iptv4", "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u"),
    ("虎牙一起看", "https://sub.ottiptv.cc/huyayqk.m3u"),
    ("斗鱼一起看", "https://sub.ottiptv.cc/douyuyqk.m3u"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-url", default=DEFAULT_ALL_URL)
    ap.add_argument("--m3u", default=os.path.join(DIST, "live_all.m3u"))
    ap.add_argument("--out", default=os.path.join(DIST, "index_lives.json"))
    args = ap.parse_args()

    if not os.path.exists(args.m3u):
        print(f"缺少 {args.m3u}，先跑 tools/build_live.py")
        return 1

    stats = {}
    sp = os.path.join(DIST, "live_channels.json")
    if os.path.exists(sp):
        stats = json.load(open(sp, encoding="utf-8"))
    n_ch = stats.get("channels", 0)
    n_src = stats.get("sources", 0)

    lives = [{"name": f"聚合频道（{n_ch} 频道 / {n_src} 源）", "type": 0,
              "url": args.all_url, "playerType": 1}]
    for name, url in BACKUP_LISTS:
        lives.append({"name": name[:24], "type": 0, "url": url})

    doc = {"lives": lives}
    # 全局段（doh/ijk/headers 等）沿用点播配置里的，直播页也用得上
    idx = os.path.join(DIST, "index.json")
    if os.path.exists(idx):
        full = json.load(open(idx, encoding="utf-8"))
        for k in ("doh", "ijk", "headers", "flags", "ads", "hosts", "timeout", "ua"):
            if full.get(k):
                doc[k] = full[k]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f"→ {args.out}  lives={len(lives)}  首条={args.all_url}")
    print(f"   频道 {n_ch} / 源 {n_src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
