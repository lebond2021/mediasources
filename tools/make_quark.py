"""挑出「网盘源」（重点是夸克），单独生成一份配置。

思路：只有 spider 类名本身就是网盘向的才算（PanWebShare / PanSou / QuarkPanso / AList …），
通用解析器（XBPQ / XYQHiker / XPath…）即使 ext 里带夸克字样也不算——它们的片源还是采集站。

    py tools/make_quark.py --max 80
    py tools/make_quark.py --kinds quark --out dist/index_quark.json

输出：
    dist/index_quark.json   网盘源配置（sites = 网盘站，parses/lives/globals 继承主配置）
    data/state/quark_sites.json  选站明细
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本身就是网盘/分享向的 spider 类（小写比较）
PAN_CLASSES = {
    "panwebshare", "pansou", "pansearch", "quarkpanso", "quark", "qup", "quarktv",
    "alist", "pushshare", "hunhepan", "funletu", "alishare", "yunpanone", "pikpakshare",
    "duopan", "yunso", "market", "wobg", "wogg", "woGG".lower(), "cloudreve", "yuntu",
    "quarkshare", "quarkso", "panso", "xiaoya", "aliyun", "ucshare", "115share",
}
QUARK_RE = re.compile(r"(quark|夸克)", re.I)
# 这些类要微信小程序激活码才能用，直接排除
NEED_ACTIVATION = re.compile(r"(pansearch|分享夸克|淘应用|请输入验证码)", re.I)
ADULT_RE = re.compile(r"(🔞|🈲|18禁|成人|色情|情色|福利|麻豆|自拍|偷拍|av资源|avzy|souav|ysxq|ckbh|porn|xxx|jav|hentai|sex|约炮|裸|黑料|吃瓜|网红|午夜|三级|探花)", re.I)


def load(path: str) -> dict:
    return json.load(open(path, encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", default=os.path.join(ROOT, "dist", "index_all.json"))
    ap.add_argument("--base", default=os.path.join(ROOT, "dist", "index.json"), help="继承 globals/parses/lives 的主配置")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "index_quark.json"))
    ap.add_argument("--report", default=os.path.join(ROOT, "data", "state", "quark_sites.json"))
    ap.add_argument("--max", type=int, default=80)
    ap.add_argument("--kinds", default="pan", choices=["pan", "quark"], help="pan=所有网盘源 quark=只留夸克相关")
    args = ap.parse_args()

    doc = load(args.from_file)
    sites = [s for s in doc.get("sites") or [] if isinstance(s, dict)]
    picked: list[dict] = []
    seen: set[str] = set()

    for s in sites:
        api = str(s.get("api") or "")
        if not api.startswith("csp_"):
            continue
        cls = api.split("@")[0][4:].lower()
        if cls not in PAN_CLASSES:
            continue
        if not s.get("jar"):
            continue
        name = str(s.get("name") or "")
        if ADULT_RE.search(f"{name} {api}"):
            continue
        if cls == "pansearch" or NEED_ACTIVATION.search(f"{name} {s.get('ext') or ''}"):
            continue
        blob = f"{name} {api} {s.get('ext') or ''}"
        if args.kinds == "quark" and not QUARK_RE.search(blob):
            continue
        key = str(s.get("key") or name)[:64]
        if key in seen:
            continue
        seen.add(key)
        out = dict(s)
        out["searchable"] = 1
        out["quickSearch"] = 1
        picked.append(out)

    def rank(s: dict) -> tuple:
        blob = f"{s.get('name')} {s.get('api')} {s.get('ext')}"
        quark = 0 if QUARK_RE.search(blob) else 1
        return (quark, 0 if s.get("alive") else 1, len(str(s.get("name") or "")))

    picked.sort(key=rank)
    picked = picked[:args.max]

    base = load(args.base) if os.path.exists(args.base) else {}
    cfg = {
        "sites": picked,
        "parses": (base.get("parses") or [])[:40],
        "lives": (base.get("lives") or [])[:20],
    }
    for k in ("doh", "ijk", "headers", "flags", "ads", "hosts", "timeout", "ua", "spider", "wallpaper", "warning"):
        if base.get(k):
            cfg[k] = base[k]

    json.dump(cfg, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"count": len(picked), "kinds": args.kinds,
               "sites": [{"name": s.get("name"), "api": s.get("api"), "jar": s.get("jar"),
                          "ext": s.get("ext")} for s in picked]},
              open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"网盘源 {len(picked)} 个 → {args.out}（{os.path.getsize(args.out)//1024} KB）")
    for s in picked[:15]:
        print(f"   {str(s.get('name'))[:30]:<32} {str(s.get('api'))[:30]:<32} {str(s.get('jar'))[:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
