"""spider jar 选择：下载候选 jar，扫 dex 字符串，选覆盖率最高的一个。

TVBox 的 csp 站点 api 形如 `csp_XBPQ`，真正实现类是 jar 里的
`com.github.catvod.spider.XBPQ`。一个配置只能指定一个 spider jar，
所以要选「能覆盖最多站点所用类名」的那个。

注意 TVBox 允许 spider 写成 `URL;md5;<hash>` 或 `URL;pk;<pkg>`，
实际请求必须去掉后缀。
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor

from .http import Fetcher
from .util import safe_url, sha256

import re

ASCII_STR = re.compile(rb"[A-Za-z][A-Za-z0-9_$]{2,40}")
JAR_SUFFIX = re.compile(r";(?:md5|pk|zip)[^;]*$", re.I)
BAD_EXT = (".php", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".html", ".htm", ".txt")


def jar_net_url(spider: str) -> str:
    """把 `url;md5;xxx` 变成真正可请求的 url。"""
    u = (spider or "").strip()
    u = JAR_SUFFIX.sub("", u)
    for sep in (";md5;", ";MD5;", ";pk;", ";PK;"):
        if sep in u:
            u = u.split(sep)[0]
    return safe_url(u)


def jar_strings(data: bytes, limit: int = 200_000) -> set[str]:
    """粗提 dex 里的标识符字符串。"""
    out: set[str] = set()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return out
    names = zf.namelist()
    for name in names:
        if not name.endswith(".dex"):
            continue
        try:
            blob = zf.read(name)
        except Exception:
            continue
        for m in ASCII_STR.finditer(blob):
            out.add(m.group().decode("ascii", "ignore"))
            if len(out) >= limit:
                return out
    return out


def is_jar_bytes(data: bytes) -> bool:
    return data[:2] == b"PK"


STABLE_HOSTS = ("raw.githubusercontent.com", "github.com", "jsdelivr.net", "gitee.com",
                "ghproxy", "gh-proxy", "gitmirror", "fastly.jsdelivr.net")


def _stability(url: str) -> int:
    u = (url or "").lower()
    return 1 if any(h in u for h in STABLE_HOSTS) else 0


def resolve_spiders(fetcher: Fetcher, candidates: dict[str, int], csp_names: set[str],
                    *, top: int = 24, verbose: bool = False, workers: int = 8) -> dict:
    """一次下载多个候选 jar，得出：全局最优 jar + 每个 csp 类名对应的 jar。

    TVBox 的 sites[] 支持站点级 `jar` 覆盖全局 spider，所以可以把不同来源的
    csp 站点分别指向「真正包含该类」的 jar，而不是硬塞进同一个 jar。
    """
    names = {n for n in csp_names if n}
    merged: dict[str, dict] = {}
    for raw, refs in candidates.items():
        net = jar_net_url(raw)
        if not net or net.lower().endswith(BAD_EXT):
            continue
        slot = merged.setdefault(net, {"raw": raw, "refs": 0})
        slot["refs"] += refs
    ranked = sorted(merged.items(),
                    key=lambda kv: (-_stability(kv[0]), -kv[1]["refs"]))[:top]

    def fetch_one(item):
        net, meta = item
        try:
            r = fetcher.get_binary(net)
        except Exception as e:  # 网络异常不该炸掉整条流水线
            return net, meta, None, str(e)
        return net, meta, r.content or b"", (r.error or ("" if r.status == 200 else f"http-{r.status}"))

    class_jar: dict[str, tuple] = {}
    report, best = [], None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for net, meta, data, err in ex.map(fetch_one, ranked):
            if not data or not is_jar_bytes(data):
                report.append({"url": net, "refs": meta["refs"], "ok": False,
                               "err": err or "not-zip", "size": len(data or b"")})
                continue
            dex_n = _dex_count(data)
            if not dex_n:
                report.append({"url": net, "refs": meta["refs"], "ok": False,
                               "err": "no-dex", "size": len(data)})
                continue
            strs = jar_strings(data)
            found = names & strs
            rank = (_stability(net), meta["refs"], -len(data))
            for n in found:
                cur = class_jar.get(n)
                if cur is None or rank > cur[0]:
                    class_jar[n] = (rank, net)
            rec = {"url": net, "refs": meta["refs"], "ok": True, "size": len(data),
                   "dex": dex_n, "classes_found": len(found),
                   "coverage": round(len(found) / len(names), 3) if names else 0}
            report.append(rec)
            if verbose:
                print(f"      jar {rec['size'] // 1024:>5}KB dex={dex_n} "
                      f"cov={rec['coverage']:.3f} found={len(found)}/{len(names)} "
                      f"refs={meta['refs']} {net[:72]}")
            score = (len(found), _stability(net), meta["refs"], len(data))
            if best is None or score > best[0]:
                best = (score, net, rec, found)

    return {"chosen": best[1] if best else "",
            "detail": best[2] if best else None,
            "classes": best[3] if best else set(),
            "class_jar": {n: v[1] for n, v in class_jar.items()},
            "covered": len(class_jar),
            "total_names": len(names),
            "report": sorted(report, key=lambda x: -(x.get("classes_found") or 0))}


def choose_spider(fetcher: Fetcher, candidates: dict[str, int],
                  csp_names: set[str], *, top: int = 12, verbose: bool = False) -> dict:
    """兼容旧接口：只取全局最优 jar。"""
    return resolve_spiders(fetcher, candidates, csp_names, top=top, verbose=verbose)


def _dex_count(data: bytes) -> int:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        return sum(1 for n in zf.namelist() if n.endswith(".dex"))
    except Exception:
        return 0
