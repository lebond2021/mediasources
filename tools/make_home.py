"""生成「开箱即用」配置：把最稳的采集站排到第一位，用户不用去设置里选首页站源。

TVBox 的「首页站源」留空时用 `sites[0]` 取分类和推荐；站点一多，默认那个可能正好是死的，
于是首页空着，用户被迫手动挑。这里对候选采集站实测 `?ac=list`（分类接口），
按「能返回分类 > 分类多 > 快」排序，把最强的一个放到第一位，并裁到适合电视盒子的大小。

用法：
    py tools/make_home.py --probe 300 --keep 120
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tvh.http import Fetcher  # noqa: E402
from tvh.model import canon_api  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

CLASS_RE = re.compile(r"<ty[^>]*>.*?</ty>", re.S)
JSON_CLASS = re.compile(r'"(?:class|type_name)"\s*:\s*"[^"]+"')
# 首页站源面向所有人，成人站点不能当默认（这类站的「分类」往往还特别多）
ADULT_RE = re.compile(
    r"(🔞|🈲|18禁|成人|色情|情色|福利|麻豆|自拍|偷拍|av资源|avzy|souav|ysxq|ckbh|porn|xxx|jav|hentai|sex)",
    re.I,
)


def is_adult(site: dict) -> bool:
    blob = f"{site.get('name', '')} {site.get('api', '')} {site.get('key', '')}"
    return bool(ADULT_RE.search(blob))


def list_url(api: str) -> str:
    base = api.rstrip("/")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}ac=list"


def probe(fetcher: Fetcher, site: dict) -> dict | None:
    api = str(site.get("api") or "")
    if not api.startswith("http"):
        return None
    t0 = time.time()
    r = fetcher.get(list_url(api), use_cache=False, cache_ttl=0)
    ms = int((time.time() - t0) * 1000)
    if r.error or not r.text:
        return None
    classes = len(CLASS_RE.findall(r.text)) or len(JSON_CLASS.findall(r.text))
    if classes <= 0:
        return None
    return {**site, "_classes": classes, "_ms": ms}


def quality(site: dict) -> int:
    """分类数打底，https 与域名加分、裸 IP 与 http 减分——首页默认站要稳。"""
    api = str(site.get("api") or "")
    q = int(site.get("_classes") or 0)
    host = api.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if api.startswith("https://"):
        q += 6
    else:
        q -= 12
    if re.fullmatch(r"[\d.]+", host):
        q -= 10
    return q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=300, help="最多实测多少个候选")
    ap.add_argument("--keep", type=int, default=120, help="最终保留多少站点")
    ap.add_argument("--workers", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=6)
    args = ap.parse_args()

    full = json.load(open(os.path.join(DIST, "index.json"), encoding="utf-8"))
    sites = full.get("sites") or []

    cand, seen = [], set()
    for s in sites:
        if str(s.get("type")) not in ("0", "1", "2"):
            continue
        api = str(s.get("api") or "")
        if not api.startswith("http") or is_adult(s):
            continue
        c = canon_api(api)
        if c in seen:
            continue
        seen.add(c)
        cand.append(s)
    cand = cand[: args.probe]
    print(f"候选采集站: {len(cand)}（总站点 {len(sites)}，已排除成人站）")

    fetcher = Fetcher(cache_dir=os.path.join(ROOT, "data", "cache"),
                      timeout=args.timeout, retries=1, per_host=8)
    ok: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe, fetcher, s): s for s in cand}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception:  # noqa: BLE001
                r = None
            if r:
                ok.append(r)
    ok.sort(key=lambda x: (-quality(x), x["_ms"]))
    print(f"可用采集站: {len(ok)}")
    for s in ok[:8]:
        print(f"  {quality(s):3d} 分 {s['_classes']:3d} 分类 {s['_ms']:5d}ms "
              f"{s.get('name', '')[:16]:16s} {s['api'][:56]}")

    # 只保留实测可用的站点：盒子加载快、默认站源一定活着；要全量请用 index.json
    head = [{k: v for k, v in s.items() if not k.startswith("_")} for s in ok[: args.keep]]
    if head:
        first = dict(head[0])
        first["name"] = f"★主站·{first.get('name', '采集')}"
        head[0] = first

    out = {
        "spider": full.get("spider", ""),
        "wallpaper": full.get("wallpaper", ""),
        "logo": full.get("logo", ""),
        "notice": full.get("notice", ""),
        "sites": head,
        "parses": (full.get("parses") or [])[:80],
        "lives": (full.get("lives") or [])[:40],
    }
    for k in ("rules", "ijk", "doh", "headers", "flags", "ads", "hosts",
              "timeout", "ua", "playerType", "style"):
        if full.get(k):
            out[k] = full[k]
    out = {k: v for k, v in out.items() if v not in (None, "", [], {})}

    path = os.path.join(DIST, "index_home.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"→ {path}  sites={len(out['sites'])}  {os.path.getsize(path)//1024}KB")
    if head:
        print(f"   首页默认站源: {head[0].get('name')}  {head[0].get('api')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
