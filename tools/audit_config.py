# -*- coding: utf-8 -*-
"""Q2 schema + Q3 sites morphology, across all parseable tvbox configs."""
import os, sys, json, re, collections, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, load_json_file, classify, dump, table

L = []
def p(s=""):
    L.append(s)

MULTI = ("urls", "storeHouse")
configs = []   # (repo, rel, obj)
for repo in REPOS:
    for r2, rel, path, size in walk_files(repo):
        low = rel.lower()
        if not (low.endswith(".json") or low.endswith(".txt")):
            continue
        if low.endswith(".txt") and open(path, "rb").read(1) not in b"{[":
            continue
        r = load_json_file(path)
        if not r["ok"]:
            continue
        cls = classify(r["obj"])
        if cls == "tvbox-config":
            configs.append((repo, rel, r["obj"], r["mode"]))

p("# config JSON inventory (class tvbox-config)")
rows = [("repo", "path", "top-level keys", "mode")]
for repo, rel, obj, mode in configs:
    rows.append((repo, rel, ",".join(sorted(obj.keys())), mode))
p("\n".join(table(rows)))
p("")
p("TOTAL config json = %d" % len(configs))

# ---------- Q2 key frequency
keyfreq = collections.Counter()
keyfreq_sites = collections.Counter()   # only configs that have sites
for repo, rel, obj, mode in configs:
    for k in obj.keys():
        keyfreq[k] += 1
p("")
p("# Q2 top-level key frequency (N=%d config files)" % len(configs))
rows = [("key", "count", "pct", "value type(s)")]
types = collections.defaultdict(collections.Counter)
for repo, rel, obj, mode in configs:
    for k, v in obj.items():
        types[k][type(v).__name__] += 1
for k, c in keyfreq.most_common():
    rows.append((k, c, "%.0f%%" % (100.0 * c / len(configs)),
                 ",".join("%s:%d" % (t, n) for t, n in types[k].most_common())))
p("\n".join(table(rows)))

# per-repo presence of the doc-named keys
DOC_KEYS = ["sites", "parses", "lives", "spider", "flags", "rules", "ijk", "ads", "doh",
            "hosts", "proxy", "wallpaper", "logo", "notice", "headers", "timeout",
            "style", "ext", "homepage"]
p("")
p("# Q2b presence matrix for doc-listed keys")
rows = [["key"] + REPOS + ["files_with"]]
for k in DOC_KEYS:
    row = [k]
    tot = 0
    for repo in REPOS:
        c = sum(1 for rp, rel, obj, m in configs if rp == repo and k in obj)
        row.append(str(c))
        tot += c
    row.append(str(tot))
    rows.append(row)
p("\n".join(table(rows)))

# ---------- Q3 sites morphology
sites_all = []
for repo, rel, obj, mode in configs:
    ss = obj.get("sites")
    if isinstance(ss, list):
        for s in ss:
            if isinstance(s, dict):
                d = dict(s)
                d["__repo"] = repo
                d["__file"] = rel
                sites_all.append(d)
p("")
p("# Q3 sites total across config files: %d (from %d configs)" % (
    len(sites_all), sum(1 for r, rel, o, m in configs if isinstance(o.get("sites"), list))))

fieldfreq = collections.Counter()
for s in sites_all:
    for k in s.keys():
        if not k.startswith("__"):
            fieldfreq[k] += 1
p("")
p("# Q3a site field frequency (N=%d)" % len(sites_all))
rows = [("field", "count", "pct")]
for k, c in fieldfreq.most_common():
    rows.append((k, c, "%.0f%%" % (100.0 * c / len(sites_all))))
p("\n".join(table(rows)))


def api_kind(v):
    """Coarse bucket for api value."""
    if v is None:
        return "null"
    if not isinstance(v, str):
        return "nonstr:" + type(v).__name__
    s = v.strip()
    if s == "":
        return "empty"
    if s.startswith("csp_"):
        return "csp_key"
    if s.lower().startswith(("js:", "py:", "lib:", "file:")):
        return "scheme_js_py_lib"
    if s.startswith(("http://", "https://")):
        low = s.lower()
        if "provide/vod" in low or "/api.php" in low:
            return "http_vod_api"
        if low.endswith(".json"):
            return "http_json"
        if low.endswith(".php"):
            return "http_php"
        if low.endswith((".m3u8", ".txt", ".m3u", ".mp4")):
            return "http_media"
        return "http_other"
    if s.startswith(("./", "../", "/")):
        ext = os.path.splitext(s.split("?")[0])[1].lower()
        return "local_path" + (ext if ext else "_noext")
    return "other"


def api_detail(v):
    """Finer bucket for the report: which bundled dir a local api points into."""
    k = api_kind(v)
    if k.startswith("local_path"):
        s = v.strip()
        m = re.match(r"\.?/?([A-Za-z0-9_]+)/", s)
        return "local:" + (m.group(1) if m else "root")
    return k


tcnt = collections.Counter()
for s in sites_all:
    t = s.get("type")
    tcnt[json.dumps(t, ensure_ascii=False) if not isinstance(t, int) else str(t)] += 1
p("")
p("# Q3b type distribution (raw value)")
rows = [("type", "count", "pct")]
for k, c in tcnt.most_common():
    rows.append((k, c, "%.1f%%" % (100.0 * c / len(sites_all))))
p("\n".join(table(rows)))

p("")
p("# Q3c api coarse kind distribution (N=%d)" % len(sites_all))
ak = collections.Counter(api_kind(s.get("api")) for s in sites_all)
rows = [("api_kind", "count", "pct")]
for k, c in ak.most_common():
    rows.append((k, c, "%.1f%%" % (100.0 * c / len(sites_all))))
