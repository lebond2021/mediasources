"""对已判可播的站点补测「播放线路域名」，用于识别同一后端的马甲站。

用法：
    py tools/rate_hosts.py --quality data/state/site_quality2.json --out data/state/site_hosts.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rate_sites import rate_site  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default=os.path.join(ROOT, "data", "state", "site_quality2.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "state", "site_hosts.json"))
    ap.add_argument("--workers", type=int, default=28)
    ap.add_argument("--timeout", type=float, default=7.0)
    ap.add_argument("--min-kbps", type=float, default=200.0)
    args = ap.parse_args()

    doc = json.load(open(args.quality, encoding="utf-8"))
    rows = [r for r in doc.get("sites") or []
            if r.get("url_ok") and float(r.get("kbps") or 0) >= args.min_kbps]
    print(f"补测 {len(rows)} 个可播站点的线路域名")

    out: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(rate_site, {"key": r.get("key"), "name": r.get("name"), "api": r.get("api")},
                          args.timeout): r for r in rows}
        for f in cf.as_completed(futs):
            try:
                out.append(f.result())
            except Exception:
                pass

    hosts: dict[str, list[str]] = {}
    for r in out:
        h = r.get("host") or ""
        if h:
            hosts.setdefault(h, []).append(r.get("api") or "")
    json.dump({"ts": 0, "sites": out, "hosts": hosts},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"线路域名 {len(hosts)} 个")
    for h, apis in sorted(hosts.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"   {len(apis):>3} 站共用 {h}")
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
