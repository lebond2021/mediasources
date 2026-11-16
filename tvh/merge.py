"""最终配置合成：全局字段合并、站点排序、输出多种形态。"""
from __future__ import annotations

import json
import re
import time
from collections import Counter

from .model import TYPE_NAMES, SiteRecord
from .util import as_int, is_http, norm_url, safe_url, urlsplit

GLOBAL_LIST_KEYS = ("flags", "rules", "ijk", "ads", "doh", "hosts", "proxy", "headers", "parses")
GLOBAL_SCALAR_KEYS = ("wallpaper", "logo", "notice", "style", "timeout", "ext", "homepage",
                      "ua", "playerType", "doh", "lives")


def _dedupe_by(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
    seen, out = set(), []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        sig = tuple(str(it.get(k, "")) for k in keys if it.get(k) is not None)
        if not sig or sig in seen:
            continue
        seen.add(sig)
        out.append(it)
    return out


def merge_globals(docs_globals: list[dict], base: dict | None = None) -> dict:
    """把多个配置的全局段合并成一个（列表段做并集）。"""
    out: dict = {}
    if base:
        out.update({k: v for k, v in base.items()
                    if k not in ("sites", "parses", "lives", "urls", "storeHouse")})
    for key in GLOBAL_LIST_KEYS:
        pool: list = []
        for g in docs_globals:
            v = (g or {}).get(key)
            if isinstance(v, list):
                pool.extend(v)
        if not pool:
            continue
        if key == "flags":
            out[key] = _dedupe_by(pool, ("key", "name"))
        elif key == "rules":
            out[key] = _dedupe_by(pool, ("name", "hosts", "regex"))
        elif key == "ijk":
            out[key] = _dedupe_by(pool, ("group", "name"))
        elif key == "ads":
            out[key] = _dedupe_by(pool, ("name", "api", "pattern"))
        elif key == "hosts":
            out[key] = _dedupe_by(pool, ("domain", "host", "name"))
        elif key == "proxy":
            out[key] = _dedupe_by(pool, ("host", "name"))
        elif key == "headers":
            out[key] = _dedupe_by(pool, ("name", "host"))
        elif key == "doh":
            if all(isinstance(x, str) for x in pool):
                out[key] = list(dict.fromkeys(pool))[:20]
            else:
                out[key] = _dedupe_by(pool, ("name", "url"))
    for key in GLOBAL_SCALAR_KEYS:
        if out.get(key) not in (None, "", [], {}):
            continue
        for g in docs_globals:
            v = (g or {}).get(key)
            if v not in (None, "", [], {}):
                out[key] = v
                break
    return out


def order_records(records: list[SiteRecord], *, drop_dead: bool = True,
                  limit: int | None = None) -> list[SiteRecord]:
    def rank(r: SiteRecord):
        t = as_int(r.data.get("type"), -1)
        alive = r.alive
        bucket = {1: 0, -1: 1, 0: 2}.get(alive, 1)
        lat = r.latency_ms if r.latency_ms and r.latency_ms > 0 else 99999
        # 采集站优先（响应快、体验好），其次 csp
        kind = 0 if t in (0, 1) else 1 if t in (3, 4, 9) else 2
        # 被越多独立配置引用 = 越主流，同档内优先
        refs = -len(r.sources or ())
        return (bucket, kind, refs, lat, str(r.data.get("name", "")))

    out = [r for r in records if not (drop_dead and r.alive == 0)]
    out.sort(key=rank)
    if limit:
        out = out[:limit]
    return out


_SPEED_TAG = re.compile(r"^\s*\[[^\]]*\d+\s*ms[^\]]*\]\s*")
_SPEED_TAG2 = re.compile(r"^\s*\[\s*\d+\s*(?:ms|MS|毫秒)?\s*\]\s*")
_FLAG_KEYS = ("searchable", "quickSearch", "filterable", "changeable")
# api 合法性：http(s)、csp_类名、py_类名、本地伪协议
_API_OK = re.compile(r"^(?:https?://|csp_[A-Za-z0-9_]+$|py_[A-Za-z0-9_]+$|"
                     r"js://|py://|assets://|file://|clan://|data://)", re.I)
# jar 合法性：http(s)（可带 ;md5;xxx 后缀）或本地伪协议
_JAR_OK = re.compile(r"^(?:https?://[^\s]+\.(?:jar|js|py)(?:;(?:md5|pk);[A-Za-z0-9+/=]+)?$|"
                     r"js://|assets://|file://|clan://)", re.I)


def api_ok(v) -> bool:
    return isinstance(v, str) and bool(_API_OK.match(v.strip()))


def jar_ok(v) -> bool:
    return isinstance(v, str) and bool(_JAR_OK.match(v.strip()))


_NON_ASCII = re.compile(r"[^\x21-\x7e]")
_MD5_TAIL = re.compile(r"^(.*?)(;(?:md5|pk);[A-Za-z0-9+/=]+)$", re.I)


_TAIL_RE = re.compile(r"^(.*?)(;(?:md5|pk);[A-Za-z0-9+/=]+)$", re.I)


def _jar_plausible(u: str) -> bool:
    """排除 `https://raw.githubusercontent.com/jar/pg.jar` 这类丢掉了 user/repo 的残废地址。"""
    m = _TAIL_RE.match(u.strip())
    v = m.group(1) if m else u.strip()
    try:
        p = urlsplit(v)
    except ValueError:
        return False
    host, path = p.netloc.lower(), p.path
    if path.startswith("/http://") or path.startswith("/https://"):
        return _jar_plausible(path[1:])
    segs = [x for x in path.split("/") if x]
    if "githubusercontent" in host:
        return len(segs) >= 4
    if "jsdelivr" in host:
        return path.startswith("/gh/") and len(segs) >= 5
    return bool(segs) and segs[-1].lower().endswith((".jar", ".js", ".py", ".dex"))


def _encode_url(v: str) -> str:
    """把含中文/空格的 URL 百分号编码（TVBox 端不会自动编码，会直接 404）。"""
    if not _NON_ASCII.search(v):
        return v
    m = _MD5_TAIL.match(v)
    tail = ""
    if m:
        v, tail = m.group(1), m.group(2)
    return safe_url(v) + tail


def clean_site(s: dict) -> dict:
    """输出前清洗单个站点条目：类型归整、去掉 None/空串、去掉源站的速度前缀。"""
    out: dict = {}
    for k, v in s.items():
        if k.startswith("_"):
            continue
        if v is None or v == "":
            continue
        if isinstance(v, str) and k in ("api", "ext", "jar", "name", "key"):
            v = v.strip()
            if not v:
                continue
        if k == "type":
            v = as_int(v, 3) if not isinstance(v, int) else v
        elif k in _FLAG_KEYS:
            v = 1 if str(v).lower() in ("1", "true", "yes") else 0
        elif k == "api":
            if not api_ok(v):
                return {}   # api 不可用的站点直接丢弃
        elif k == "jar":
            if not jar_ok(v) or not _jar_plausible(v):
                continue    # 丢掉坏 jar 字段，站点本身保留（用全局 spider）
        elif k == "ext" and not isinstance(v, (str, dict, list)):
            continue    # ext 只能是字符串/对象/数组，int/bool 一律丢
        elif k == "name" and isinstance(v, str):
            v = _SPEED_TAG2.sub("", _SPEED_TAG.sub("", v)).strip() or v
        if k in ("api", "ext", "jar") and isinstance(v, str) and is_http(v):
            v = _encode_url(v)
        out[k] = v
    if not api_ok(out.get("api")):
        return {}
    return out


def _clean_dict(d: dict) -> dict:
    return {k: v for k, v in (d or {}).items()
            if not str(k).startswith("_") and v not in (None, "")}


def build_config(records: list[SiteRecord], parses: list[dict], lives: list[dict],
                 groups: list[dict], globals_: dict, *, spider: str = "",
                 name_tag: bool = False, drop_dead: bool = True,
                 limit: int | None = None) -> dict:
    ordered = order_records(records, drop_dead=drop_dead, limit=limit)
    sites = []
    for r in ordered:
        s = clean_site(r.data)
        if not s:
            continue
        if name_tag and r.alive == 1 and r.latency_ms and r.latency_ms > 0:
            s["name"] = f"[{r.latency_ms}ms]{s.get('name', '')}"
        sites.append(s)
    cfg = {"spider": spider or globals_.get("spider", "") or ""}
    for k in ("wallpaper", "logo", "notice", "style", "timeout", "ua", "playerType"):
        if globals_.get(k) not in (None, "", [], {}):
            cfg[k] = globals_[k]
    cfg["sites"] = sites
    if groups:
        cfg["lives"] = [{"group": g.get("group"), "channels": g.get("channels") or []}
                        for g in groups]
    elif lives:
        cfg["lives"] = [_clean_dict(x) for x in lives]
    if parses:
        cfg["parses"] = [_clean_dict(x) for x in parses]
    for k in ("flags", "rules", "ijk", "ads", "doh", "hosts", "proxy", "headers"):
        if globals_.get(k):
            cfg[k] = globals_[k]
    return cfg


def store_house(entries: list[dict], title: str = "TVBox 聚合源") -> dict:
    return {"storeHouse": [{"sourceName": e.get("name") or e["url"], "sourceUrl": e["url"]}
                           for e in entries if e.get("url")]}


def stats_of(records: list[SiteRecord], docs_n: int, urls_n: int,
             parses_n: int, lives_n: int, started: float) -> dict:
    types = Counter(as_int(r.data.get("type"), -1) for r in records)
    alive = Counter(r.alive for r in records)
    hosts = Counter()
    for r in records:
        api = str(r.data.get("api") or "")
        if is_http(api):
            from .util import host_of
            hosts[host_of(api)] += 1
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_s": round(time.time() - started, 1),
        "sources_crawled": docs_n,
        "urls_seen": urls_n,
        "sites_total": len(records),
        "sites_alive": alive.get(1, 0),
        "sites_dead": alive.get(0, 0),
        "sites_unknown": alive.get(-1, 0),
        "by_type": {str(k): v for k, v in sorted(types.items(), key=lambda kv: -kv[1])},
        "by_type_name": {TYPE_NAMES.get(k, f"type{k}"): v
                         for k, v in sorted(types.items(), key=lambda kv: -kv[1])},
        "parses": parses_n,
        "lives": lives_n,
        "top_hosts": hosts.most_common(10),
    }


def write_json(path: str, obj) -> None:
    import os
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    import os as _os
    _os.replace(tmp, path)
