"""选择性拉取 GitHub 仓库里的配置文件（不整仓克隆）。

原理：partial clone（--filter=blob:limit=500k --no-checkout）+ ls-tree 列文件
+ 只 checkout 需要的 .json/.txt/.m3u 路径，避免几个 GB 的仓库拖垮磁盘与时间。

用法：
    py tools/gh_pull.py --list            # 列出 gh_repos.json 里将要拉取的仓库
    py tools/gh_pull.py                   # 拉取全部候选
    py tools/gh_pull.py --only qist/tvbox,liu673cn/bug
    py tools/gh_pull.py --max-files 300 --max-repos 40
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state")
DEST_ROOT = os.path.join(ROOT, "sources")

# 只要这些扩展名（配置文件 / 直播源 / 文本清单）
WANT_EXT = (".json", ".txt", ".m3u", ".m3u8", ".yaml", ".yml")
# 明确不要的目录（图片、apk、前端资源、字体）
SKIP_DIR = re.compile(r"(^|/)(node_modules|\.github|\.git|images?|img|icons?|fonts?|"
                      r"apk|release|screenshot|assets?/img|web/static|public/static)/", re.I)
# 明确不要的仓库（播放器客户端 / APK 收集 / 与配置无关）
DENY_REPO = re.compile(r"(TVAPP|iptv-api|FreeBox|AVBox|HTV|tvbox-desktop|AinanPlayer|"
                       r"tvbox-silicon|TVBox-tvs|Win-box|TVBox_live|EcoHub|alist-tvbox|"
                       r"IPTV|hl128k|tvbox-ysc|TvBox$|xiongjian83|kukuqi666)", re.I)
# 优先仓库（配置密度高，先拉）
PRIORITY = [
    "liu673cn/bug", "gaotianliuyun/gao", "2hacc/TVBox", "qist/tvbox", "25175/tvyuan",
    "noimank/tvbox", "cliya/TVBox", "cyao2q/files", "xianyuyimu/TVBOX-",
    "Zhou-Li-Bin/Tvbox-QingNing", "scovis/TVBox", "jinenge/tvbox", "qirenzhidao/tvbox18",
    "cluntop/tvbox", "yangxiaoge/tvbox_cust", "lubin776/tvbox-api-backup",
    "Lightconer/tvbox-ysc-config", "wuxierj/TVBox", "kimwang1978/tvbox",
    "CandyMuj/ResourceInterface", "ne7359/tvurl", "anaer/Meow", "adminouyang/231006",
    "loopool/fan", "niubihu1/tvbox", "yoursmile66/TVBox", "fish2018/tvbox",
    "Dong-learn9/TVBox-zyjk", "hd9211/Tvbox1", "yw88075/tvbox", "mlabalabala/box",
    "llazyl/TVBox", "franksun1211/TVBOX", "jadehh/TVSpider", "FongMi/CatVodSpider",
    "bizhangjie/CatVodSpider", "a736240087/tvbox", "j4Uq/TVBoxOSC",
]


def run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return 1, f"err: {e}"
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out.strip()


def pick_files(paths: list[str], max_files: int) -> list[str]:
    keep = []
    for p in paths:
        low = p.lower()
        if not low.endswith(WANT_EXT):
            continue
        if SKIP_DIR.search(p):
            continue
        keep.append(p)
    # 配置 json 优先，其次 txt/m3u；同层浅路径优先
    def score(p: str) -> tuple:
        low = p.lower()
        pri = 0 if low.endswith(".json") else (1 if low.endswith((".txt", ".m3u", ".m3u8")) else 2)
        return (pri, p.count("/"), len(p), p)

    keep.sort(key=score)
    return keep[:max_files]


def pull_one(repo: str, max_files: int, verbose: bool = True) -> str:
    name = repo.replace("/", "__")
    dest = os.path.join(DEST_ROOT, name)
    if os.path.isdir(os.path.join(dest, ".git")):
        rc, out = run(["git", "-C", dest, "fetch", "--depth", "1", "-q", "origin"], timeout=240)
        if rc != 0:
            return f"fetch-fail {name}: {out[:80]}"
        rc, out = run(["git", "-C", dest, "reset", "--soft", "FETCH_HEAD"], timeout=120)
        if rc != 0:
            return f"reset-fail {name}: {out[:80]}"
    else:
        os.makedirs(DEST_ROOT, exist_ok=True)
        rc, out = run(["git", "clone", "--depth", "1", "--filter=blob:limit=500k",
                       "--no-checkout", "-q", f"https://github.com/{repo}.git", dest], timeout=420)
        if rc != 0:
            # 部分服务器不支持 filter，退回普通浅克隆
            rc2, out2 = run(["git", "clone", "--depth", "1", "-q",
                             f"https://github.com/{repo}.git", dest], timeout=420)
            if rc2 != 0:
                return f"clone-fail {name}: {out[:70]} | {out2[:70]}"
    rc, out = run(["git", "-C", dest, "ls-tree", "-r", "--name-only", "HEAD"], timeout=120)
    if rc != 0:
        return f"lstree-fail {name}: {out[:80]}"
    paths = [x for x in out.splitlines() if x.strip()]
    want = pick_files(paths, max_files)
    if not want:
        return f"empty {name} (0/{len(paths)} files matched)"
    rc, out = run(["git", "-C", dest, "checkout", "-q", "HEAD", "--"] + want, timeout=420)
    if rc != 0:
        # 分批重试，单个文件失败不影响其它
        got = 0
        for i in range(0, len(want), 50):
            rc2, _ = run(["git", "-C", dest, "checkout", "-q", "HEAD", "--"] + want[i:i + 50],
                         timeout=240)
            if rc2 == 0:
                got += len(want[i:i + 50])
        if got == 0:
            return f"checkout-fail {name}: {out[:80]}"
        return f"partial {name}: {got}/{len(want)} of {len(paths)}"
    return f"ok {name}: {len(want)}/{len(paths)} files"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--max-files", type=int, default=260)
    ap.add_argument("--max-repos", type=int, default=60)
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    src = os.path.join(STATE, "gh_repos.json")
    repos: list[dict] = []
    if os.path.exists(src):
        with open(src, encoding="utf-8") as f:
            repos = json.load(f)
    by_name = {r["repo"]: r for r in repos}

    todo: list[str] = []
    for r in PRIORITY:
        if r in by_name or True:
            todo.append(r)
    # 再把搜索到的、没在优先级表里但相关的补上
    for r in repos:
        fn = r["repo"]
        if fn in todo or DENY_REPO.search(fn):
            continue
        if r.get("size_kb", 0) > 400_000:
            continue
        todo.append(fn)
    todo = todo[:a.max_repos]

    if a.only:
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        todo = [x for x in todo if x in want] or sorted(want)
    if a.list:
        print(f"{len(todo)} 个仓库：")
        for t in todo:
            r = by_name.get(t, {})
            print(f"  {r.get('stars', 0):>6}★ {r.get('size_kb', 0):>8}KB  {t:<45} {r.get('desc','')[:44]}")
        return 0

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(pull_one, t, a.max_files): t for t in todo}
        for fut in futs:
            msg = fut.result()
            print("  " + msg, flush=True)
            if msg.startswith(("ok", "partial")):
                ok += 1
            else:
                fail += 1
    print(f"\n完成：{ok} 成功 / {fail} 失败，目录 {DEST_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
