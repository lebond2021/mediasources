"""侦察：找出配置里的「网盘源」（夸克/UC/阿里/百度/115 等），按类型统计。

夸克网盘源在 TVBox 生态里通常是 csp_ 站点，靠 jar 里的网盘接口出 4K 直链，
比采集站画质高得多。这里先把它们从 6 万多站里捞出来看清结构。

    py tools/scan_pan.py
    py tools/scan_pan.py --out data/state/pan_sites.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAN_PATTERNS = {
    "quark": re.compile(r"(quark|夸克)", re.I),
    "uc": re.compile(r"\buc\b|ucdrive|ucpan", re.I),
    "ali": re.compile(r"(aliyundrive|阿里云盘|alipan|aliyundrive)", re.I),
    "baidu": re.compile(r"(baidupan|百度网盘|baiduyun)", re.I),
    "115": re.compile(r"(115pan|115网盘)", re.I),
    "xunlei": re.compile(r"(xunlei|迅雷)", re.I),
}
# 常见的网盘向 spider 类名（社区里出网盘直链的那批）
PAN_SPIDERS = re.compile(
    r"(PanWebShare|PanSou|PanSearch|Quark|QuP|QuarkTV|Pan|Yun|Cloud|Share|Shandian|XiaoYa|Ali|UC|115|Baidu)",
    re.I,
)


def classify(site: dict) -> set[str]:
    hits: set[str] = set()
    blob = " ".join(str(site.get(k) or "") for k in ("name", "api", "ext", "jar", "key"))
    for name, pat in PAN_PATTERNS.items():
        if pat.search(blob):
            hits.add(name)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", default=os.path.join(ROOT, "dist", "index_all.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "state", "pan_sites.json"))
    args = ap.parse_args()

    doc = json.load(open(args.from_file, encoding="utf-8"))
    sites = [s for s in doc.get("sites") or [] if isinstance(s, dict)]
    pan: list[dict] = []
    kinds: Counter[str] = Counter()
    sp: Counter[str] = Counter()
    for s in sites:
        hits = classify(s)
        api = str(s.get("api") or "")
        is_csp = api.startswith("csp_")
        cls = api.split("@")[0][4:] if is_csp else ""
        if cls and PAN_SPIDERS.search(cls):
            hits.add("pan-spider")
        if not hits:
            continue
        kinds.update(hits)
        if is_csp:
            sp[cls] += 1
        pan.append({
            "name": s.get("name"), "api": api, "type": s.get("type"),
            "jar": str(s.get("jar") or "")[:120],
            "ext": str(s.get("ext") or "")[:200],
            "kinds": sorted(hits),
        })

    pan.sort(key=lambda x: (0 if "quark" in x["kinds"] else 1, str(x["name"])))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({"count": len(pan), "kinds": dict(kinds), "spiders": dict(sp), "sites": pan},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"疑似网盘源 {len(pan)} 个 / 全量 {len(sites)}")
    print("特征命中:", dict(kinds))
    print("spider 类前 15:", sp.most_common(15))
    print("\n前 12 个（夸克优先）:")
    for x in pan[:12]:
        print(f"   {str(x['name'])[:26]:<28} {x['api'][:34]:<36} {x['kinds']}")
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
