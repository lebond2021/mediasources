# -*- coding: utf-8 -*-
"""Q2b: sub-schemas of parses/lives/rules/ads/flags/doh/ijk + dangling relative refs."""
import os, sys, json, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, load_json_file, classify, dump, table

L = []
def p(s=""):
    L.append(s)

cfgs = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        if not rel.lower().endswith(".json"):
            continue
        r = load_json_file(path)
        if r["ok"] and classify(r["obj"]) == "tvbox-config":
            cfgs.append((repo, rel, r["obj"], path))

p("# configs: %d" % len(cfgs))

def sub(key, maxsamples=4):
    p("")
    p("# -- %s --" % key)
    cnt = collections.Counter()
    n_files = 0
    samples = []
    types = collections.Counter()
    for repo, rel, o, path in cfgs:
        v = o.get(key)
        if v is None:
            continue
        n_files += 1
        types[type(v).__name__] += 1
        if isinstance(v, list):
            for e in v:
                if isinstance(e, dict):
                    for k in e:
                        cnt[k] += 1
                    if len(samples) < maxsamples:
                        samples.append((repo, rel, e))
                else:
                    cnt["<" + type(e).__name__ + ">"] += 1
        elif isinstance(v, str):
            cnt["<str value>"] += 1
    p("files=%d value types=%s" % (n_files, dict(types)))
    if cnt:
        rows = [("field", "count")]
        for k, c in cnt.most_common(30):
            rows.append((k, c))
        p("\n".join(table(rows)))
    for repo, rel, e in samples:
        p("   sample @%s: %s" % (rel, json.dumps(e, ensure_ascii=False)[:220]))

for k in ("parses", "lives", "rules", "ads", "flags", "doh", "ijk", "hosts"):
    sub(k)

# ---- relative refs: dangling check
p("")
p("# Q2c relative reference resolution (./xxx in sites api/ext) vs files present in repo")
refs = collections.Counter()
missing = collections.Counter()
for repo, rel, o, path in cfgs:
    base = os.path.dirname(path)
    for s in (o.get("sites") or []):
        if not isinstance(s, dict):
            continue
        vals = [s.get("api")]
        e = s.get("ext")
        if isinstance(e, str):
            vals.append(e)
        for v in vals:
            if isinstance(v, str) and (v.startswith("./") or v.startswith("../")):
                tgt = os.path.normpath(os.path.join(base, v))
                ok = os.path.exists(tgt)
                refs[(repo, "resolved" if ok else "MISSING")] += 1
                if not ok:
                    missing[(repo, rel, v)] += 1
rows = [("repo", "status", "count")]
for (repo, st), n in sorted(refs.items()):
    rows.append((repo, st, n))
p("\n".join(table(rows)))
p("missing detail (top 25):")
for (repo, rel, v), n in missing.most_common(25):
    p("   %s/%s -> %s x%d" % (repo, rel, v, n))

# spider refs
p("")
p("# Q2d spider value per config + jar existence")
rows = [("file", "spider value", "resolves?")]
for repo, rel, o, path in cfgs:
    sp = o.get("spider")
    if not isinstance(sp, str):
        rows.append(("%s/%s" % (repo, rel), repr(sp), "-"))
        continue
    ok = "-"
    if sp.startswith("./"):
        ok = "yes" if os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), sp.split(";")[0]))) else "NO"
    elif sp.startswith("http"):
        ok = "remote"
    rows.append(("%s/%s" % (repo, rel), sp[:70], ok))
p("\n".join(table(rows)))

# lives url forms
p("")
p("# Q2e lives[].url forms across configs")
forms = collections.Counter()
ex = {}
for repo, rel, o, path in cfgs:
    for l in (o.get("lives") or []):
        if not isinstance(l, dict):
            continue
        u = l.get("url")
        if not isinstance(u, str):
            k = "nonstr"
        elif u.startswith("http"):
            k = "http"
        elif u.startswith("./"):
            k = "relative"
        elif u.startswith("clan://"):
            k = "clan://"
        elif u == "":
            k = "empty"
        else:
            k = "other:" + u[:20]
        forms[k] += 1
        ex.setdefault(k, (rel, json.dumps(l, ensure_ascii=False)[:150]))
for k, n in forms.most_common(15):
    p("   %-14s %d   e.g. %s" % (k, n, ex[k][1]))

dump("09_sub.txt", L)
print("ok", len(cfgs))
