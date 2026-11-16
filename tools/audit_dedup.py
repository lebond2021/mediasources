# -*- coding: utf-8 -*-
"""Q4 cross-source duplication measurement + proof cases."""
import os, sys, json, re, collections, unicodedata
from urllib.parse import urlsplit, urlunsplit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import OUT, dump, table

L = []
def p(s=""):
    L.append(s)

sites = json.load(open(os.path.join(OUT, "sites_all.json"), encoding="utf-8"))


def norm_api(v):
    if not isinstance(v, str):
        return "\x00" + repr(v)
    s = v.strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith(("http://", "https://")):
        try:
            u = urlsplit(s)
            host = u.netloc.lower()
            host = re.sub(r":(80|443)$", "", host)
            path = u.path.rstrip("/")
            q = u.query
            return urlunsplit((u.scheme.lower(), host, path, q, ""))
        except Exception:
            return low
    if s.startswith("./"):
        return s[2:].lower()
    return s.lower()


def norm_name(v):
    if not isinstance(v, str):
        return ""
    s = v
    # drop separators / emoji / brackets, keep CJK + alnum
    s = "".join(ch for ch in s if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return s.lower()


def norm_key(v):
    if not isinstance(v, str):
        return "\x00" + repr(v)
    return v.strip().lower()


for s in sites:
    s["_api"] = norm_api(s.get("api"))
    s["_name"] = norm_name(s.get("name"))
    s["_key"] = norm_key(s.get("key"))
    t = s.get("type")
    s["_type"] = "missing" if "type" not in s else str(t) if isinstance(t, int) else "nonint"

N = len(sites)
p("# Q4 dedup measurement over %d site entries from 20 config files" % N)
p("")
combos = [
    ("raw entries", lambda s: id(s)),
    ("(type, api) normalized", lambda s: (s["_type"], s["_api"])),
    ("(api) only", lambda s: s["_api"]),
    ("name normalized", lambda s: s["_name"]),
    ("key only", lambda s: s["_key"]),
    ("(name, api)", lambda s: (s["_name"], s["_api"])),
    ("(key, api)", lambda s: (s["_key"], s["_api"])),
    ("(key, type, api)", lambda s: (s["_key"], s["_type"], s["_api"])),
]
rows = [("dedup key", "unique", "dup count", "dedup rate", "remaining %")]
for label, fn in combos:
    seen = set()
    for s in sites:
        seen.add(fn(s))
    u = len(seen) if label != "raw entries" else N
    rows.append((label, u, N - u, "%.1f%%" % (100.0 * (N - u) / N), "%.1f%%" % (100.0 * u / N)))
p("\n".join(table(rows)))

# per repo
p("")
p("# Q4b per-repo uniqueness (within repo)")
rows = [("repo", "entries", "uniq(type,api)", "uniq(name)", "uniq(key)", "uniq(key,type,api)")]
for repo in ["cliya", "qist", "tvyuan", "tvbox"]:
    sub = [s for s in sites if s.get("__repo") == repo]
    if not sub:
        rows.append((repo, 0, "-", "-", "-", "-"))
        continue
    rows.append((repo, len(sub),
                 len({(s["_type"], s["_api"]) for s in sub}),
                 len({s["_name"] for s in sub}),
                 len({s["_key"] for s in sub}),
                 len({(s["_key"], s["_type"], s["_api"]) for s in sub})))
p("\n".join(table(rows)))

# per file
p("")
p("# Q4c per-file uniqueness")
rows = [("file", "entries", "uniq(type,api)", "uniq(key)", "uniq(name)")]
byfile = collections.defaultdict(list)
for s in sites:
    byfile[(s["__repo"], s["__file"])].append(s)
for (repo, rel), sub in sorted(byfile.items(), key=lambda x: -len(x[1])):
    rows.append(("%s/%s" % (repo, rel), len(sub),
                 len({(s["_type"], s["_api"]) for s in sub}),
                 len({s["_key"] for s in sub}),
                 len({s["_name"] for s in sub})))
p("\n".join(table(rows)))

# ---- proof cases
p("")
p("# Q4d PROOF: same key, different api")
bykey = collections.defaultdict(list)
for s in sites:
    bykey[s["_key"]].append(s)
cases = 0
for k, lst in sorted(bykey.items(), key=lambda x: -len({s["_api"] for s in x[1]})):
    apis = {s["_api"] for s in lst}
    if len(apis) < 2 or not k:
        continue
    p("-- key=%r : %d entries, %d distinct api" % (k, len(lst), len(apis)))
    shown = set()
    for s in lst:
        if s["_api"] in shown:
            continue
        shown.add(s["_api"])
        p("     api=%-70s name=%-18s type=%s  @%s/%s" % (
            str(s.get("api"))[:70], str(s.get("name"))[:18], s["_type"], s["__repo"], s["__file"]))
        if len(shown) >= 4:
            break
    cases += 1
    if cases >= 6:
        break

p("")
p("# Q4e PROOF: same api, different key")
byapi = collections.defaultdict(list)
for s in sites:
    if s["_api"]:
        byapi[s["_api"]].append(s)
cases = 0
for a, lst in sorted(byapi.items(), key=lambda x: -len({s["_key"] for s in x[1]})):
    keys = {s["_key"] for s in lst}
    if len(keys) < 2:
        continue
    p("-- api=%s : %d entries, %d distinct key" % (a[:70], len(lst), len(keys)))
    shown = set()
    for s in lst:
        if s["_key"] in shown:
            continue
        shown.add(s["_key"])
        p("     key=%-22s name=%-18s type=%s  @%s/%s" % (
            str(s.get("key"))[:22], str(s.get("name"))[:18], s["_type"], s["__repo"], s["__file"]))
        if len(shown) >= 4:
            break
    cases += 1
    if cases >= 6:
        break

# ---- same api different csp_ prefix situation
p("")
p("# Q4f key prefix vs api prefix mismatch (csp_ keys whose api is not csp_)")
mism = [s for s in sites if s["_key"].startswith("csp_") and not str(s.get("api", "")).startswith("csp_")]
p("count=%d" % len(mism))
for s in mism[:5]:
    p("   key=%s api=%s @%s" % (s.get("key"), str(s.get("api"))[:60], s["__file"]))
mism2 = [s for s in sites if not s["_key"].startswith("csp_") and str(s.get("api", "")).startswith("csp_")]
p("reverse (api csp_*, key not csp_): count=%d" % len(mism2))
for s in mism2[:5]:
    p("   key=%s api=%s @%s" % (s.get("key"), str(s.get("api"))[:60], s["__file"]))

# how many csp_ keys resolve against spider jar? (can't check jar internals, but note)
p("")
p("# Q4g api host frequency (top 15)")
hosts = collections.Counter()
for s in sites:
    a = s.get("api")
    if isinstance(a, str) and a.startswith("http"):
        try:
            hosts[urlsplit(a).netloc.lower()] += 1
        except Exception:
            pass
for h, c in hosts.most_common(15):
    p("   %-42s %d" % (h, c))

dump("04_dedup.txt", L)
print("done", N)
