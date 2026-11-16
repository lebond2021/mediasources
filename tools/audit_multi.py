# -*- coding: utf-8 -*-
"""Q5 multi-source (urls / storeHouse) format audit."""
import os, sys, json, re, collections
from urllib.parse import urlsplit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, load_json_file, dump, table

L = []
def p(s=""):
    L.append(s)

found = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        low = rel.lower()
        if not (low.endswith(".json") or low.endswith(".txt")):
            continue
        if low.endswith(".txt") and open(path, "rb").read(1) not in b"{[":
            continue
        r = load_json_file(path)
        if not r["ok"] or not isinstance(r["obj"], dict):
            continue
        o = r["obj"]
        if "urls" in o or "storeHouse" in o:
            found.append((repo, rel, o, r))

p("# Q5 multi-source files: %d" % len(found))
rows = [("repo", "path", "wrapper key", "top keys", "entries", "mode")]
detail = []
for repo, rel, o, r in found:
    key = "storeHouse" if "storeHouse" in o else "urls"
    lst = o.get(key)
    n = len(lst) if isinstance(lst, list) else -1
    rows.append((repo, rel, key, ",".join(sorted(o.keys())), n, r["mode"]))
    detail.append((repo, rel, key, lst))
p("\n".join(table(rows)))

# entry schema per wrapper
p("")
p("# Q5b entry field schema")
for repo, rel, key, lst in detail:
    if not isinstance(lst, list):
        continue
    kf = collections.Counter()
    for e in lst:
        if isinstance(e, dict):
            for k in e.keys():
                kf[k] += 1
        else:
            kf["<non-dict:" + type(e).__name__ + ">"] += 1
    p("%s/%s [%s] n=%d fields=%s" % (repo, rel, key, len(lst), dict(kf)))

# url shape stats over all entries
p("")
p("# Q5c entry value shapes (all multi files combined)")
urls, names, schemes = [], [], collections.Counter()
for repo, rel, key, lst in detail:
    if not isinstance(lst, list):
        continue
    for e in lst:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or e.get("sourceUrl")
        nm = e.get("name") if "name" in e else e.get("sourceName")
        if isinstance(u, str):
            urls.append((repo, rel, u))
            schemes[urlsplit(u).scheme.lower() if "://" in u else "(no-scheme)"] += 1
        if nm is not None:
            names.append((repo, rel, nm))
p("total url entries=%d, name entries=%d" % (len(urls), len(names)))
p("scheme hist: " + json.dumps(dict(schemes.most_common()), ensure_ascii=False))

p("")
p("# Q5d duplicate sourceUrl within one multi file")
for repo, rel, key, lst in detail:
    if not isinstance(lst, list):
        continue
    us = [ (e.get("url") or e.get("sourceUrl")) for e in lst if isinstance(e, dict)]
    c = collections.Counter(u for u in us if isinstance(u, str))
    dups = {k: v for k, v in c.items() if v > 1}
    p("%s/%s: entries=%d unique_url=%d dups=%s" % (repo, rel, len(us), len(set(us)),
      json.dumps(dups, ensure_ascii=False)[:300] if dups else "none"))

p("")
p("# Q5e name/latency convention")
lat = 0
for repo, rel, key, lst in detail:
    if not isinstance(lst, list):
        continue
    for e in lst:
        if not isinstance(e, dict):
            continue
        nm = e.get("name") or e.get("sourceName") or ""
        if re.match(r"^\[\d+ms\]", nm):
            lat += 1
p("names starting with [<n>ms]: %d / %d" % (lat, len(names)))
for repo, rel, nm in names[:8]:
    p("   %-40s %s" % (("%s/%s" % (repo, rel))[:40], nm))

p("")
p("# Q5f nested multi (url pointing at another multi file in the repo set)")
allnames = {os.path.basename(rel) for repo, rel, key, lst in detail}
for repo, rel, key, lst in detail:
    if not isinstance(lst, list):
        continue
    for e in lst:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or e.get("sourceUrl") or ""
        b = os.path.basename(urlsplit(u).path)
        if b in allnames and b:
            p("   %s/%s -> %s" % (repo, rel, u))

# full dump of small ones for the report
p("")
p("# Q5g full content of small multi files (<=15 entries)")
for repo, rel, key, lst in detail:
    if isinstance(lst, list) and len(lst) <= 15:
        p("-- %s/%s" % (repo, rel))
        for e in lst:
            p("   " + json.dumps(e, ensure_ascii=False)[:160])

dump("05_multi.txt", L)
print("multi files", len(found))
