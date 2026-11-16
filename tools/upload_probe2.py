"""第二轮：找长期可用 + 直链的文件床 / 粘贴站。"""
from __future__ import annotations

import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(ROOT, "dist", "index_lite.json")
NAME = os.path.basename(FILE)
BROWSER = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
}


def pomf(base, field="files[]"):
    with open(FILE, "rb") as f:
        r = requests.post(base, files={field: (NAME, f, "application/json")},
                          headers=BROWSER, timeout=300)
    return r.status_code, (r.text or "").strip()[:200]


def paste_rs():
    with open(FILE, "rb") as f:
        r = requests.post("https://paste.rs/", data=f, headers=BROWSER, timeout=300)
    return r.status_code, (r.text or "").strip()[:120]


def dpaste():
    body = open(FILE, encoding="utf-8").read()
    r = requests.post("https://dpaste.org/api/", data={"content": body, "format": "url",
                                                      "expiry_days": "365"},
                      headers=BROWSER, timeout=300)
    return r.status_code, (r.text or "").strip()[:120]


def filebin():
    bin_id = "tvboxagg"
    r = requests.post(f"https://filebin.net/{bin_id}/{NAME}",
                      data=open(FILE, "rb").read(),
                      headers={**BROWSER, "Content-Type": "application/octet-stream"}, timeout=300)
    return r.status_code, (r.text or "").strip()[:120]


def tmpfiles():
    with open(FILE, "rb") as f:
        r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": (NAME, f)},
                          headers=BROWSER, timeout=300)
    return r.status_code, (r.text or "").strip()[:200]


def kappa():
    with open(FILE, "rb") as f:
        r = requests.post("https://kappa.lol/api/upload", files={"file": (NAME, f)},
                          headers=BROWSER, timeout=300)
    return r.status_code, (r.text or "").strip()[:200]


TESTS = [
    ("pomf.lain.la", lambda: pomf("https://pomf.lain.la/upload.php")),
    ("qu.ax", lambda: pomf("https://qu.ax/upload.php")),
    ("uguu.se", lambda: pomf("https://uguu.se/upload?output=text", "files[]")),
    ("paste.rs", paste_rs),
    ("dpaste.org", dpaste),
    ("filebin.net", filebin),
    ("tmpfiles", tmpfiles),
    ("kappa.lol", kappa),
]
print(f"file={FILE} {os.path.getsize(FILE)/1024:.0f}KB")
for name, fn in TESTS:
    try:
        code, txt = fn()
        print(f"[{code}] {name:14s} {txt}")
    except Exception as e:  # noqa: BLE001
        print(f"[ERR] {name:14s} {type(e).__name__}: {str(e)[:120]}")
