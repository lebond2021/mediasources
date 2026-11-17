"""给采集站（type=1 苹果 CMS）实测打分：延迟、分类数、真实画质、真实速率。

打分过程（每站）：
  1) ?ac=list            → 拿分类数 + 首屏延迟
  2) ?ac=videolist&t=..  → 拿 10 条片
  3) ?ac=detail&ids=..   → 拿播放地址（最多试 3 部片）
  4) 拉 m3u8 master      → 有 STREAM-INF 就挑最高码率变体，解析 RESOLUTION
  5) 读 400KB / 4 秒     → 算真实 KB/s

输出 data/state/site_quality.json：
  {"ts":.., "sites":[{key,name,api,ms,classes,kbps,res,url_ok,adult,title}]}

用法：
    py tools/rate_sites.py --limit 200 --workers 32
    py tools/rate_sites.py --from dist/index.json --only-type1 --workers 40
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
ADULT_RE = re.compile(r"(🔞|🈲|18禁|成人|色情|情色|福利|麻豆|自拍|偷拍|av资源|avzy|souav|ysxq|ckbh|porn|xxx|jav|hentai|sex|约炮|裸)", re.I)
CAP = 400 * 1024


def sess() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update(UA)
    return s


def jget(s: requests.Session, url: str, timeout: float = 8.0):
    t0 = time.time()
    try:
        r = s.get(url, timeout=timeout, verify=False)
        if r.status_code != 200:
            return None, (time.time() - t0) * 1000
        return r.json(), (time.time() - t0) * 1000
    except Exception:
        return None, (time.time() - t0) * 1000


def api_of(api: str, query: str) -> str:
    base = api.strip()
    sep = "&" if "?" in base else "?"
    return base + sep + query


def measure_stream(s: requests.Session, url: str, timeout: float = 8.0) -> tuple[float, int, str]:
    """返回 (KB/s, 分辨率高度, 说明)。"""
    try:
        r = s.get(url, timeout=timeout, verify=False, stream=True)
        if r.status_code != 200:
            return 0.0, 0, f"http{r.status_code}"
        first = r.raw.read(24000, decode_content=True) or b""
        text = first.decode("utf-8", "ignore")
        height = 0
        target = url
        if "#EXTM3U" in text:
            variants = re.findall(r"#EXT-X-STREAM-INF:([^\n]+)\n([^\n#]+)", text)
            if variants:
                best, best_bw = None, -1
                for attrs, uri in variants:
                    m = re.search(r"BANDWIDTH=(\d+)", attrs)
                    bw = int(m.group(1)) if m else 0
                    if bw > best_bw:
                        best_bw, best = bw, uri.strip()
                    rm = re.search(r"RESOLUTION=\d+x(\d+)", attrs)
                    if rm:
                        height = max(height, int(rm.group(1)))
                if best:
                    from urllib.parse import urljoin
                    target = urljoin(url, best)
                    r.close()
                    r = s.get(target, timeout=timeout, verify=False, stream=True)
                    if r.status_code != 200:
                        return 0.0, height, f"variant{r.status_code}"
        t0 = time.time()
        got = 0
        try:
            for chunk in r.iter_content(65536):
                got += len(chunk)
                if got >= CAP or time.time() - t0 > 5.0:
                    break
        finally:
            r.close()
        dt = max(0.3, time.time() - t0)
        kbps = (got / 1024.0) / dt
        return kbps, height, "ok"
    except Exception as e:
        return 0.0, 0, type(e).__name__


def rate_site(site: dict, timeout: float = 8.0) -> dict:
    s = sess()
    api = str(site.get("api") or "")
    rec = {
        "key": site.get("key"), "name": site.get("name"), "api": api,
        "ms": 0, "classes": 0, "kbps": 0.0, "res": 0, "url_ok": 0, "title": "", "note": "",
        "adult": bool(ADULT_RE.search(f"{site.get('name')} {api}")),
    }
    data, ms = jget(s, api_of(api, "ac=list"), timeout)
    rec["ms"] = int(ms)
    if not isinstance(data, dict):
        rec["note"] = "list-fail"
        return rec
    classes = [c for c in (data.get("class") or []) if isinstance(c, dict)]
    rec["classes"] = len(classes)
    tid = None
    for c in classes:
        if re.search(r"(电影|片)", str(c.get("type_name") or "")):
            tid = c.get("type_id")
            break
    if tid is None and classes:
        tid = classes[0].get("type_id")

    items, _ = jget(s, api_of(api, f"ac=videolist&t={tid}&pg=1"), timeout) if tid is not None else (None, 0)
    lst = [x for x in ((items or {}).get("list") or []) if isinstance(x, dict) and x.get("vod_id")]
    if not lst:
        # 有些站不认 t 参数，直接拿首页列表
        items, _ = jget(s, api_of(api, "ac=videolist&pg=1"), timeout)
        lst = [x for x in ((items or {}).get("list") or []) if isinstance(x, dict) and x.get("vod_id")]
    if not lst:
        items, _ = jget(s, api_of(api, "ac=detail&pg=1"), timeout)
        lst = [x for x in ((items or {}).get("list") or []) if isinstance(x, dict) and x.get("vod_id")]
    if not lst:
        rec["note"] = "no-items"
        return rec

    best_kbps, best_h, best_title = 0.0, 0, ""
    for it in lst[:4]:
        d, _ = jget(s, api_of(api, f"ac=detail&ids={it['vod_id']}"), timeout)
        dl = [x for x in ((d or {}).get("list") or []) if isinstance(x, dict)]
        if not dl:
            continue
        pu = str(dl[0].get("vod_play_url") or "")
        m = re.search(r"(https?://[^\s#$]+?\.(?:m3u8|mp4)[^\s#$]*)", pu)
        if not m:
            continue
        url = m.group(1)
        kbps, h, note = measure_stream(s, url, timeout)
        if kbps > best_kbps:
            best_kbps, best_h, best_title = kbps, h, str(dl[0].get("vod_name") or "")
            rec["note"] = note
            try:
                from urllib.parse import urlsplit as _us
                rec["host"] = _us(url).netloc.lower()
            except Exception:
                rec["host"] = ""
        if best_kbps >= 2500:
            break
    rec["kbps"] = round(best_kbps, 1)
    rec["res"] = best_h
    rec["title"] = best_title
    rec["url_ok"] = 1 if best_kbps > 0 else 0
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", default=os.path.join(ROOT, "dist", "index.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "state", "site_quality.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--min-kbps", type=float, default=0.0, help="只保留高于该速率的（仅影响统计打印）")
    args = ap.parse_args()

    doc = json.load(open(args.from_file, encoding="utf-8"))
    sites = [s for s in doc.get("sites") or []
             if s.get("type") == 1 and str(s.get("api", "")).startswith("http")]
    if args.limit:
        sites = sites[:args.limit]
    print(f"待测 {len(sites)} 个采集站，并发 {args.workers}")

    out: list[dict] = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(rate_site, s, args.timeout): s for s in sites}
        done = 0
        for f in cf.as_completed(futs):
            done += 1
            try:
                out.append(f.result())
            except Exception as e:
                s = futs[f]
                out.append({"key": s.get("key"), "name": s.get("name"), "api": s.get("api"),
                            "kbps": 0, "res": 0, "url_ok": 0, "note": type(e).__name__})
            if done % 25 == 0:
                ok = sum(1 for x in out if x.get("url_ok"))
                print(f"  {done}/{len(sites)}  可播 {ok}  {time.time()-t0:.0f}s", flush=True)

    out.sort(key=lambda x: (-x.get("kbps", 0), x.get("ms", 9999)))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({"ts": int(time.time()), "count": len(out), "sites": out},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    ok = [x for x in out if x.get("url_ok")]
    hd = [x for x in ok if x.get("res", 0) >= 720 or x.get("kbps", 0) >= 1500]
    fast = [x for x in ok if x.get("kbps", 0) >= args.min_kbps] if args.min_kbps else ok
    print(f"\n完成 {len(out)} 站，{time.time()-t0:.0f}s")
    print(f"  可播 {len(ok)}  高清(≥720p 或 ≥1.5MB/s) {len(hd)}  达速率门槛 {len(fast)}")
    for x in out[:10]:
        print(f"   {x['kbps']:>7.1f} KB/s  {x.get('res') or '-':>4}p  {x.get('ms')}ms  {x['name'][:18]}")
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
