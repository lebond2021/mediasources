"""把 dist/index.json 发布成一条公网链接（TVBox 可直接填）。

支持：
    py tools/publish.py --to catbox        # catbox.moe，匿名、长期
    py tools/publish.py --to litterbox     # catbox 的临时盘（72h）
    py tools/publish.py --to 0x0           # 0x0.st
    py tools/publish.py --to gist          # 需要 GITHUB_TOKEN

--to all 会依次尝试，返回第一个成功的链接。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tvh-publish"}


def upload_catbox(path: str, host: str = "catbox.moe") -> str:
    url = f"https://{host}/user/api.php"
    with open(path, "rb") as f:
        r = requests.post(url, data={"reqtype": "fileupload", "userhash": ""},
                          files={"fileToUpload": (os.path.basename(path), f, "application/json")},
                          headers=UA, timeout=120)
    txt = (r.text or "").strip()
    if r.status_code == 200 and txt.startswith("http"):
        return txt
    raise RuntimeError(f"catbox: http-{r.status_code} {txt[:160]}")


def upload_0x0(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://0x0.st", files={"file": (os.path.basename(path), f)},
                          headers=UA, timeout=120)
    txt = (r.text or "").strip()
    if r.status_code == 200 and txt.startswith("http"):
        return txt
    raise RuntimeError(f"0x0: http-{r.status_code} {txt[:160]}")


def upload_gist(path: str) -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("gist: 缺少 GITHUB_TOKEN")
    body = open(path, encoding="utf-8").read()
    r = requests.post("https://api.github.com/gists",
                      headers={**UA, "Authorization": f"Bearer {token}",
                               "Accept": "application/vnd.github+json"},
                      json={"description": "TVBox 聚合源", "public": True,
                            "files": {"index.json": {"content": body}}}, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"gist: http-{r.status_code} {r.text[:160]}")
    js = r.json()
    return js["files"]["index.json"]["raw_url"]


ADAPTERS = {
    "catbox": lambda p: upload_catbox(p, "catbox.moe"),
    "litterbox": lambda p: upload_catbox(p, "litterbox.catbox.moe"),
    "0x0": upload_0x0,
    "gist": upload_gist,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="catbox", choices=list(ADAPTERS) + ["all"])
    ap.add_argument("--file", default=os.path.join(DIST, "index.json"))
    a = ap.parse_args()
    if not os.path.exists(a.file):
        print(f"文件不存在: {a.file}")
        return 1
    size = os.path.getsize(a.file)
    print(f"上传 {a.file} ({size / 1024:.1f} KB)")
    targets = list(ADAPTERS) if a.to == "all" else [a.to]
    for t in targets:
        try:
            url = ADAPTERS[t](a.file)
            print(f"\n[{t}] 成功 → {url}")
            with open(os.path.join(DIST, "published.json"), "w", encoding="utf-8") as f:
                json.dump({"adapter": t, "url": url, "file": a.file, "size": size},
                          f, ensure_ascii=False, indent=1)
            return 0
        except Exception as e:
            print(f"[{t}] 失败: {e}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
