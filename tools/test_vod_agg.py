"""生成「一个站点聚合多个点播源」的测试配置。

思路：CatVod 系有若干支持 ext.sites 的爬虫（XBPQ 就是其中之一），
把 N 个采集站塞进它的 ext.sites，这个站点自身就会把 N 个源的分类/搜索/详情都代理出来，
用户在 TVBox 里只看到一个「聚合点播」站点，就能访问 N 个源的数据。

用法：
    py tools/test_vod_agg.py            # 生成 dist/vod_agg.json（默认 6 个站）
    py tools/test_vod_agg.py --n 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

JAR = "https://raw.githubusercontent.com/qist/tvbox/master/jar/spider.jar"
SPIDER = "csp_XBPQ"


def pick_sites(n: int) -> list[dict]:
    home = json.load(open(os.path.join(DIST, "index_home.json"), encoding="utf-8"))
    out, seen = [], set()
    for s in home.get("sites") or []:
        if s.get("type") != 1:
            continue
        api = str(s.get("api") or "")
        if "provide/vod" not in api and "api.php" not in api:
            continue
        base = api.split("?")[0].rstrip("/")
        if base in seen:
            continue
        seen.add(base)
        out.append({
            "key": f"agg{len(out) + 1}",
            "name": str(s.get("name") or "")[:10],
            "type": 1,
            "api": api,
            "searchable": 1,
            "quickSearch": 1,
            "filterable": 1,
        })
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="聚合几个采集站")
    ap.add_argument("--out", default=os.path.join(DIST, "vod_agg.json"))
    args = ap.parse_args()

    subs = pick_sites(args.n)
    if not subs:
        print("index_home.json 里没有可用采集站")
        return 1

    doc = {
        "sites": [{
            "key": "aggvod",
            "name": f"聚合点播（{len(subs)} 源）",
            "type": 3,
            "api": SPIDER,
            "searchable": 1,
            "quickSearch": 1,
            "filterable": 1,
            "jar": JAR,
            "ext": {"sites": subs},
        }],
    }

    # 解析器 / 直播 从主配置里借一份，保证详情页与直播可用
    idx_path = os.path.join(DIST, "index.json")
    if os.path.exists(idx_path):
        idx = json.load(open(idx_path, encoding="utf-8"))
        doc["parses"] = (idx.get("parses") or [])[:20]
        doc["lives"] = (idx.get("lives") or [])[:20]
        for k in ("doh", "ijk", "headers", "flags", "ads", "hosts", "timeout", "ua"):
            if idx.get(k):
                doc[k] = idx[k]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"→ {args.out}  站点 1 个（聚合 {len(subs)} 源）")
    for s in subs:
        print("   -", s["name"], s["api"][:56])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
