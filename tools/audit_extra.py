# -*- coding: utf-8 -*-
"""Q1 extras: live files, jar dir, js/py inventory, ext form samples."""
import os, sys, json, re, collections, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, decode, load_json_file, dump, table

L = []
def p(s=""):
    L.append(s)

# ---------- live files
p("# Q1a live source files (.txt/.m3u not JSON)")
rows = [("repo", "path", "bytes", "lines", "encoding", "#genre#", "http lines", "dup urls")]
livefiles = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        low = rel.lower()
        if not (low.endswith(".txt") or low.endswith(".m3u") or low.endswith(".m3u8")):
            continue
        raw = open(path, "rb").read()
        if raw[:1] in b"{[":
            continue
        txt, enc, notes = decode(raw)
        lines = [x for x in txt.replace("\r\n", "\n").split("\n")]
        nonempty = [x for x in lines if x.strip()]
        urls = [x for x in nonempty if re.search(r"https?://", x)]
        us = set()
        for x in urls:
            m = re.findall(r"https?://\S+", x)
            for u in m:
                us.add(u)
        livefiles.append((repo, rel, path, size, txt, nonempty, urls))
        rows.append((repo, rel, size, len(nonempty), enc,
                     "yes" if "#genre#" in txt else "-",
                     len(urls), len(urls) - len(us)))
p("\n".join(table(rows)))
p("")
p("total live-ish files: %d" % len(livefiles))

p("")
p("# Q1b live file format samples (first 6 non-empty lines)")
for repo, rel, path, size, txt, nonempty, urls in livefiles:
    p("-- %s/%s  (%d lines)" % (repo, rel, len(nonempty)))
    for x in nonempty[:6]:
        p("   " + x[:150])

p("")
p("# Q1c live line-shape classification across all live files")
shapes = collections.Counter()
for repo, rel, path, size, txt, nonempty, urls in livefiles:
    for x in nonempty:
        if x.startswith("#genre#") or re.match(r"^[^,]+,\s*#genre#", x):
            shapes["genre-header (name,#genre#)"] += 1
        elif x.startswith("#"):
            shapes["comment/other #"] += 1
        elif x.count(",") >= 2:
            shapes["name,url,extra(,)"] += 1
        elif x.count(",") == 1:
            shapes["name,url"] += 1
        elif re.match(r"^https?://", x):
            shapes["bare url"] += 1
        elif x.startswith(("EXTINF", "#EXTM3U", "#EXT")):
            shapes["m3u directive"] += 1
        else:
            shapes["other"] += 1
for k, v in shapes.most_common():
    p("   %-30s %d" % (k, v))

# ---------- jar
p("")
p("# Q1d jar files (spider jars)")
rows = [("repo", "path", "bytes", "md5", "sidecar")]
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        if rel.lower().endswith((".jar", ".md5")):
            md5 = hashlib.md5(open(path, "rb").read()).hexdigest() if rel.lower().endswith(".jar") else ""
            sc = ""
            if rel.lower().endswith(".jar"):
                for cand in (path + ".md5", path[:-4] + ".md5"):
                    if os.path.exists(cand):
                        sc = os.path.basename(cand)
            rows.append((repo, rel, size, md5, sc or "-"))
p("\n".join(table(rows)))

# ---------- js / py inventory
p("")
p("# Q1e js / py counts by directory (top 25 dirs)")
c = collections.Counter()
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        low = rel.lower()
        if low.endswith((".js", ".py")):
            d = os.path.dirname(rel) or "(root)"
            c[(repo, d, os.path.splitext(low)[1])] += 1
for (repo, d, ext), n in sorted(c.items(), key=lambda x: -x[1])[:25]:
    p("   %-8s %-24s %-4s %d" % (repo, d[:24], ext, n))

p("")
p("# Q1f py tools in qist (file list with sizes, top 25 by size)")
rows = [("path", "bytes")]
pys = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        if rel.lower().endswith(".py"):
            pys.append((repo, rel, size))
for repo, rel, size in sorted(pys, key=lambda x: -x[2])[:25]:
    rows.append(("%s/%s" % (repo, rel), size))
p("\n".join(table(rows)))

# ---------- ext samples
p("")
p("# Q1g ext form samples (3 per form)")
sites = json.load(open(os.path.join(OUT, "sites_all.json"), encoding="utf-8"))
forms = collections.defaultdict(list)
def form_of(v):
    if "ext" not in v:
        return "missing"
    e = v["ext"]
    if e is None:
        return "null"
    if isinstance(e, dict):
        return "json-obj"
    if isinstance(e, list):
        return "json-array"
    if not isinstance(e, str):
        return "nonstr:" + type(e).__name__
    s = e.strip()
    if s == "":
        return "empty"
    if s.startswith(("http://", "https://")):
        return "url"
    if s.startswith("{") or s.startswith("["):
        return "json-str"
    if re.fullmatch(r"[A-Za-z0-9+/=\s]{20,}", s):
        return "likely-base64"
    return "other-str"
for s in sites:
    forms[form_of(s)].append(s)
for f, lst in sorted(forms.items(), key=lambda x: -len(x[1])):
    p("-- %s n=%d" % (f, len(lst)))
    seen = 0
    for s in lst:
        if seen >= 3:
            break
        e = s.get("ext")
        p("   key=%-18s api=%-30s ext=%s" % (str(s.get("key"))[:18], str(s.get("api"))[:30],
                                             json.dumps(e, ensure_ascii=False)[:120]))
        seen += 1

dump("07_extra.txt", L)
print("live", len(livefiles), "forms", dict((k, len(v)) for k, v in forms.items()))
