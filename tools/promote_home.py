"""把 index_home.json 里实测最好的站提到 index.json 的最前面。

TVBox 在「首页站源」留空时用 sites[0]，所以 sites[0] 必须是一个活的、分类多的采集站，
否则用户一进来就是空首页。这里按 index_home.json 的排序把已验证站点前置，
其余站点顺序不变，站点数量不减。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")


def main() -> int:
    idx_path = os.path.join(DIST, "index.json")
    home_path = os.path.join(DIST, "index_home.json")
    if not (os.path.exists(idx_path) and os.path.exists(home_path)):
        print("缺少 index.json 或 index_home.json")
        return 1

    full = json.load(open(idx_path, encoding="utf-8"))
    home = json.load(open(home_path, encoding="utf-8"))
    sites = full.get("sites") or []
    ranked = home.get("sites") or []
    if not sites or not ranked:
        print("站点为空，跳过")
        return 1

    def sig(s: dict) -> tuple:
        return (str(s.get("api") or ""), json.dumps(s.get("ext"), ensure_ascii=False, sort_keys=True))

    head_sigs = {sig(s) for s in ranked}
    head = [s for s in sites if sig(s) in head_sigs]
    tail = [s for s in sites if sig(s) not in head_sigs]
    # head 内部按 index_home 的顺序（quality 排序）
    order = {sig(s): i for i, s in enumerate(ranked)}
    head.sort(key=lambda s: order.get(sig(s), 999))

    before = sites[0].get("name")
    full["sites"] = head + tail
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False)
    print(f"index.json: {len(sites)} 站  首位 {before} → {full['sites'][0].get('name')}")
    print(f"前置已验证站 {len(head)} 个（其余 {len(tail)} 个顺序不变）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
