#!/usr/bin/env python
"""对比两次构建结果，输出「本次新增 / 本次消失」清单。

用途：配合每日自动更新，证明「去掉了失效源、加进了新源」。
  py tools/diff_report.py --prev data/state/prev_index.json --cur dist/index.json --out docs/changes.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tvh.model import site_backend_id  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_sites(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    out: dict[str, dict] = {}
    for s in doc.get("sites") or []:
        if not isinstance(s, dict):
            continue
        k = site_backend_id(s) or f"{s.get('type')}|{s.get('api')}"
        out.setdefault(k, s)
    return out


def label(s: dict) -> str:
    name = str(s.get("name") or "?").strip()
    api = str(s.get("api") or "").strip()
    if len(api) > 48:
        api = api[:45] + "..."
    return f"{name} `{s.get('type')}` {api}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", default=os.path.join(ROOT, "data", "state", "prev_index.json"))
    ap.add_argument("--cur", default=os.path.join(ROOT, "dist", "index.json"))
    ap.add_argument("--out", default="")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()

    prev = load_sites(a.prev)
    cur = load_sites(a.cur)
    if not prev:
        print("没有上一轮快照，跳过对比")
        return 0

    added = [cur[k] for k in cur.keys() - prev.keys()]
    removed = [prev[k] for k in prev.keys() - cur.keys()]
    kept = len(cur.keys() & prev.keys())

    added.sort(key=lambda s: (str(s.get("name") or "")))
    removed.sort(key=lambda s: (str(s.get("name") or "")))

    print(f"上一轮 {len(prev)} 站 → 本轮 {len(cur)} 站；新增 {len(added)}，消失 {len(removed)}，保留 {kept}")

    if a.out:
        lines = [
            "# 本轮变化",
            "",
            f"- 上一轮：{len(prev)} 站",
            f"- 本轮：{len(cur)} 站",
            f"- **新增：{len(added)}**",
            f"- **移除（探测失效 / 类名无实现 / 引用数不足）：{len(removed)}**",
            f"- 保留：{kept}",
            "",
            f"## 新增站点（前 {a.top}）",
            "",
        ]
        lines += [f"- {label(s)}" for s in added[: a.top]] or ["- （无）"]
        lines += ["", f"## 移除站点（前 {a.top}）", ""]
        lines += [f"- {label(s)}" for s in removed[: a.top]] or ["- （无）"]
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"写入 {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
