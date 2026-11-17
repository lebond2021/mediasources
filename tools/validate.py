"""对 dist/ 产出的配置做结构与内容校验，输出问题清单。

用法：
    py tools/validate.py                 # 校验 dist/index.json
    py tools/validate.py dist/index_all.json
    py tools/validate.py --all           # 校验 dist/*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

VALID_TYPES = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)


WARN: list[str] = []


def check_config(path: str) -> list[str]:
    WARN.clear()
    errs: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:  # noqa: BLE001
        return [f"JSON 解析失败: {e}"]
    if not isinstance(cfg, dict):
        return ["顶层不是对象"]

    sites = cfg.get("sites")
    relax = bool(re.search(r"(live|channel|probe)", os.path.basename(path).lower()))
    if not isinstance(sites, list):
        if not relax:
            errs.append("缺少 sites 数组")
        sites = []
    if not sites and not re.search(r"(live|channel|probe)", os.path.basename(path).lower()):
        errs.append("sites 为空")

    keys = Counter()
    api_counter = Counter()
    for i, s in enumerate(sites):
        where = f"sites[{i}]"
        if not isinstance(s, dict):
            errs.append(f"{where} 不是对象")
            continue
        key = s.get("key")
        if not key:
            errs.append(f"{where} 缺 key")
        elif not isinstance(key, str):
            errs.append(f"{where} key 非字符串: {type(key).__name__}")
        else:
            keys[key] += 1
            if len(key) > 64:
                errs.append(f"{where} key 超长({len(key)})")
        name = s.get("name")
        if not name:
            errs.append(f"{where} 缺 name")
        t = s.get("type")
        if t is None:
            errs.append(f"{where} 缺 type")
        elif not isinstance(t, int) or t not in VALID_TYPES:
            errs.append(f"{where} type 非法: {t!r}")
        api = s.get("api")
        if not api:
            errs.append(f"{where} 缺 api")
        elif isinstance(api, str) and not re.match(r"^(?:csp|py)_[A-Za-z0-9_]+$", api):
            if not URL_RE.match(api) and not re.match(r"^(js|py|assets|file|clan|data)://", api):
                errs.append(f"{where} api 非 URL: {api[:60]}")
        if isinstance(api, str):
            # 同一 csp 类名挂不同 key/ext 是常态；这里只统计「api+ext 完全相同」的真重复
            ext_sig = json.dumps(s.get("ext"), ensure_ascii=False, sort_keys=True) if s.get("ext") is not None else ""
            api_counter[(api, ext_sig, str(s.get("jar") or ""))] += 1
        for flag in ("searchable", "quickSearch", "filterable"):
            v = s.get(flag)
            if v is not None and v not in (0, 1):
                errs.append(f"{where} {flag} 非 0/1: {v!r}")
        jar = s.get("jar")
        if jar is not None:
            if not isinstance(jar, str) or not jar:
                errs.append(f"{where} jar 非法: {jar!r}")
            elif not URL_RE.match(jar) and not re.match(r"^(js|assets|file|clan)://", jar):
                errs.append(f"{where} jar 非 URL: {jar[:60]}")
        ext = s.get("ext")
        if ext is not None and not isinstance(ext, (str, dict, list)):
            errs.append(f"{where} ext 类型异常: {type(ext).__name__}")

    for k, n in keys.items():
        if n > 1:
            errs.append(f"key 重复 {n} 次: {k}")
    for (a, _ext, _jar), n in api_counter.items():
        if n > 1:
            errs.append(f"完全重复的站 {n} 次: {a[:70]}")

    for field in ("parses", "lives", "flags", "rules", "ijk", "ads", "doh", "hosts", "headers", "proxy"):
        v = cfg.get(field)
        if v is not None and not isinstance(v, list):
            errs.append(f"{field} 不是数组")

    sp = cfg.get("spider")
    if sp and not URL_RE.match(str(sp)):
        errs.append(f"spider 非 URL: {str(sp)[:60]}")

    # 站点名重复（TVBox 允许，但同名的多，检查是否有完全同名不同后端）
    names = Counter(s.get("name") for s in sites if isinstance(s, dict))
    dup_names = [n for n, c in names.items() if c > 1]
    if dup_names:
        WARN.append(f"重名站点 {len(dup_names)} 个（示例: {', '.join(map(str, dup_names[:5]))}）")

    return errs


def check_store(path: str) -> list[str]:
    """多仓格式：urls[] 或 storeHouse[]，每项要有 url/sourceUrl。"""
    errs: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:  # noqa: BLE001
        return [f"JSON 解析失败: {e}"]
    if not isinstance(cfg, dict):
        return ["顶层不是对象"]
    items = cfg.get("urls") or cfg.get("storeHouse") or cfg.get("repos") or []
    if not isinstance(items, list) or not items:
        return ["多仓里没有任何源"]
    bad = 0
    for it in items:
        if not isinstance(it, dict):
            bad += 1
            continue
        u = it.get("url") or it.get("sourceUrl") or it.get("api")
        if not u or not isinstance(u, str) or not u.startswith(("http://", "https://")):
            bad += 1
    if bad:
        errs.append(f"多仓里有 {bad} 条源地址非法")
    return errs


def summarize(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    sites = cfg.get("sites")
    if not isinstance(sites, list):
        print("  （非配置产物，跳过统计）")
        return
    tc = Counter(s.get("type") for s in sites if isinstance(s, dict))
    jars = {s.get("jar") for s in sites if isinstance(s, dict) and s.get("jar")}
    size = os.path.getsize(path) / 1024
    print(f"  sites={len(sites)} parses={len(cfg.get('parses') or [])} "
          f"lives={len(cfg.get('lives') or [])} spider={bool(cfg.get('spider'))} "
          f"per-site-jar={len(jars)} size={size:.0f}KB")
    print("  type 分布: " + ", ".join(f"{k}×{v}" for k, v in sorted(tc.items(), key=lambda x: -x[1])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-errors", type=int, default=25)
    a = ap.parse_args()

    SKIP = {"published.json", "stats.json", "sources.json"}
    if a.all:
        paths = [p for p in sorted(glob.glob(os.path.join(DIST, "*.json")))
                 if os.path.basename(p) not in SKIP]
    else:
        paths = a.paths or [os.path.join(DIST, "index.json")]
    total = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"[缺失] {p}")
            total += 1
            continue
        base = os.path.basename(p)
        print(f"\n=== {base}")
        if base.startswith("storehouse"):
            errs = check_store(p)
            total += len(errs)
            print("  ✓ 多仓校验通过" if not errs else "  ! " + "; ".join(errs))
            continue
        summarize(p)
        errs = check_config(p)
        for w in WARN:
            print(f"  · {w}")
        total += len(errs)
        if errs:
            for e in errs[: a.max_errors]:
                print(f"  ! {e}")
            if len(errs) > a.max_errors:
                print(f"  ... 另有 {len(errs) - a.max_errors} 条")
        else:
            print("  ✓ 结构校验通过")
    print(f"\n合计问题 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
