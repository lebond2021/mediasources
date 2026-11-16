# -*- coding: utf-8 -*-
"""Q6 bad-data inventory: raw-parse failures, BOM, comments, trailing commas, base64."""
import os, sys, json, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, decode, strip_json5, dump, table, load_json_file

L = []
def p(s=""):
    L.append(s)

B64 = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
cands = []
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        low = rel.lower()
        if not (low.endswith(".json") or low.endswith(".txt")):
            continue
        head = open(path, "rb").read(1)
        if low.endswith(".txt") and head not in b"{[":
            continue
        cands.append((repo, rel, path, size))

p("# Q6 candidate files (json + json-in-txt): %d" % len(cands))
rows = []
fails = []
for repo, rel, path, size in cands:
    raw = open(path, "rb").read()
    txt, enc, notes = decode(raw)
    row = dict(repo=repo, rel=rel, size=size, enc=enc, bom="BOM" in notes)
    # raw parse
    try:
        json.loads(txt)
        row["raw_ok"] = True
        row["err"] = ""
    except Exception as e:
        row["raw_ok"] = False
        msg = "%s: %s" % (type(e).__name__, e)
        row["err"] = msg
        m = re.search(r"line (\d+) column (\d+)", msg)
        row["line"] = int(m.group(1)) if m else -1
        row["col"] = int(m.group(2)) if m else -1
    # comments (outside strings, crude but string-aware via strip_json5 difference)
    cleaned, changed = strip_json5(txt)
    row["json5_changed"] = changed
    row["comments"] = bool(re.search(r"(?m)^\s*//|^\s*/\*|\*/", txt)) or ("/*" in txt)
    row["trailing"] = bool(re.search(r",(\s*[}\]])", txt))
    try:
        json.loads(cleaned)
        row["clean_ok"] = True
    except Exception as e:
        row["clean_ok"] = False
        row["err2"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    row["b64"] = len(B64.findall(txt))
    row["head"] = txt[:200]
    rows.append(row)
    if not row["raw_ok"]:
        fails.append(row)

tot = len(rows)
raw_ok = sum(1 for r in rows if r["raw_ok"])
clean_ok = sum(1 for r in rows if r["clean_ok"])
p("")
p("raw json.loads OK      : %d / %d = %.1f%%" % (raw_ok, tot, 100.0 * raw_ok / tot))
p("after json5 cleaning OK: %d / %d = %.1f%%" % (clean_ok, tot, 100.0 * clean_ok / tot))
p("BOM files              : %d" % sum(1 for r in rows if r["bom"]))
p("files with comments    : %d" % sum(1 for r in rows if r["comments"]))
p("files with trailing ,  : %d" % sum(1 for r in rows if r["trailing"]))
p("files w/ base64 >=40   : %d" % sum(1 for r in rows if r["b64"]))

p("")
p("# Q6b files failing raw json.loads (%d)" % len(fails))
rows2 = [("repo", "path", "line", "col", "err", "json5-fixable")]
for r in sorted(fails, key=lambda x: (x["repo"], x["rel"])):
    rows2.append((r["repo"], r["rel"], r["line"], r["col"],
                  r["err"].split(":", 1)[-1][:70], "YES" if r["clean_ok"] else "NO"))
p("\n".join(table(rows2)))

p("")
p("# Q6c first 200 chars of each raw-failure")
for r in sorted(fails, key=lambda x: (x["repo"], x["rel"])):
    p("-- %s/%s (line %s col %s)" % (r["repo"], r["rel"], r["line"], r["col"]))
    p("   " + json.dumps(r["head"], ensure_ascii=False)[:400])
    if "err2" in r:
        p("   STILL BROKEN AFTER CLEAN: " + r["err2"])

p("")
p("# Q6d BOM / comments / trailing-comma file lists")
for flag in ("bom", "comments", "trailing"):
    p("-- %s" % flag)
    for r in rows:
        if r[flag]:
            p("   %s/%s" % (r["repo"], r["rel"]))

p("")
p("# Q6e base64-bearing files")
for r in sorted(rows, key=lambda x: -x["b64"])[:15]:
    if r["b64"]:
        p("   %-46s tokens=%d" % (("%s/%s" % (r["repo"], r["rel"]))[:46], r["b64"]))

dumped = [{k: v for k, v in r.items() if k != "head"} for r in rows]
json.dump(dumped, open(os.path.join(OUT, "bad_rows.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
dump("06_bad.txt", L)
print("cands", tot, "raw_ok", raw_ok, "clean_ok", clean_ok, "fails", len(fails))
