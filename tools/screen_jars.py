"""离线识别「会弹激活码验证框」的 jar。

思路：这类 spider 的验证框文案写死在 dex 里（「请先进行接口验证」「淘应用」
「免费获取验证码」「激活」），把 jar 下下来在字节里搜这些 UTF-8 字符串即可，
不用一台一台真机试。

用法：
    py tools/screen_jars.py --top 40
输出 data/state/jar_gate.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "jars")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tvbox-agg/1.0"}

# 命中任意一个，就认为这个 jar 带激活码验证
GATE_MARKS = ["淘应用", "免费获取验证码", "请先进行接口验证", "请输入验证码", "接口验证"]
# 辅助判断：这些说明它是网盘向的
PAN_MARKS = ["夸克", "阿里云盘", "token.txt", "cookie.txt", "分享链接"]

ADULT = re.compile(r"(18lib|c18h|/18/|成人|色情|🔞|🈲)", re.I)
PAN_CLASSES = {
    "panwebshare", "quarkshare", "quarkpanso", "pansou", "alist", "alishare",
    "pushshare", "hunhepan", "yunpanone", "pikpakshare", "yunso", "tianyi",
    "duopan", "funletu", "market", "wobg", "wogg",
}


def cls_of(site: dict) -> str:
    api = str(site.get("api") or "").split("@")[0]
    return api[4:].lower() if api.startswith("csp_") else ""


def net_jar(url: str) -> str:
    return re.sub(r";(?:md5|pk);[A-Za-z0-9+/=]+$", "", url.strip())


def fetch(url: str, timeout: float = 20.0) -> bytes:
    os.makedirs(CACHE, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", url)[-80:]
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return open(path, "rb").read()
    r = requests.get(url, headers=UA, timeout=timeout, verify=False)
    data = r.content if r.status_code == 200 else b""
    if data:
        open(path, "wb").write(data)
    return data


def scan(jar: str) -> dict:
    try:
        data = fetch(jar)
    except Exception as e:
        return {"jar": jar, "ok": False, "note": type(e).__name__, "gated": False, "marks": []}
    if not data:
        return {"jar": jar, "ok": False, "note": "empty", "gated": False, "marks": []}
    text = data.decode("utf-8", "ignore")
    marks = [m for m in GATE_MARKS if m in text]
    pan = [m for m in PAN_MARKS if m in text]
    return {
        "jar": jar, "ok": True, "size": len(data),
        "gated": bool(marks), "marks": marks, "pan_marks": pan,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "dist", "index_all.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "state", "jar_gate.json"))
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    doc = json.load(open(args.src, encoding="utf-8"))
    refs: dict[str, int] = {}
    for s in doc.get("sites") or []:
        cls = cls_of(s)
        if cls not in PAN_CLASSES:
            continue
        jar = s.get("jar")
        if not jar or not str(jar).startswith("http"):
            continue
        if ADULT.search(f"{s.get('name')} {s.get('api')} {s.get('ext')}"):
            continue
        j = net_jar(str(jar))
        refs[j] = refs.get(j, 0) + 1

    top = sorted(refs.items(), key=lambda kv: -kv[1])[: args.top]
    print(f"网盘向 jar {len(refs)} 个，扫描前 {len(top)} 个")

    out = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for f in cf.as_completed([ex.submit(scan, j) for j, _ in top]):
            r = f.result()
            r["refs"] = refs.get(r["jar"], 0)
            out.append(r)
    out.sort(key=lambda r: (-r["refs"], r["jar"]))

    gated = [r for r in out if r.get("gated")]
    clean = [r for r in out if r.get("ok") and not r.get("gated")]
    print(f"  带激活验证 {len(gated)} 个 / 干净 {len(clean)} 个 / 失败 {len(out)-len(gated)-len(clean)} 个")
    for r in gated[:8]:
        print(f"   [GATE] refs={r['refs']:>3} {r['jar'][-70:]}  {r['marks']}")
    for r in clean[:8]:
        print(f"   [ OK ] refs={r['refs']:>3} pan={r.get('pan_marks')} {r['jar'][-60:]}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({"ts": __import__("time").time(), "jars": out}, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
