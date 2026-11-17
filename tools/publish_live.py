"""发布直播配置，并刷新 dist/published.json 清单。

真机（BlueStacks + TVBox q215613905）实测结论：
- 点播配置：raw.githubusercontent.com（text/plain）能正常加载；
- 直播配置：同一个 raw 链接会被直播加载器静默忽略，换成返回
  `Content-Type: application/json` 的主机（jsDelivr / pomf / kappa）才生效。
所以直播链接优先给 jsDelivr，raw 只作为兜底。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
REPO = "lebond2021/mediasources"
BRANCH = "dist"


UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tvbox-aggregator/1.0"}


def upload_pomf(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://pomf2.lain.la/upload.php", headers=UA,
                          files={"files[]": (os.path.basename(path), f, "application/json")},
                          timeout=300)
    r.raise_for_status()
    return r.json()["files"][0]["url"]


def upload_kappa(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post("https://kappa.lol/api/upload", headers=UA,
                          files={"file": (os.path.basename(path), f, "application/json")},
                          timeout=300)
    r.raise_for_status()
    js = r.json()
    return js.get("link") or js.get("url") or js.get("direct_url") or ""


def probe(url: str, expect_lives: bool) -> tuple[bool, str]:
    try:
        r = requests.get(url, timeout=120)
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败 {e}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    ctype = r.headers.get("content-type", "")
    try:
        d = r.json()
    except Exception:  # noqa: BLE001
        return False, "不是合法 JSON"
    n = len(d.get("lives") or [])
    if expect_lives and not n:
        return False, "lives 为空"
    return True, f"{r.status_code} {ctype} {len(r.content)//1024}KB lives={n}"


def main() -> int:
    live = os.path.join(DIST, "index_lives.json")
    if not os.path.exists(live):
        print("缺少 dist/index_lives.json，先跑 build")
        return 1
    doc = json.load(open(live, encoding="utf-8"))
    n_lives = len(doc.get("lives") or [])

    jsd = f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/index_lives.json"
    raw = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/index_lives.json"

    mirrors = {}
    for name, fn in (("pomf2.lain.la", upload_pomf), ("kappa.lol", upload_kappa)):
        try:
            u = fn(live)
            ok, info = probe(u, True)
            print(f"  {name:16s} {u}  {'✓' if ok else '✗'} {info}")
            if ok:
                mirrors[name] = u
        except Exception as e:  # noqa: BLE001
            print(f"  {name:16s} 上传失败 {e}")

    ok_jsd, info_jsd = probe(jsd, True)
    print(f"  jsdelivr         {jsd}  {'✓' if ok_jsd else '✗'} {info_jsd}")

    idx = os.path.join(DIST, "index.json")
    n_sites = len(json.load(open(idx, encoding="utf-8")).get("sites") or []) if os.path.exists(idx) else 0
    out = {
        "published_at": date.today().isoformat(),
        "vod": {
            "primary": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/index.json",
            "mirror": f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/index.json",
            "sites": n_sites,
        },
        "live": {
            "primary": jsd if ok_jsd else (mirrors.get("pomf2.lain.la") or raw),
            "mirrors": {**mirrors, "raw(仅供点播加载器)": raw},
            "lives": n_lives,
            "note": "直播加载器要求 Content-Type: application/json；raw.githubusercontent 返回 text/plain 会被静默忽略。",
        },
        "variants": {
            "index_lite.json（300 站精简）": f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/index_lite.json",
            "storehouse.json（多仓）": f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/storehouse.json",
            "index_all.json（全量）": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/index_all.json",
            "index_lives_grouped.json（频道组）": f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/index_lives_grouped.json",
        },
    }
    path = os.path.join(DIST, "published.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {path}")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
