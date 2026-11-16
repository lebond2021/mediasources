# -*- coding: utf-8 -*-
"""Q3b: for each config, do csp_XXX class names exist inside its own spider jar/dex?"""
import os, sys, json, zipfile, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, load_json_file, classify, dump, table

L = []
def p(s=""):
    L.append(s)

def dex_blob(path):
    blob = open(path, "rb").read()
    if blob[:2] != b"PK":
        return b"", "not-a-zip"
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return b"", "zip-err"
    dex = b""
    for n in z.namelist():
        if n.endswith(".dex"):
            dex += z.read(n)
    return dex, "dex=%d" % len(dex)

cfgs = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        if not rel.lower().endswith(".json"):
            continue
        r = load_json_file(path)
        if r["ok"] and classify(r["obj"]) == "tvbox-config":
            cfgs.append((repo, rel, r["obj"], path))

cache = {}
p("# per-config spider vs csp_ class coverage")
rows = [("config", "spider", "csp_sites", "distinct_csp", "class_found", "missing_examples")]
for repo, rel, o, path in cfgs:
    sp = o.get("spider") if isinstance(o.get("spider"), str) else ""
    apis = collections.Counter()
    for s in (o.get("sites") or []):
        a = s.get("api") if isinstance(s, dict) else None
        if isinstance(a, str) and a.startswith("csp_"):
            apis[a] += 1
    if not sp:
        rows.append(("%s/%s" % (repo, rel), "(none)", sum(apis.values()), len(apis), "-", "-"))
        continue
    jar = sp.split(";")[0]
    tgt = os.path.normpath(os.path.join(os.path.dirname(path), jar)) if jar.startswith(".") else None
    if tgt is None or not os.path.exists(tgt):
        rows.append(("%s/%s" % (repo, rel), jar[-40:], sum(apis.values()), len(apis), "REMOTE/MISSING", "-"))
        continue
    if tgt not in cache:
        cache[tgt] = dex_blob(tgt)
    dex, note = cache[tgt]
    found = [a for a in apis if ("/" + a[4:] + ";").encode() in dex]
    miss = [a for a in apis if ("/" + a[4:] + ";").encode() not in dex]
    rows.append(("%s/%s" % (repo, rel), os.path.basename(jar)[:26], sum(apis.values()), len(apis),
                 "%d/%d" % (len(found), len(apis)), ", ".join(miss[:3])[:44] or "-"))
p("\n".join(table(rows)))

p("")
p("# jar dex sizes / class-name probe")
for tgt, (dex, note) in sorted(cache.items()):
    p("   %-42s %s %s" % (os.path.relpath(tgt, ROOT)[-42:], note,
                          "has DouDouGuard" if b"DouDouGuard" in dex else ""))

dump("12_spider_match.txt", L)
print("done", len(cfgs))
