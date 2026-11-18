"""从网盘源池里筛出「非激活码」的一批，生成独立配置。

排除需要微信小程序激活码的类（Wobg/WoGG/Wogg/PanSearch 玩偶系）。
保留：PanWebShare / QuarkShare / QuarkPanso / PanSou / AList / AliShare /
      PushShare / HunHePan / YunPanOne / PikPakShare / YunSo / TianYi / Market

用法：
    py tools/make_pan2.py --out dist/index_pan2.json --max 60
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADULT_RE = re.compile(
    r"(🔞|🈲|18禁|成人|色情|情色|福利|麻豆|自拍|偷拍|av资源|avzy|souav|ysxq|ckbh|porn|xxx|jav|hentai|sex|18lib|c18h)",
    re.I,
)

# 需要激活码 / 已知会弹「淘应用」验证框的 spider 类
GATED = {"wobg", "wogg", "pansearch", "woog", "woGG".lower()}

# 保留类（顺序=展示优先级）
ORDER = [
    "panwebshare", "quarkshare", "quarkpanso", "pansou", "alist",
    "alishare", "pushshare", "hunhepan", "yunpanone", "pikpakshare",
    "yunso", "tianyi", "market", "duopan", "funletu",
]


def cls_of(site: dict) -> str:
    api = str(site.get("api") or "")
    api = api.split("@")[0]
    if api.startswith("csp_"):
        api = api[4:]
    return api.lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "data", "state", "pan_sites.json"))
    ap.add_argument("--base", default=os.path.join(ROOT, "dist", "index_all.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "index_pan2.json"))
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--per-class", type=int, default=8)
    ap.add_argument("--allow-gated", action="store_true")
    ap.add_argument("--require-jar", action="store_true", help="只要自带 jar 的站（避免落到全局 spider 上被激活码拦）")
    args = ap.parse_args()

    pool = json.load(open(args.src, encoding="utf-8"))
    sites = pool.get("sites") if isinstance(pool, dict) else pool
    sites = sites or []

    keep, seen = [], set()
    for s in sites:
        cls = cls_of(s)
        if not cls:
            continue
        if cls in GATED and not args.allow_gated:
            continue
        if cls not in ORDER:
            continue
        name = str(s.get("name") or "")
        blob = f"{name} {s.get('api')} {s.get('ext')}"
        if ADULT_RE.search(blob):
            continue
        if args.require_jar and not str(s.get("jar") or "").startswith("http"):
            continue
        key = (cls, str(s.get("ext"))[:160])
        if key in seen:
            continue
        seen.add(key)
        s = dict(s)
        s["type"] = 3
        if not s.get("key"):
            base_key = re.sub(r"[^A-Za-z0-9]+", "", str(s.get("name") or cls))[:12] or cls
            s["key"] = f"pan2_{base_key}_{len(keep)+1}"
        s.pop("key_len", None)
        keep.append(s)

    keep.sort(key=lambda s: ORDER.index(cls_of(s)) if cls_of(s) in ORDER else 99)
    # 每个类最多留 --per-class 个，避免被单一 spider 类占满
    per = max(1, args.per_class)
    capped, cnt = [], {}
    for s in keep:
        c = cls_of(s)
        if cnt.get(c, 0) >= per:
            continue
        cnt[c] = cnt.get(c, 0) + 1
        capped.append(s)
    keep = capped[: args.max]

    base = json.load(open(args.base, encoding="utf-8"))
    cfg = {
        "name": f"网盘源精选（{len(keep)} 站）",
        "sites": keep,
        "parses": (base.get("parses") or [])[:60],
        "lives": (base.get("lives") or [])[:20],
    }
    for k in ("doh", "ijk", "headers", "flags", "ads", "hosts", "timeout", "ua", "rules"):
        if k in base:
            cfg[k] = base[k]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(cfg, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)

    from collections import Counter
    c = Counter(cls_of(s) for s in keep)
    print(f"保留 {len(keep)} 站 → {args.out}  ({os.path.getsize(args.out)//1024}KB)")
    print("类分布:", c.most_common())
    for s in keep[:10]:
        print("  -", s.get("name"), "|", s.get("api"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
