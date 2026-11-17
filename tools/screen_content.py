"""按「内容」筛站：抓两页片名，判断这是不是正常的影视站。

名字里带不带「成人」并不可靠——很多最「快」的站名字无害，内容却是色情。
这里直接看片名与分类名：

    py tools/screen_content.py --from dist/index_all.json --only-ok --workers 24
    py tools/screen_content.py --sites data/agg_sites.json --workers 8

输出 data/state/site_content.json：
    {"ts":.., "sites":[{api,name,total,adult_ratio,kind}]}

kind: movie / drama / anime / sports / adult / mixed / empty
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 9; TV) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

ADULT_WORDS = re.compile(
    r"(性交|做爱|自慰|自摸|裸|乳|射精|射脸|肛|淫|骚|高潮|脱衣|私密|约炮|中出|内射|人妻|熟女|巨乳|爆乳|痴女|"
    r"颜射|口交|乱伦|迷奸|强奸|调教|sm|束縛|捆绑|无码|有码|素人|女优|男优|av女|jav|porn|hentai|xxx|"
    r"约啪|约啪|成人|色情|情色|三级|偷拍|走光|裙底|巨臀|蜜穴|骚穴|阳具|阴茎|阴道|睾丸|舔|淫荡|淫乱|"
    r"包养|援交|福利姬|深夜福利|里番|肉番|工口|男同|女同|蕾丝|榨精|潮吹|吞精|口爆|乳交|足交|"
    r"片寄|中出し|お義姉|痴漢|ナンパ|人妻|素人|企画|鬼畜|触手)",
    re.I,
)
KIND_WORDS = {
    "anime": re.compile(r"(动漫|动画|里番|新番|番剧|剧场版|OVA|动画片)", re.I),
    "sports": re.compile(r"(体育|足球|篮球|NBA|赛事|直播|联赛|杯赛|U1\d|友谊赛)", re.I),
    "drama": re.compile(r"(电视剧|连续剧|剧集|短剧|美剧|韩剧|日剧|港剧|泰剧|综艺)", re.I),
    "movie": re.compile(r"(电影|片|影片|动作|喜剧|爱情|科幻|恐怖|剧情|战争|纪录)", re.I),
}


def sess() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update(UA)
    return s


def api_q(api: str, query: str) -> str:
    return api + ("&" if "?" in api else "?") + query


def screen(site: dict, timeout: float = 8.0) -> dict:
    api = str(site.get("api") or "")
    s = sess()
    names: list[str] = []
    classes: list[str] = []
    for pg in (1, 2):
        try:
            j = s.get(api_q(api, f"ac=videolist&pg={pg}"), timeout=timeout, verify=False).json()
        except Exception:
            continue
        for c in j.get("class") or []:
            if isinstance(c, dict):
                classes.append(str(c.get("type_name") or ""))
        for it in (j.get("list") or [])[:20]:
            if isinstance(it, dict):
                names.append(str(it.get("vod_name") or ""))
    total = len(names)
    if not total:
        return {"api": api, "name": site.get("name"), "total": 0, "adult_ratio": 0.0, "kind": "empty"}
    adult = sum(1 for n in names if ADULT_WORDS.search(n))
    ratio = adult / total
    kind = "adult" if ratio >= 0.2 else "mixed" if ratio >= 0.05 else "main"
    if kind == "main":
        blob = " ".join(classes) + " " + " ".join(names)
        for k in ("anime", "sports", "drama", "movie"):
            if KIND_WORDS[k].search(blob):
                kind = k
                break
    return {"api": api, "name": site.get("name"), "total": total,
            "adult_ratio": round(ratio, 3), "kind": kind}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", default=os.path.join(ROOT, "dist", "index.json"))
    ap.add_argument("--sites", default="", help="直接给一个 {sites:[{name,api}]} 文件")
    ap.add_argument("--only-ok", action="store_true", help="只筛 rate_sites 判定可播的站")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "state", "site_content.json"))
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args()

    doc = json.load(open(args.sites or args.from_file, encoding="utf-8"))
    sites = [s for s in doc.get("sites") or [] if isinstance(s, dict) and str(s.get("api", "")).startswith("http")]
    if args.only_ok:
        ok = set()
        for p in ("site_quality.json", "site_quality1.json", "site_quality2.json"):
            fp = os.path.join(ROOT, "data", "state", p)
            if os.path.exists(fp):
                for r in (json.load(open(fp, encoding="utf-8")).get("sites") or []):
                    if r.get("url_ok"):
                        ok.add(str(r.get("api")))
        sites = [s for s in sites if str(s["api"]) in ok]
    sites = [s for s in sites if s.get("type", 1) == 1]
    print(f"待筛 {len(sites)} 个站")

    out: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(screen, s, args.timeout) for s in sites]
        for f in cf.as_completed(futs):
            try:
                out.append(f.result())
            except Exception:
                pass
    out.sort(key=lambda r: (r["kind"] != "main", -r["adult_ratio"]))
    json.dump({"ts": int(time.time()), "sites": out}, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    from collections import Counter
    print(Counter(r["kind"] for r in out))
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
