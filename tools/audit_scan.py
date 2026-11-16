# -*- coding: utf-8 -*-
"""Step 1 recon: inventory + which JSON files parse, and their top-level shape."""
import os, sys, json, io, collections

ROOT = r"C:\Users\Nick\Documents\tvbox\sources"
OUT = r"C:\Users\Nick\Documents\tvbox\tools\out"
os.makedirs(OUT, exist_ok=True)

REPOS = ["cliya", "qist", "tvbox", "tvyuan"]


def load_any(path):
    """Return (obj, encoding, err) - tries utf-8-sig, utf-8, gbk."""
    raw = open(path, "rb").read()
    if raw[:3] == b"\xef\xbb\xbf":
        encs = ["utf-8-sig", "utf-8", "gbk"]
    else:
        encs = ["utf-8", "gbk", "utf-8-sig"]
    last = None
    for enc in encs:
        try:
            txt = raw.decode(enc)
        except Exception as e:
            last = ("decode:" + enc + ":" + str(e)[:120])
            continue
        try:
            return json.loads(txt), enc, None, txt
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            return None, enc, last, txt
    return None, None, last, None


def main():
    rows = []          # per json file
    ext_hist = collections.Counter()
    size_hist = collections.Counter()
    allfiles = []
    for repo in REPOS:
        base = os.path.join(ROOT, repo)
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d != ".git"]
            for fn in fns:
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, base)
                allfiles.append((repo, rel, os.path.getsize(p)))
                ext_hist["." + fn.rsplit(".", 1)[-1].lower() if "." in fn else "(none)"] += 1

    # treat every file that could carry json: .json + .txt (some are json) + extensionless
    for repo, rel, size in allfiles:
        ext = ("." + rel.rsplit(".", 1)[-1].lower()) if "." in rel else ""
        if ext not in (".json", ".txt", "") and not rel.lower().endswith((".json", ".txt", ".webp")):
            continue
        p = os.path.join(ROOT, repo, rel)
        try:
            head = open(p, "rb").read(1)
        except Exception:
            continue
        if head not in (b"{", b"[", b"\xef", b" ", b"\n", b"\r", b"\t"):
            continue
        obj, enc, err, txt = load_any(p)
        top = None
        kind = None
        if obj is not None:
            if isinstance(obj, dict):
                top = sorted(obj.keys())
                kind = "dict"
            elif isinstance(obj, list):
                kind = "list[%d]" % len(obj)
            else:
                kind = type(obj).__name__
        rows.append(dict(repo=repo, rel=rel.replace("\\", "/"), size=size,
                         ok=obj is not None, enc=enc, err=err, kind=kind, top=top,
                         head=(txt[:200] if txt else "")))

    # top-level key histogram over dict configs
    keyfreq = collections.Counter()
    prefixes = collections.Counter()
    for r in rows:
        if r["ok"] and r["kind"] == "dict":
            for k in r["top"]:
                keyfreq[k] += 1

    with io.open(os.path.join(OUT, "scan.json"), "w", encoding="utf-8") as f:
        json.dump(dict(rows=rows, ext_hist=dict(ext_hist), keyfreq=dict(keyfreq)), f,
                  ensure_ascii=False, indent=1)

    # human summary
    lines = []
    lines.append("EXT HIST: " + json.dumps(dict(ext_hist.most_common()), ensure_ascii=False))
    lines.append("")
    per = collections.Counter()
    for r in rows:
        per[(r["repo"], r["ok"])] += 1
    lines.append("CANDIDATE FILES per repo (ok): " + json.dumps({"|".join(map(str, k)): v for k, v in per.items()}, ensure_ascii=False))
    lines.append("")
    lines.append("== top-level key freq (dict-parseable files only) ==")
    for k, v in keyfreq.most_common(80):
        lines.append("%-24s %d" % (k, v))
    lines.append("")
    lines.append("== per-file ==")
    for r in rows:
        lines.append("%-7s %-58s %8d ok=%s enc=%s kind=%s err=%s top=%s" % (
            r["repo"], r["rel"][:58], r["size"], r["ok"], r["enc"], r["kind"],
            (r["err"] or "")[:90], (",".join(r["top"] or [])[:120])))
    open(os.path.join(OUT, "scan.txt"), "w", encoding="utf-8").write("\n".join(lines))
    print("rows", len(rows), "files", len(allfiles))


if __name__ == "__main__":
    main()
