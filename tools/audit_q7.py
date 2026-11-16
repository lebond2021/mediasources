# -*- coding: utf-8 -*-
"""Q7: what are qist's 257 JSON files? content-hash mirror analysis + sampling."""
import os, sys, json, hashlib, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, decode, load_json_file, classify, dump, table

L = []
def p(s=""):
    L.append(s)

recs = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        if not rel.lower().endswith(".json"):
            continue
        raw = open(path, "rb").read()
        txt, enc, notes = decode(raw)
        r = load_json_file(path)
        recs.append(dict(repo=repo, rel=rel, path=path, size=size, md5=hashlib.md5(raw).hexdigest(),
                         enc=enc, bom="BOM" in notes, ok=r["ok"], mode=r["mode"],
                         cls=classify(r["obj"]) if r["ok"] else "UNPARSEABLE",
                         obj=r["obj"], txt=txt))

p("# Q7 all .json files: %d" % len(recs))
c = collections.Counter((r["repo"], r["cls"]) for r in recs)
rows = [("repo", "class", "count")]
for (repo, cls), n in sorted(c.items()):
    rows.append((repo, cls, n))
p("\n".join(table(rows)))

# ---- identical content groups
p("")
p("# Q7b identical-content groups (md5), size>1")
g = collections.defaultdict(list)
for r in recs:
    g[r["md5"]].append(r)
groups = [(h, v) for h, v in g.items() if len(v) > 1]
p("distinct contents=%d, groups with >1 file=%d, files inside groups=%d"
  % (len(g), len(groups), sum(len(v) for h, v in groups)))
rows = [("md5", "n", "members")]
for h, v in sorted(groups, key=lambda x: -len(x[1])):
    rows.append((h[:10], len(v), " | ".join("%s/%s" % (x["repo"], x["rel"]) for x in v)[:150]))
p("\n".join(table(rows)))

# ---- qist only: dir distribution & basename duplication
p("")
p("# Q7c qist json by directory")
q = [r for r in recs if r["repo"] == "qist"]
c = collections.Counter((os.path.dirname(r["rel"]) or "(root)", r["cls"]) for r in q)
rows = [("dir", "class", "n")]
for (d, cls), n in sorted(c.items()):
    rows.append((d, cls, n))
p("\n".join(table(rows)))

p("")
p("# Q7d qist: same basename in multiple dirs (mirror pairs)")
bn = collections.defaultdict(list)
for r in q:
    bn[os.path.basename(r["rel"])].append(r)
multi = {k: v for k, v in bn.items() if len(v) > 1}
p("basenames appearing >1: %d" % len(multi))
same = 0
diff = 0
rows = [("basename", "paths", "identical?")]
for k, v in sorted(multi.items()):
    ids = len({x["md5"] for x in v})
    if ids == 1:
        same += 1
    else:
        diff += 1
    rows.append((k, " | ".join(x["rel"] for x in v)[:110], "same" if ids == 1 else "DIFF(%d)" % ids))
p("identical-basename groups=%d, differing=%d" % (same, diff))
p("\n".join(table(rows[:60])))

# ---- sampling: 10 different subdirs
p("")
p("# Q7e sample: 10 files from 10 different subdirs")
dirs = {}
for r in q:
    d = os.path.dirname(r["rel"]) or "(root)"
    dirs.setdefault(d, []).append(r)
picked = []
for d in sorted(dirs):
    cand = sorted(dirs[d], key=lambda x: x["rel"])
    if cand:
        picked.append(cand[0])
p("dirs total=%d" % len(dirs))
for r in picked[:12]:
    p("-- %s  (%d B, %s, %s%s)" % (r["rel"], r["size"], r["cls"], r["mode"], ", BOM" if r["bom"] else ""))
    p("   md5=%s  mirror_of=%s" % (r["md5"][:10], ", ".join(
        "%s/%s" % (x["repo"], x["rel"]) for x in g[r["md5"]] if x["path"] != r["path"]) or "-"))
    if r["ok"]:
        ks = list(r["obj"].keys()) if isinstance(r["obj"], dict) else ["<array len=%d>" % len(r["obj"])]
        p("   top keys: " + ", ".join(map(str, ks[:12])))
        p("   head: " + json.dumps(r["txt"][:150], ensure_ascii=False)[:320])
    else:
        p("   head: " + json.dumps(r["txt"][:150], ensure_ascii=False)[:320])

# ---- reference coverage: which json/js/py are actually referenced by configs?
p("")
p("# Q7f are these files referenced by any config? (by basename)")
allsites = json.load(open(os.path.join(OUT, "sites_all.json"), encoding="utf-8"))
refblob = " ".join(str(s.get("api", "")) + " " + json.dumps(s.get("ext"), ensure_ascii=False)
                   for s in allsites)
unref = []
ref = 0
for r in recs:
    b = os.path.basename(r["rel"])
    if b and b in refblob:
        ref += 1
    else:
        unref.append(r["rel"])
p("json referenced by some sites api/ext: %d / %d" % (ref, len(recs)))
p("unreferenced (first 30): " + ", ".join(unref[:30]))

dump("08_q7.txt", L)
print("json", len(recs), "groups", len(groups), "qistdirs", len(dirs))