p("\n".join(table(rows)))

p("")
p("# Q3c2 api fine bucket (local paths split by bundled dir)")
ad = collections.Counter(api_detail(s.get("api")) for s in sites_all)
rows = [("api_detail", "count", "pct")]
for k, c in ad.most_common(30):
    rows.append((k, c, "%.1f%%" % (100.0 * c / len(sites_all))))
p("\n".join(table(rows)))

p("")
p("# Q3c3 type x api_kind cross tab")
cross = collections.defaultdict(collections.Counter)
for s in sites_all:
    t = s.get("type")
    tk = "missing" if "type" not in s else (str(t) if isinstance(t, int) else json.dumps(t, ensure_ascii=False))
    cross[tk][api_kind(s.get("api"))] += 1
allk = sorted({k for c in cross.values() for k in c}, key=lambda x: -sum(cross[t][x] for t in cross))
rows = [["type"] + allk + ["n"]]
for t, c in sorted(cross.items(), key=lambda x: -sum(x[1].values())):
    rows.append([t] + [str(c.get(k, 0)) for k in allk] + [str(sum(c.values()))])
p("\n".join(table(rows)))

# api examples per type
p("")
p("# Q3d api samples per type (up to 6 each, diverse kinds)")
bytype = collections.defaultdict(list)
for s in sites_all:
    t = s.get("type")
    tk = "missing" if "type" not in s else (str(t) if isinstance(t, int) else json.dumps(t, ensure_ascii=False))
    bytype[tk].append(s)
for t, lst in sorted(bytype.items(), key=lambda x: -len(x[1])):
    p("-- type=%s n=%d" % (t, len(lst)))
    seen = set()
    shown = 0
    for s in lst:
        k = api_kind(s.get("api"))
        if k in seen:
            continue
        seen.add(k)
        p("   [%-12s] name=%-16s key=%-20s api=%s" % (k, str(s.get("name"))[:16], str(s.get("key"))[:20],
                                                      str(s.get("api"))[:100]))
        shown += 1
        if shown >= 6:
            break

p("")
p("# Q3d2 jar field + playerType values")
jar = collections.Counter(s.get("jar") for s in sites_all if "jar" in s)
for k, c in jar.most_common(12):
    p("   jar=%-46s %d" % (str(k)[:46], c))
pt = collections.Counter(json.dumps(s.get("playerType"), ensure_ascii=False) for s in sites_all if "playerType" in s)
p("   playerType: " + json.dumps(dict(pt.most_common(12)), ensure_ascii=False))
tt = collections.Counter(json.dumps(s.get("timeout"), ensure_ascii=False) for s in sites_all if "timeout" in s)
p("   timeout: " + json.dumps(dict(tt.most_common(12)), ensure_ascii=False))
stl = collections.Counter(json.dumps(s.get("style"), ensure_ascii=False) for s in sites_all if "style" in s)
p("   style: " + json.dumps(dict(stl.most_common(10)), ensure_ascii=False))


def ext_kind(v):
    if "ext" not in v:
        return "missing"
    e = v["ext"]
    if e is None:
        return "null"
    if isinstance(e, (dict, list)):
        return "json-obj"
    if isinstance(e, str):
        s = e.strip()
        if s == "":
            return "empty"
        if s.startswith(("{", "[")):
            try:
                json.loads(s)
                return "json-str(parsed)"
            except Exception:
                return "json-str(broken)"
        if s.startswith(("http://", "https://")):
            return "url"
        if re.fullmatch(r"[A-Za-z0-9+/=]{24,}", s):
            return "likely-base64"
        return "other-str"
    return type(e).__name__


ecnt = collections.Counter(ext_kind(s) for s in sites_all)
p("")
p("# Q3e ext forms")
rows = [("ext form", "count", "pct")]
for k, c in ecnt.most_common():
    rows.append((k, c, "%.1f%%" % (100.0 * c / len(sites_all))))
p("\n".join(table(rows)))

# key naming
keys = [s.get("key") for s in sites_all if isinstance(s.get("key"), str)]
kcnt = collections.Counter(keys)
pref = collections.Counter("csp_" if k.startswith("csp_") else ("empty" if not k else "other") for k in keys)
p("")
p("# Q3f key naming: total keys=%d, unique=%d" % (len(keys), len(kcnt)))
p("prefix: " + json.dumps(pref, ensure_ascii=False))
p("top duplicated keys (same file): ")
for k, c in kcnt.most_common(15):
    p("   %-28s %d" % (k, c))
p("")
p("# Q3g other common fields by type (searchable/quickSearch/filterable/playerType/jar/...)")
OTHER = ["searchable", "quickSearch", "filterable", "playerType", "jar", "timeout",
         "headers", "extend", "clickSelector", "changeable", "searchUrl", "categories",
         "style", "playerUrl", "ua", "referer", "hide", "logo", "ext"]
rows = [["type", "n"] + OTHER]
for t, lst in sorted(bytype.items(), key=lambda x: -len(x[1])):
    rows.append([t, str(len(lst))] + [str(sum(1 for s in lst if k in s)) for k in OTHER])
p("\n".join(table(rows)))

json.dump(sites_all, open(os.path.join(OUT, "sites_all.json"), "w", encoding="utf-8"),
          ensure_ascii=False)
dump("02_schema.txt", L)
print("configs", len(configs), "sites", len(sites_all), "fields", len(fieldfreq))
