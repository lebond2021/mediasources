"""用 GitHub 搜索 API 发现 TVBox 媒体源仓库，并浅克隆到 sources/。

用法：
    py tools/gh_discover.py search            # 只搜索，输出 data/state/gh_repos.json
    py tools/gh_discover.py clone --top 40    # 搜索 + 浅克隆前 N 个
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state")
SOURCES = os.path.join(ROOT, "sources")

QUERIES = [
    "tvbox in:name",
    "tvbox in:description",
    "topic:tvbox",
    "topic:tvbox-config",
    "topic:tvbox-interface",
    "影视仓 in:name,description",
    "tvbox 接口 in:description",
    "tvbox 配置 in:description",
    "tvbox 直播源 in:description",
    "catvod in:name,description",
    "tvbox source in:name",
    "tvbox json in:name",
]

RELEVANT = re.compile(r"(tvbox|tbox|影视仓|影視倉|catvod|tvboxos|vod|直播源|电视|spider|接口|"
                      r"yingshi|tv-config|tvbox)", re.I)

HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "tvh-gh-discover"}
TOKEN = os.environ.get("GITHUB_TOKEN", "")
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

SKIP_OWNER = {"tvbox", "o2bomb"}


def search() -> list[dict]:
    repos: dict[str, dict] = {}
    for q in QUERIES:
        for page in (1, 2):
            url = "https://api.github.com/search/repositories"
            params = {"q": q, "sort": "stars", "order": "desc", "per_page": 50, "page": page}
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            except Exception as e:
                print(f"  ! {q} p{page}: {e}")
                continue
            if r.status_code == 403:
                print("  ! rate limited, 等 30s")
                time.sleep(30)
                continue
            if r.status_code != 200:
                print(f"  ! {q} p{page}: http-{r.status_code}")
                continue
            items = (r.json() or {}).get("items") or []
            print(f"  {q} p{page}: {len(items)} 个仓库")
            for it in items:
                fn = it.get("full_name", "")
                if not fn or fn.split("/")[0] in SKIP_OWNER:
                    continue
                desc = (it.get("description") or "")
                if not RELEVANT.search(fn) and not RELEVANT.search(desc):
                    continue
                cur = repos.get(fn)
                stars = it.get("stargazers_count", 0)
                if cur is None or stars > cur["stars"]:
                    repos[fn] = {"repo": fn, "stars": stars,
                                 "size_kb": it.get("size", 0),
                                 "desc": (it.get("description") or "")[:120],
                                 "pushed": it.get("pushed_at", ""),
                                 "default_branch": it.get("default_branch", "main")}
            time.sleep(2)
    out = sorted(repos.values(), key=lambda x: -x["stars"])
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "gh_repos.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n共发现 {len(out)} 个仓库 → data/state/gh_repos.json")
    for r in out[:60]:
        print(f"  {r['stars']:>6}  {r['size_kb']:>7}KB  {r['repo']:<45} {r['desc'][:50]}")
    return out


def clone(repos: list[dict], top: int) -> None:
    os.makedirs(SOURCES, exist_ok=True)
    todo = [r for r in repos if r["size_kb"] < 60_000][:top]

    def one(r: dict) -> str:
        name = r["repo"].replace("/", "__")
        dest = os.path.join(SOURCES, name)
        if os.path.isdir(os.path.join(dest, ".git")):
            try:
                subprocess.run(["git", "-C", dest, "pull", "--ff-only", "-q"],
                               capture_output=True, timeout=180)
                return f"pull {name}"
            except Exception:
                return f"pull-fail {name}"
        url = f"https://github.com/{r['repo']}.git"
        try:
            p = subprocess.run(["git", "clone", "--depth", "1", "-q", url, dest],
                               capture_output=True, timeout=300)
            if p.returncode != 0:
                return f"clone-fail {name}: {p.stderr.decode('utf-8', 'replace')[:90]}"
            return f"clone {name}"
        except Exception as e:
            return f"clone-err {name}: {e}"

    with ThreadPoolExecutor(max_workers=6) as ex:
        for msg in ex.map(one, todo):
            print("  " + msg)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "search"
    repos = search()
    if mode == "clone":
        top = 40
        if "--top" in sys.argv:
            top = int(sys.argv[sys.argv.index("--top") + 1])
        clone(repos, top)
        print(f"\nsources/ 现有仓库: {len(os.listdir(SOURCES))} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
