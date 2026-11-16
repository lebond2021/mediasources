# -*- coding: utf-8 -*-
"""Inventory + classification of every file in the 4 repos."""
import os, json, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, load_json_file, classify, dump, table

L = []
def p(s=""):
    L.append(s)

inv = collections.defaultdict(lambda: dict(files=0, dirs=set(), byext=collections.Counter(), size=0))
for repo in REPOS:
    base = os.path.join(ROOT, repo)
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d != ".git"]
        for d in dns:
            inv[repo]["dirs"].add(os.path.relpath(os.path.join(dp, d), base).replace("\\", "/"))
    for repo2, rel, path, size in walk_files(repo):
        ext = ("." + rel.rsplit(".", 1)[-1].lower()) if "." in rel else "(noext)"
        inv[repo]["files"] += 1
        inv[repo]["byext"][ext] += 1
        inv[repo]["size"] += size

p("# 01 inventory")
p("")
rows = [("repo", "files", "dirs", "bytes", "top ext")]
for repo in REPOS:
    i = inv[repo]
    top = ", ".join("%s=%d" % (k, v) for k, v in i["byext"].most_common(9))
    rows.append((repo, i["files"], len(i["dirs"]), "%,d" % i["size"] if False else "{:,}".format(i["size"]), top))
p("\n".join(table(rows)))
p("")
p("## directories (non-.git)")
for repo in REPOS:
    ds = sorted(inv[repo]["dirs"])
    p("%s (%d): %s" % (repo, len(ds), ", ".join(ds) if ds else "(flat)"))

# ---- classify all json-ish files
p("")
p("# json-ish candidates per repo")
cat = collections.defaultdict(collections.Counter)
catfiles = collections.defaultdict(list)
records = []
for repo in REPOS:
    for repo2, rel, path, size in walk_files(repo):
        low = rel.lower()
        if not (low.endswith(".json") or low.endswith(".txt")):
            continue
        head = open(path, "rb").read(1)
        if low.endswith(".txt") and head not in b"{[":
            continue
        r = load_json_file(path)
        cls = classify(r["obj"]) if r["ok"] else "UNPARSEABLE"
        r["repo"], r["rel"], r["cls"] = repo, rel, cls
        records.append(r)
        cat[repo][cls] += 1
        catfiles[repo].append((rel, cls, r["ok"], r["mode"], r["flags"]))

rows = [("repo", "tvbox-config", "multi-urls", "multi-storeHouse", "csp-site-rule",
         "xyq-spider-rule", "class-filters", "biliext", "cat-open-config", "json-array",
         "other-dict", "UNPARSEABLE", "TOTAL")]
order = rows[0][1:-1]
for repo in REPOS:
    rows.append([repo] + [cat[repo].get(k, 0) for k in order] + [sum(cat[repo].values())])
p("")
p("\n".join(table(rows)))
p("")
p("## config-json locations by directory (tvbox-config + multi-*)")
loc = collections.defaultdict(lambda: collections.Counter())
for r in records:
    if r["cls"] in ("tvbox-config", "multi-urls", "multi-storeHouse"):
        d = os.path.dirname(r["rel"]) or "(root)"
        loc[r["repo"]][d] += 1
for repo in REPOS:
    if loc[repo]:
        p("%s: %s" % (repo, dict(loc[repo])))
    else:
        p("%s: none" % repo)

p("")
p("# per-file classification")
for repo in REPOS:
    p("== %s ==" % repo)
    for rel, cls, ok, mode, flags in catfiles[repo]:
        p("  %-62s %-18s ok=%s %s %s" % (rel[:62], cls, ok, mode, ",".join(flags)))

json.dump([{k: v for k, v in r.items() if k != "obj"} for r in records],
          open(os.path.join(OUT, "records_meta.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
dump("01_inventory.txt", L)
print("\n".join(L[:40]))
