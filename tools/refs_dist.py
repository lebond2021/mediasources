"""阈值统计：不同「被引用次数」门槛下保留多少站点。"""
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
docs = json.load(open(os.path.join(ROOT, "data", "state", "docs.json"), encoding="utf-8"))

from tvh.dedupe import dedupe_sites  # noqa: E402
from tvh.util import absolutize  # noqa: E402

sites = []
for d in docs:
    base = d.get("url") or ""
    for s in d.get("sites") or []:
        s = dict(s)
        for k in ("api", "ext", "jar"):
            if k in s:
                s[k] = absolutize(s.get(k), base)
        s["_src"] = (d.get("globals") or {}).get("_name") or base
        sites.append(s)
recs = dedupe_sites(sites)
refs = Counter(len(r.sources) for r in recs)
print("dedup", len(recs))
for th in (2, 3, 5, 10, 20, 50, 100):
    n = sum(v for k, v in refs.items() if k >= th)
    print(f"  refs >= {th:<4}: {n}")
csp = [r for r in recs if str(r.data.get("api", "")).lower().startswith("csp_")]
print("csp sites", len(csp))
cls = Counter(str(r.data.get("api")) for r in csp)
print("distinct csp classes", len(cls), cls.most_common(6))
