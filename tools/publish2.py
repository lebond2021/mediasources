"""把 dist/index.json 发布到可用文件床，并立刻回读校验。"""
from __future__ import annotations

import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}


def upload_pomf(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://pomf.lain.la/upload.php",
                          files={"files[]": (os.path.basename(path), f, "application/json")},
                          headers=UA, timeout=600)
    js = r.json()
    if not js.get("success"):
        raise RuntimeError(f"pomf: {js}")
    return js["files"][0]["url"].replace("\\/", "/")


def upload_kappa(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://kappa.lol/api/upload",
                          files={"file": (os.path.basename(path), f, "application/json")},
                          headers=UA, timeout=600)
    js = r.json()
    if "link" not in js:
        raise RuntimeError(f"kappa: {str(js)[:200]}")
    return js["link"]


def upload_uguu(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://uguu.se/upload?output=text",
                          files={"files[]": (os.path.basename(path), f, "application/json")},
                          headers=UA, timeout=600)
    txt = (r.text or "").strip()
    if not txt.startswith("http"):
        raise RuntimeError(f"uguu: {txt[:160]}")
    return txt


def verify(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=120)
    try:
        js = r.json()
    except Exception:
        return f"http-{r.status_code} 非 JSON ({len(r.content)}B) head={r.text[:80]!r}"
    return (f"http-{r.status_code} sites={len(js.get('sites') or [])} "
            f"parses={len(js.get('parses') or [])} lives={len(js.get('lives') or [])} "
            f"spider={'Y' if js.get('spider') else 'N'} {len(r.content)/1024:.0f}KB")


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DIST, "index.json")
    print(f"发布 {target} ({os.path.getsize(target)/1024:.0f}KB)")
    out = {}
    for name, fn in (("pomf", upload_pomf), ("kappa", upload_kappa), ("uguu", upload_uguu)):
        try:
            url = fn(target)
            print(f"[{name}] {url}")
            print(f"       校验: {verify(url)}")
            out[name] = url
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] 失败: {type(e).__name__}: {str(e)[:160]}")
    if out:
        p = os.path.join(DIST, "published.json")
        json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"→ {p}")
    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())
