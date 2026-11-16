"""发布后冒烟测试：拉公网链接 → 校验结构 → 抽查 spider 与站点级 jar 可达性。"""
from __future__ import annotations

import collections
import json
import random
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
URL = sys.argv[1] if len(sys.argv) > 1 else "https://pomf2.lain.la/f/wn0goigg.json"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}

r = requests.get(URL, headers=UA, timeout=120)
print(f"GET {URL} → {r.status_code} {len(r.content)/1024:.0f}KB ct={r.headers.get('content-type')}")
cfg = r.json()
sites = cfg.get("sites") or []
print(f"sites={len(sites)} parses={len(cfg.get('parses') or [])} "
      f"lives={len(cfg.get('lives') or [])} spider={cfg.get('spider')}")

keys = [s.get("key") for s in sites]
print(f"key 唯一: {len(set(keys)) == len(keys)}  重名: "
      f"{len(sites) - len({s.get('name') for s in sites})}")

types = collections.Counter(s.get("type") for s in sites)
print("type:", dict(sorted(types.items(), key=lambda x: -x[1])))
jarred = sum(1 for s in sites if s.get("jar"))
print(f"站点级 jar: {jarred}")


def head(u: str) -> str:
    try:
        rr = requests.get(u, headers={**UA, "Range": "bytes=0-1023"}, timeout=25,
                          stream=True)
        return f"{rr.status_code} {rr.headers.get('content-type', '')[:30]}"
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}"


print("spider:", head(cfg.get("spider", "")))
random.seed(7)
sample = random.sample([s["jar"] for s in sites if s.get("jar")], k=min(6, jarred))
for u in sample:
    print("  jar:", head(u), u[:90])

bad = [s for s in sites if not s.get("api") or not s.get("key") or not s.get("name")]
print(f"缺字段站点: {len(bad)}")
spaces = [s for s in sites if any(" " in str(s.get(k, "")) for k in ("api", "ext", "jar"))]
print(f"含空格的 URL: {len(spaces)}")
