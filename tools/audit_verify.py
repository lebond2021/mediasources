# -*- coding: utf-8 -*-
"""复核 repo-audit.md 里几张高风险表格：按文件去重、base64 分布、qist JSON 分类、直播文件行数。"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_common import ROOT, OUT, REPOS, walk_files, load_json_file, classify, dump, table
from collections import Counter


def norm_api(a):
    if not isinstance(a, str):
        return ""
    s = a.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("?")[0].rstrip("/")
    return s


def norm_type(t):
    if isinstance(t, str) and t.strip().lstrip("-").isdigit():
        return int(t)
    return t


# ---- 1) 每个配置文件的 sites 数与 (type,api) 去重 ----
per_file = []
files = []
for repo in REPOS:
    for r in walk_files(repo):
        files.append(r)

for repo, rel, p, size in files:
    if not p.lower().endswith(".json"):
        continue
    r = load_json_file(p)
    if not r.get("ok") or not isinstance(r.get("obj"), dict):
        continue
    o = r["obj"]
    if not isinstance(o.get("sites"), list):
        continue
    sites = [s for s in o["sites"] if isinstance(s, dict)]
    keys = {str(s.get("key", "")).strip().lower() for s in sites if s.get("key") is not None}
    names = {re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(s.get("name", "")).lower()) for s in sites}
    ta = {(norm_type(s.get("type")), norm_api(s.get("api", ""))) for s in sites}
    per_file.append((repo + "/" + rel, len(sites), len(ta), len(keys), len(names)))
per_file.sort(key=lambda x: -x[1])

lines = ["# 每配置 sites 统计（复核）", ""]
lines += table([("file", "sites", "(type,api)", "key", "name")] + [(a, b, c, d, e) for a, b, c, d, e in per_file])

# ---- 2) base64 分布（>=40 连续 base64 字符） ----
B64 = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
b64 = []
for repo, rel, p, size in files:
    low = p.lower()
    if not (low.endswith(".json") or low.endswith(".txt")):
        continue
    raw = open(p, "rb").read()
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        continue
    if txt.lstrip()[:1] not in ("{", "["):
        continue
    n = len(B64.findall(txt))
    if n:
        b64.append((repo + "/" + rel, n))
b64.sort(key=lambda x: -x[1])
lines += ["", "# 含 >=40 字符 base64 片段（复核）N=%d" % len(b64), ""]
lines += table([("file", "hits")] + [(a, b) for a, b in b64])

# ---- 3) qist 257 个 .json 分类 ----
cls = Counter()
nq = 0
for repo, rel, p, size in files:
    if repo != "qist" or not p.lower().endswith(".json"):
        continue
    nq += 1
    r = load_json_file(p)
    cls[classify(r.get("obj")) if r.get("ok") else "UNPARSEABLE"] += 1
lines += ["", "# qist .json 分类（复核，N=%d）" % nq, ""]
for k, v in cls.most_common():
    lines.append("%-20s %d" % (k, v))

# ---- 4) 直播文件行数 ----
LIVE = ["cliya/18live.txt", "cliya/live.txt", "cliya/live.m3u", "qist/list.txt", "qist/list.m3u",
        "qist/listx.txt", "qist/listx.m3u", "qist/livex.m3u", "qist/radio.txt", "qist/radio.m3u",
        "qist/ITV.txt", "qist/zb.txt", "qist/tvboxtv.txt", "qist/tvlive.txt", "qist/FTY/id.txt",
        "qist/FTY/id.m3u", "qist/live/山东联通.txt", "qist/live/广东联通内网.txt",
        "qist/live/河南联通单播.txt", "qist/live/辽宁移动华为.txt", "qist/live/辽宁移动烽火.txt",
        "qist/live/辽宁联通.txt", "qist/js/lf_live.txt"]
lines += ["", "# 直播文件行数（复核）", ""]
for rel in LIVE:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        lines.append("%-40s MISSING" % rel)
        continue
    raw = open(p, "rb").read()
    if raw[:2] == b"\xff\xfe":
        txt = raw.decode("utf-16-le"); enc = "utf-16le"
    elif raw[:3] == b"\xef\xbb\xbf":
        txt = raw.decode("utf-8-sig"); enc = "utf-8-sig"
    else:
        txt = raw.decode("utf-8", "replace"); enc = "utf-8"
    lines.append("%-40s %6d lines  %8d B  %s" % (rel, txt.count("\n") + 1, len(raw), enc))

dump("14_verify.txt", lines)
print("ok", len(lines))
