# -*- coding: utf-8 -*-
"""Shared helpers: tolerant loading, config classification, results dumping."""
import os, json, io, re, base64, collections

ROOT = r"C:\Users\Nick\Documents\tvbox\sources"
OUT = r"C:\Users\Nick\Documents\tvbox\tools\out"
REPOS = ["cliya", "qist", "tvbox", "tvyuan"]
os.makedirs(OUT, exist_ok=True)


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def decode(raw):
    """Return (text, encoding, notes)."""
    notes = []
    if raw[:3] == b"\xef\xbb\xbf":
        notes.append("BOM")
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig", notes
        except Exception:
            pass
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc), enc, notes
        except Exception:
            continue
    return raw.decode("utf-8", "replace"), "utf-8(replace)", notes + ["undecodable"]


def strip_json5(txt):
    """Remove // and /* */ comments + trailing commas, string-aware."""
    out = []
    i, n = 0, len(txt)
    in_s = False
    q = ""
    while i < n:
        c = txt[i]
        if in_s:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(txt[i + 1])
                    i += 2
                    continue
            elif c == q:
                in_s = False
            i += 1
            continue
        if c in "\"'":
            in_s = True
            q = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and txt[i + 1] == "/":
            j = txt.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and txt[i + 1] == "*":
            j = txt.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    s = "".join(out)
    # trailing commas: ,  }  or , ]
    s2 = re.sub(r",(\s*[}\]])", r"\1", s)
    return s2, s2 != txt


def load_json_file(p):
    """Tolerant load. Returns dict(ok, obj, enc, mode, err, head, raw_len, flags)."""
    raw = read_bytes(p)
    txt, enc, notes = decode(raw)
    res = dict(path=p, size=len(raw), enc=enc, flags=list(notes), mode="raw",
               ok=False, obj=None, err=None, head=txt[:200])
    try:
        res["obj"] = json.loads(txt)
        res["ok"] = True
    except Exception as e:
        res["err"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        s, changed = strip_json5(txt)
        if changed:
            try:
                res["obj"] = json.loads(s)
                res["ok"] = True
                res["mode"] = "json5-clean"
            except Exception as e2:
                res["err2"] = "%s: %s" % (type(e2).__name__, str(e2)[:200])
    # extra flags
    if res["ok"]:
        if re.search(r"(?m)^\s*//", txt) or "/*" in txt:
            res["flags"].append("comments")
        if re.search(r",(\s*[}\]])", txt):
            res["flags"].append("trailing-comma")
    return res


def walk_files(repo):
    base = os.path.join(ROOT, repo)
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d != ".git"]
        for fn in fns:
            p = os.path.join(dp, fn)
            yield repo, os.path.relpath(p, base).replace("\\", "/"), p, os.path.getsize(p)


CONFIG_KEYS = {"sites", "parses", "lives", "spider", "flags", "rules", "ijk", "ads",
               "doh", "hosts", "proxy", "wallpaper", "logo", "notice", "headers",
               "timeout", "style", "ext", "homepage", "urls", "storeHouse",
               "warningText", "danmaku", "sites2"}


def classify(obj):
    if isinstance(obj, list):
        return "json-array"
    if not isinstance(obj, dict):
        return "scalar"
    ks = set(obj.keys())
    if "storeHouse" in ks:
        return "multi-storeHouse"
    if "urls" in ks:
        return "multi-urls"
    if ks & {"sites", "parses", "lives", "spider"}:
        return "tvbox-config"
    if "Classes" in ks or "SiteUrl" in ks:
        return "csp-site-rule"
    if ks & {"分类url", "分类", "线路标题", "播放数组"}:
        return "xyq-spider-rule"
    if ks & {"class", "filters"} and "class" in ks:
        return "class-filters"
    if "classes" in ks:
        return "biliext"
    if ks & {"video", "pan", "read", "comic", "color"}:
        return "cat-open-config"
    return "other-dict"


def dump(name, lines):
    open(os.path.join(OUT, name), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def table(rows, headers=None, widths=None):
    """rows: list of tuples/lists -> aligned text table."""
    data = [[str(c) for c in r] for r in rows]
    cols = len(data[0]) if data else 0
    w = [0] * cols
    for r in data:
        for i, c in enumerate(r):
            w[i] = max(w[i], len(c))
    out = []
    for idx, r in enumerate(data):
        out.append("  ".join(c.ljust(w[i]) for i, c in enumerate(r)))
        if idx == 0 and headers is not False:
            out.append("  ".join("-" * w[i] for i in range(cols)))
    return out
