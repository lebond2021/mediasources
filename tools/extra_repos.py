"""从 recon 报告第 3 节抽取仓库名，输出未拉取过的仓库清单。"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
md = os.path.join(ROOT, "docs", "recon-web.md")
lines = io.open(md, encoding="utf-8").read().splitlines()
i = next(n for n, l in enumerate(lines) if l.startswith("## 3."))
j = next(n for n, l in enumerate(lines) if l.startswith("## 4."))
repos = []
for l in lines[i:j]:
    m = re.match(r"\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|", l)
    if m and int(m.group(2)) >= 4:
        repos.append(m.group(1))
have = {d.replace("__", "/") for d in os.listdir(os.path.join(ROOT, "sources"))}
todo = [r for r in repos if r not in have]
print(f"{len(repos)} 个仓库在表中，{len(todo)} 个未拉取")
print(",".join(todo))
with io.open(os.path.join(ROOT, "data", "state", "extra_repos.txt"), "w", encoding="utf-8") as f:
    f.write(",".join(todo))
