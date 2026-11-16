"""从已克隆的采集仓库里导出种子 URL。"""
from __future__ import annotations

import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")
OUT = os.path.join(ROOT, "seeds", "seed_from_collectors.txt")
URL_RE = re.compile(r"https?://[^\s\t\"'<>]+")


def parse_tvyuan_sources(p: str):
    """tvyuan/sources.txt 格式：空行分隔，[12ms] 名称 / URL"""
    out = []
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return out
    blocks = re.split(r"\n\s*\n", txt)
    for b in blocks:
        urls = URL_RE.findall(b)
        if not urls:
            continue
        name = ""
        for line in b.splitlines():
            line = line.strip()
            if line and not line.startswith("http") and not line.startswith("#"):
                name = re.sub(r"^\[\d+ms\]\s*", "", line)
                break
        for u in urls:
            out.append((u.rstrip(".,;"), name))
    return out


def main():
    rows = []
    p = os.path.join(SRC, "tvyuan", "sources.txt")
    rows += parse_tvyuan_sources(p)

    # cliya / qist 的 README 里也有链接
    for repo in ("cliya", "qist", "tvbox"):
        for fn in os.listdir(os.path.join(SRC, repo)) if os.path.isdir(os.path.join(SRC, repo)) else []:
            if fn.lower() in ("readme.md", "readme.en-us.md"):
                try:
                    txt = open(os.path.join(SRC, repo, fn), encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                for u in URL_RE.findall(txt):
                    rows.append((u.rstrip(".,;）)】\""), f"{repo}/readme"))

    seen, lines = set(), []
    lines.append("# 从采集仓库自动导出的种子（tools/make_seeds.py 生成）\n")
    for u, name in rows:
        if not u or u in seen:
            continue
        if any(u.lower().endswith(x) for x in (".png", ".jpg", ".gif", ".svg", ".ico", ".apk", ".zip", ".exe")):
            continue
        seen.add(u)
        lines.append(f"{u}\t{name}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"导出 {len(seen)} 条 -> {OUT}")


if __name__ == "__main__":
    main()
