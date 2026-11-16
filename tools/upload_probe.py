"""探测哪些匿名文件床当前可用（catbox 412 之后的备选）。"""
from __future__ import annotations

import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "index_lite.json")
NAME = os.path.basename(FILE)
SIZE = os.path.getsize(FILE)

BROWSER = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "*/*",
}


def _post(url, **kw):
    with open(FILE, "rb") as f:
        return requests.post(url, timeout=180, **kw, files=kw.pop("files", None) or
                             {"fileToUpload": (NAME, f, "application/json")})


def catbox(ua, userhash=""):
    with open(FILE, "rb") as f:
        r = requests.post("https://catbox.moe/user/api.php",
                          data={"reqtype": "fileupload", "userhash": userhash},
                          files={"fileToUpload": (NAME, f, "application/json")},
                          headers=ua, timeout=180)
    return r.status_code, (r.text or "").strip()[:120]


def litterbox():
    with open(FILE, "rb") as f:
        r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                          data={"reqtype": "fileupload", "time": "72h"},
                          files={"fileToUpload": (NAME, f, "application/json")},
                          headers=BROWSER, timeout=180)
    return r.status_code, (r.text or "").strip()[:120]


def zero0(host="0x0.st"):
    with open(FILE, "rb") as f:
        r = requests.post(f"https://{host}", files={"file": (NAME, f)},
                          headers=BROWSER, timeout=180)
    return r.status_code, (r.text or "").strip()[:120]


def tmpfiles():
    with open(FILE, "rb") as f:
        r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": (NAME, f)},
                          headers=BROWSER, timeout=180)
    return r.status_code, (r.text or "").strip()[:200]


def bashupload():
    with open(FILE, "rb") as f:
        r = requests.post("https://bashupload.com/", files={"file": (NAME, f)},
                          headers=BROWSER, timeout=180)
    return r.status_code, (r.text or "").strip()[:200]


def oshi():
    with open(FILE, "rb") as f:
        r = requests.post("https://oshi.at", files={"f": (NAME, f)},
                          headers=BROWSER, timeout=180)
    return r.status_code, (r.text or "").strip()[:200]


def filebin():
    r = requests.post(f"https://filebin.net/tvboxagg{os.getpid()}/{NAME}",
                      data=open(FILE, "rb"), headers={**BROWSER, "Content-Type": "application/json"},
                      timeout=180)
    return r.status_code, (r.text or "").strip()[:120]


def gofile():
    s = requests.Session()
    s.headers.update(BROWSER)
    srv = s.get("https://api.gofile.io/servers", timeout=60).json()
    server = srv["data"]["servers"][0]["name"]
    with open(FILE, "rb") as f:
        r = s.post(f"https://{server}.gofile.io/contents/uploadfile",
                   files={"file": (NAME, f, "application/json")}, timeout=300)
    return r.status_code, (r.text or "").strip()[:200]


TESTS = [
    ("catbox-browser-ua", lambda: catbox(BROWSER)),
    ("catbox-no-ua", lambda: catbox({})),
    ("catbox-curl-ua", lambda: catbox({"User-Agent": "curl/8.4.0"})),
    ("litterbox-72h", litterbox),
    ("0x0.st", zero0),
    ("envs.sh", lambda: zero0("envs.sh")),
    ("tmpfiles.org", tmpfiles),
    ("bashupload", bashupload),
    ("oshi.at", oshi),
    ("gofile", gofile),
]

print(f"file={FILE} size={SIZE/1024:.1f}KB")
for name, fn in TESTS:
    try:
        code, txt = fn()
        ok = "OK " if code == 200 and txt.startswith("http") else ".."
        print(f"{ok} {name:20s} {code} {txt}")
    except Exception as e:  # noqa: BLE001
        print(f"!! {name:20s} {type(e).__name__}: {e}")
