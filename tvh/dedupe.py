"""去重：站点（多策略）、解析、直播；并修正 key 冲突。"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from .model import (SiteRecord, norm_name, parse_lives, site_backend_id,
                    site_dedupe_id, site_signature, site_sort_rank)
from .util import as_int, host_of, is_http, norm_url, sha1
from urllib.parse import urlsplit


def _fill_missing(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if k.startswith("_"):
            continue
        if dst.get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
            dst[k] = v


def dedupe_sites(sites: list[dict], *, profile: str = "backend",
                 source_of: bool = True) -> list[SiteRecord]:
    """按「同一后端」聚类去重。

    profile='backend'  同一后端只保留一条（默认，聚合去重）
    profile='exact'    后端 + ext 完全相同才合并（保留多入口）
    profile='key'      仅按 key 去重（宽口径，兼容旧习惯）
    """
    if profile == "key":
        keyfn = lambda s: str(s.get("key") or site_backend_id(s))
    elif profile == "exact":
        keyfn = site_dedupe_id
    else:
        keyfn = site_backend_id

    buckets: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for s in sites:
        k = keyfn(s)
        if k not in buckets:
            order.append(k)
        buckets[k].append(s)

    out: list[SiteRecord] = []
    for k in order:
        group = buckets[k]
        group.sort(key=site_sort_rank)
        rep = dict(group[0])
        variants = {site_dedupe_id(s): s for s in group}
        for other in group[1:]:
            _fill_missing(rep, other)
        rec = SiteRecord(backend_id=k, data=rep, variants=len(group),
                         sources=list(dict.fromkeys(
                             x.get("_src", "") for x in group if x.get("_src"))))
        out.append(rec)
    return out


_TAG_TAIL = re.compile(r"\s*[·|@#(（]\s*\d+\s*[)）]?$")


def _site_tag(r: SiteRecord) -> str:
    """给同名站点挑一个短标识：csp 用类名，采集站用域名。"""
    api = str(r.data.get("api") or "")
    if api.lower().startswith("csp_"):
        return api[4:].strip()[:24]
    if is_http(api):
        h = host_of(api) or ""
        if h.startswith("www."):
            h = h[4:]
        return h[:32]
    ext = r.data.get("ext")
    if isinstance(ext, str) and is_http(ext):
        return (host_of(ext) or "")[:32]
    return ""


def disambiguate_names(records: list[SiteRecord]) -> int:
    """同名但不同后端的站点：名字后加 `·短标识`，避免用户分不清。返回改名数。"""
    by_name: dict[str, list[SiteRecord]] = defaultdict(list)
    for r in records:
        by_name[norm_name(r.data.get("name", ""))].append(r)
    changed = 0
    for name, group in by_name.items():
        if not name or len(group) < 2:
            continue
        used: dict[str, int] = {}
        for r in sorted(group, key=lambda x: site_sort_rank(x.data)):
            base = _TAG_TAIL.sub("", str(r.data.get("name") or "站点").strip()) or "站点"
            tag = _site_tag(r)
            label = f"{base}·{tag}" if tag and tag.lower() not in base.lower() else base
            used[label] = used.get(label, 0) + 1
            if used[label] > 1:
                label = f"{label}{used[label]}"
            if label != r.data.get("name"):
                r.data["name"] = label
                changed += 1
    return changed


_KEY_BAD = re.compile(r"[^\w\u4e00-\u9fff.\-]")


def fix_keys(records: list[SiteRecord]) -> int:
    """TVBox 要求 key 全局唯一，冲突时追加 _2/_3。返回修正数。"""
    used: set[str] = set()
    fixed = 0
    for r in records:
        k = str(r.data.get("key") or "").strip()
        if not k:
            k = str(r.data.get("api") or "site")
        k = k.replace("|", "_")
        if len(k) > 64:
            k = k[:48] + "_" + sha1(k)[:8]
        base = k
        n = 2
        while k in used:
            k = f"{base}_{n}"
            n += 1
        if k != r.data.get("key"):
            fixed += 1
        r.data["key"] = k
        used.add(k)
    return fixed


# ------------------------------------------------------------------ 解析
def dedupe_parses(parses: list[dict], limit: int = 0) -> list[dict]:
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for p in parses:
        url = str(p.get("url") or "").strip()
        ext = p.get("ext")
        # 丢掉明显不是解析器的条目（url 既不是 http 也没有 ext）
        if not is_http(url) and ext in (None, "", [], {}):
            continue
        if not is_http(url) and not re.match(r"^[A-Za-z][\w.]{1,30}$", url):
            continue
        key = norm_url(url) if is_http(url) else f"{url.lower()}|{ext}"
        key = key + "|" + str(as_int(p.get("type"), 0))
        if key not in buckets:
            order.append(key)
            buckets[key] = dict(p)
            buckets[key]["_n"] = 1
        else:
            buckets[key]["_n"] += 1
            for k, v in p.items():
                if buckets[key].get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
                    buckets[key][k] = v
    # 被越多配置引用 = 越主流；同次数保持原始顺序
    idx = {k: i for i, k in enumerate(order)}
    keys = sorted(order, key=lambda k: (-buckets[k]["_n"], idx[k]))
    if limit:
        keys = keys[:limit]
    out = []
    for k in keys:
        p = buckets[k]
        p.pop("_n", None)
        out.append(p)
    return out


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]"}


def is_dead_local_url(url: str) -> bool:
    """源作者自己电脑上的本地代理（127.0.0.1:10079 / :3066 之类）对别人永远是死的。"""
    if not url:
        return False
    low = url.lower()
    if "127.0.0.1" in low or "localhost" in low or "0.0.0.0" in low or "[::1]" in low:
        return True
    if not is_http(url):
        return False
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return h in _LOOPBACK_HOSTS or h.startswith("127.")


def dedupe_lives(lives: list[dict]) -> list[dict]:
    """按 URL 去重直播源，并按「被多少个配置引用」排序（越主流越靠前）。"""
    seen: dict[str, dict] = {}
    cnt: dict[str, int] = {}
    for e in lives:
        url = str(e.get("url") or "")
        if not url or is_dead_local_url(url):
            continue
        key = norm_url(url) if is_http(url) else url
        if key in seen:
            cnt[key] = cnt.get(key, 1) + 1
            # 合并 logo/epg
            for k in ("logo", "epg", "ua", "referer"):
                if seen[key].get(k) in (None, "") and e.get(k):
                    seen[key][k] = e[k]
            continue
        cnt[key] = 1
        seen[key] = dict(e)
    keys = sorted(seen, key=lambda k: (-cnt[k], str(seen[k].get("name") or "")))
    return [seen[k] for k in keys]


def dedupe_channel_groups(groups: list[dict]) -> list[dict]:
    """按组名合并频道组，频道按名字 + urls 去重。"""
    merged: dict[str, dict] = {}
    for g in groups:
        name = str(g.get("group") or "直播")
        slot = merged.setdefault(name, {"group": name, "channels": []})
        by_chan = {c.get("name"): c for c in slot["channels"]}
        for c in g.get("channels") or []:
            cn = str(c.get("name") or "")
            if cn in by_chan:
                have = by_chan[cn]["urls"]
                for u in c.get("urls") or []:
                    if u not in have:
                        have.append(u)
            else:
                newc = {"name": cn, "urls": list(dict.fromkeys(c.get("urls") or []))}
                slot["channels"].append(newc)
                by_chan[cn] = newc
    # 丢掉只剩本地占位地址的频道
    for g in merged.values():
        keep = []
        for c in g["channels"]:
            urls = [u for u in c["urls"] if not is_dead_local_url(u)]
            if urls:
                c["urls"] = urls
                keep.append(c)
        g["channels"] = keep
    out = [g for g in merged.values() if g["channels"]]
    out.sort(key=lambda g: -len(g["channels"]))
    return out


# ------------------------------------------------------------------ 同接口收敛
_COLLECT_TYPES = (0, 1, 2, 5, 6, 7, 8)
# 同一个 api 被写成多种 type 时，优先保留「最通用/最可能可用」的那个
_TYPE_PREF = {1: 5, 0: 4, 6: 3, 2: 2, 7: 1, 5: 1, 8: 1}


def collapse_identical(records: list[SiteRecord]) -> tuple[list[SiteRecord], int]:
    """同一 (api, ext) 只保留一条。

    典型场景：同一个 py 脚本 / csp 类被不同配置写成 type 3 和 type 4，
    后端去重（按 type 分组）不会合并，但 TVBox 里会显示成两个一模一样的分组。
    """
    buckets: dict[tuple[str, str, str], list[SiteRecord]] = defaultdict(list)
    for r in records:
        api = str(r.data.get("api") or "")
        ext = r.data.get("ext")
        sig = "" if ext is None else json.dumps(ext, ensure_ascii=False, sort_keys=True)
        jar = str(r.data.get("jar") or "")
        buckets[(api, sig, jar)].append(r)

    out: list[SiteRecord] = []
    merged = 0
    for group in buckets.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda r: (
            -(r.alive or 0),
            -len(r.sources),
            -_TYPE_PREF.get(as_int(r.data.get("type"), 3), 0),
            len(str(r.data.get("name") or "")),
        ))
        keep = group[0]
        srcs = set(keep.sources)
        for r in group[1:]:
            srcs |= set(r.sources)
            merged += 1
        keep.sources = sorted(srcs)
        out.append(keep)

    order = {id(r): i for i, r in enumerate(records)}
    out.sort(key=lambda r: order.get(id(r), 0))
    return out, merged


def collapse_by_api(records: list[SiteRecord]) -> tuple[list[SiteRecord], int]:
    """采集站按 api（canon 后）再收敛一次：同一接口只保留一条，避免同名源刷屏。

    豆瓣/采集站的 api 相同但 type 写成 0/1/6 的极多，TVBox 里会显示成多个重复条目。
    保留优先级：已探活 > 引用次数 > type 偏好 > 名称短。
    """
    from .model import canon_api
    buckets: dict[str, list[SiteRecord]] = defaultdict(list)
    passthrough: list[SiteRecord] = []
    for r in records:
        t = as_int(r.data.get("type"), 3)
        api = str(r.data.get("api") or "")
        if t in _COLLECT_TYPES and is_http(api):
            buckets[canon_api(api)].append(r)
        else:
            passthrough.append(r)
    out = list(passthrough)
    merged = 0
    for key, group in buckets.items():
        if len(group) == 1:
            out.extend(group)
            continue
        group.sort(key=lambda r: (
            -(r.alive or 0),
            -len(r.sources),
            -_TYPE_PREF.get(as_int(r.data.get("type"), 3), 0),
            len(str(r.data.get("name") or "")),
        ))
        keep = group[0]
        # 把被合并者的引用来源并进去，方便溯源
        srcs = set(keep.sources)
        for r in group[1:]:
            srcs |= set(r.sources)
        keep.sources = sorted(srcs)
        out.append(keep)
        merged += len(group) - 1
    return out, merged


# ------------------------------------------------------------------ 统计
def dup_stats(sites: list[dict]) -> dict:
    n = len(sites)
    by_backend = len({site_backend_id(s) for s in sites})
    by_exact = len({site_dedupe_id(s) for s in sites})
    by_key = len({str(s.get("key")) for s in sites})
    by_name = len({norm_name(s.get("name", "")) for s in sites})
    by_sig = len({site_signature(s) for s in sites})
    return {
        "total": n,
        "unique_by_backend": by_backend,
        "unique_by_exact": by_exact,
        "unique_by_key": by_key,
        "unique_by_name": by_name,
        "unique_by_signature": by_sig,
        "dup_rate_backend": round(1 - by_backend / n, 4) if n else 0,
        "dup_rate_key": round(1 - by_key / n, 4) if n else 0,
    }
