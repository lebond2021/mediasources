# -*- coding: utf-8 -*-
"""probe: fan.txt, gz files, jar class names (csp_*), cross-repo key overlap."""
import os, sys, json, zipfile, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, decode, dump, table

L = []
def p(s=""):
    L.append(s)

p("# fan.txt head (referenced as spider by 0821/0826/fty)")
for rel in ["qist/jar/fan.txt"]:
    t, enc, n = decode(open(os.path.join(ROOT, rel), "rb").read())
    p("   %s enc=%s len=%d" % (rel, enc, len(t)))
    for line in t.split("\n")[:8]:
        p("   | " + line[:160])

p("")
p("# gz files")
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        if rel.lower().endswith(".gz"):
            p("   %s/%s %d B" % (repo, rel, size))

p("")
p("# jar internals: do csp_* class names exist?")
sites = json.load(open(os.path.join(OUT, "sites_all.json"), encoding="utf-8"))
csp = collections.Counter()
for s in sites:
    a = s.get("api")
    if isinstance(a, str) and a.startswith("csp_"):
        csp[a] += 1
p("distinct csp_ api values: %d" % len(csp))
jars = {
    "qist/jar/spider.jar": None, "qist/jar/pg_upgraded.jar": None,
    "qist/jar/XYQ.jar": None, "qist/jar/XBPQ_upgraded.jar": None,
    "qist/jar/custom_spider.jar": None,
}
for rel in jars:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        p("   %s MISSING" % rel)
        continue
    try:
        z = zipfile.ZipFile(path)
        names = z.namelist()
        p("   %-30s entries=%d" % (rel, len(names)))
        # look for class files whose basename matches csp_ names
        base = {os.path.basename(n) for n in names}
        hit = [a for a in csp if (a + ".class") in base or (a + ".dex") in base]
        p("      csp_ names present as <name>.class: %d / %d  e.g. %s"
          % (len(hit), len(csp), ", ".join(hit[:5])))
        # list some class names to show convention
        cls = [n for n in names if n.endswith(".class")][:0]
        idx = [n for n in names if "classes" in n or n.endswith(".dex")][:6]
        p("      structure sample: " + ", ".join(idx))
    except Exception as e:
        p("   %s ERROR %s" % (rel, e))

p("")
p("# cross-repo key overlap")
byrepo = collections.defaultdict(set)
bykey = collections.defaultdict(set)
for s in sites:
    k = s.get("key")
    if isinstance(k, str):
        byrepo[s["__repo"]].add(k)
        bykey[k].add(s["__repo"])
p("keys in >1 repo: %d" % sum(1 for k, v in bykey.items() if len(v) > 1))
for k, v in sorted(bykey.items(), key=lambda x: -len(x[1]))[:15]:
    if len(v) > 1:
        p("   %-24s %s" % (k, sorted(v)))

p("")
p("# key charset / shape stats")
pat = collections.Counter()
for k in bykey:
    if k.startswith("csp_"):
        pat["csp_ prefix"] += 1
    elif re.fullmatch(r"[A-Za-z0-9_.-]+", k):
        pat["ascii token"] += 1
    elif re.search(r"[\u4e00-\u9fff]", k):
        pat["contains CJK"] += 1
    else:
        pat["other"] += 1
for k, v in pat.most_common():
    p("   %-16s %d" % (k, v))

dump("10_probe.txt", L)
print("done", len(csp))
