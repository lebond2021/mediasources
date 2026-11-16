"""数据模型与「同一后端」身份判定。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from .util import as_int, is_http, norm_name, norm_url, sha1

# TVBox 站点的 type 语义（社区通用约定 + FongMi/CatVod 实现）
TYPE_NAMES = {
    0: "xml采集",
    1: "json采集",
    2: "xml自定义",
    3: "csp爬虫",
    4: "csp接口",
    5: "json扩展",
    6: "xml扩展",
    7: "json聚合",
    8: "xml聚合",
    9: "csp聚合",
    10: "js/本地",
    11: "js",
}

# 允许「只看 api」判定为同一后端的 type
COLLECT_TYPES = {0, 1, 2, 5, 6, 7, 8}

SITE_FIELDS_ALWAYS = ("key", "name", "type", "api", "searchable", "quickSearch", "filterable")
SITE_FIELDS_OPT = ("ext", "jar", "playerType", "categories", "changeable", "timeout",
                   "headers", "extend", "playUrl", "clickSelector", "clickPlay", "style",
                   "hide", "poster", "logo", "searchUrl", "detailUrl", "homepage")


def _json_stable(v: Any) -> str:
    try:
        return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(v)


# 采集站 API 的无意义差异：查询参数、输出格式后缀、尾斜杠、www 前缀、协议
_DROP_PARAMS = {"ac", "wd", "ids", "pg", "t", "at", "pagesize", "limit", "page"}
_FMT_SUFFIX = re.compile(r"/(?:at/(?:json|xml)|json|xml|index\.php)/?$", re.I)


def canon_api(api: str) -> str:
    """把同一个 CMS 后端的各种写法归一：协议/端口/www/输出格式/查询参数都不算差异。

    http://360zy.com/api.php/provide/vod/?ac=list
    https://360zy.com/api.php/provide/vod/at/json
    -> 360zy.com/api.php/provide/vod
    """
    if not is_http(api):
        return api
    try:
        p = urlsplit(api.strip())
    except ValueError:
        return api.strip().lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", p.path or "")
    path = _FMT_SUFFIX.sub("", path)
    if len(path) > 1:
        path = path.rstrip("/")
    try:
        pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if k.lower() not in _DROP_PARAMS]
    except Exception:
        pairs = []
    pairs.sort()
    q = urlencode(pairs, doseq=True, safe="/:@")
    return f"{host}{path}" + (f"?{q}" if q else "")


def site_backend_id(s: dict) -> str:
    """站点「后端」身份：同一后端无论换名字/换 key 都视为同一站点。

    规则：
      - api 是 http URL  -> 采集/api 型，身份 = (type, canon_api)
      - api 以 csp_ 开头 -> csp 爬虫，身份 = (type, api, 归一化 ext)
      - 其它（js://、空 api、包名类） -> (type, api, ext 指纹, 归一化 name)
    """
    t = as_int(s.get("type"), -1)
    api = (s.get("api") or "")
    api = api.strip() if isinstance(api, str) else _json_stable(api)
    ext = s.get("ext")

    if is_http(api):
        return f"h|{t}|{canon_api(api)}"

    if api.lower().startswith("csp_"):
        if isinstance(ext, str) and is_http(ext):
            e = norm_url(ext)
        elif ext in (None, "", [], {}):
            e = ""
        else:
            e = sha1(_json_stable(ext))[:16]
        return f"c|{t}|{api.lower()}|{e}"

    if api.lower().startswith(("js:", "js/")):
        return f"j|{t}|{api}"

    if not api:
        if isinstance(ext, str) and is_http(ext):
            return f"e|{t}|{norm_url(ext)}"
        if ext not in (None, "", [], {}):
            return f"e|{t}|{sha1(_json_stable(ext))[:16]}"
        return f"n|{t}|{norm_name(s.get('name', ''))}"

    return f"m|{t}|{api}|{sha1(_json_stable(ext))[:12] if ext not in (None, '', [], {}) else ''}"


def site_dedupe_id(s: dict) -> str:
    """严格去重身份：后端 + ext 变体。用于 dedupe_profile=exact。"""
    base = site_backend_id(s)
    ext = s.get("ext")
    if ext not in (None, "", [], {}) and not is_http(str(ext)):
        return base + "|" + sha1(_json_stable(ext))[:16]
    return base


def site_signature(s: dict) -> str:
    """整条站点的内容签名（用于识别完全相同的条目）。"""
    return sha1(_json_stable({k: v for k, v in s.items() if not k.startswith("_")}))


def site_sort_rank(s: dict) -> tuple:
    """合并时代表条目的优选排序（越小越优）：字段更全、名字更干净、有 ext 的优先。"""
    filled = sum(1 for k in SITE_FIELDS_ALWAYS + SITE_FIELDS_OPT
                 if s.get(k) not in (None, "", [], {}))
    name = str(s.get("name") or "")
    dirty = 1 if re.search(r"[\[\]【】]|x{2,}|测试|备用|失效|广告", name, re.I) else 0
    return (-filled, dirty, len(name), name)


# --------------------------------------------------------------------- 解析
_M3U_LINE = re.compile(r"^#EXTINF:.*?,(.*)$")


def parse_lives(raw: Any) -> tuple[list[dict], list[dict]]:
    """把各种形态的直播配置摊平成 TVBox lives 数组 + 频道组。

    返回 (lives_entries, channel_groups)
      lives_entries:  [{name, url, group, ua, epg, logo, ...}]  —— 直接可用的直播源
      channel_groups: [{group, channels:[{name, urls:[...]}]}] —— 新格式频道组
    """
    flat: list[dict] = []
    groups: list[dict] = []

    def norm_entry(e: dict) -> dict | None:
        if not isinstance(e, dict):
            return None
        url = e.get("url") or e.get("api") or ""
        if isinstance(url, list):
            url = url[0] if url else ""
        if not isinstance(url, str) or not url.strip():
            return None
        out = dict(e)
        out["url"] = url.strip()
        out.setdefault("name", out.get("group") or "直播")
        return out

    def walk(node: Any, depth: int = 0):
        if depth > 4 or node is None:
            return
        if isinstance(node, str):
            s = node.strip()
            if is_http(s) and (s.endswith((".txt", ".m3u", ".m3u8")) or "/live" in s):
                flat.append({"name": "直播", "url": s, "group": "直播"})
            return
        if isinstance(node, list):
            for x in node:
                walk(x, depth + 1)
            return
        if not isinstance(node, dict):
            return
        # 频道组新格式
        if "channels" in node and isinstance(node["channels"], list):
            chans = []
            for c in node["channels"]:
                if not isinstance(c, dict):
                    continue
                urls = c.get("urls") or c.get("url") or []
                if isinstance(urls, str):
                    urls = [urls]
                urls = [u for u in urls if isinstance(u, str) and u.strip()]
                if urls:
                    chans.append({"name": c.get("name") or "", "urls": urls})
                    for i, u in enumerate(urls):
                        flat.append({"name": f"{c.get('name') or ''}#{i + 1}",
                                     "url": u.strip(), "group": node.get("group") or "直播"})
            if chans:
                groups.append({"group": node.get("group") or "直播", "channels": chans})
                return
        e = norm_entry(node)
        if e:
            flat.append(e)
            return
        for key in ("lives", "data", "urls", "list", "groups", "channels"):
            if key in node:
                walk(node[key], depth + 1)

    walk(raw)
    return flat, groups


def parse_parses(raw: Any) -> list[dict]:
    out: list[dict] = []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return out
    for p in raw:
        if not isinstance(p, dict):
            continue
        url = p.get("url") or p.get("api") or ""
        if not isinstance(url, str) or not url.strip():
            # 有些解析只有 ext（本地解析器名）
            if p.get("ext") or p.get("name"):
                q = dict(p)
                q["url"] = ""
                out.append(q)
            continue
        q = dict(p)
        q["url"] = url.strip()
        q.setdefault("name", "解析")
        q.setdefault("type", 1)
        out.append(q)
    return out


def parse_sites(raw: Any) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for s in raw:
        if not isinstance(s, dict):
            continue
        if "api" not in s and "ext" not in s:
            continue
        q = dict(s)
        q["key"] = str(q.get("key") or q.get("api") or q.get("name") or "")
        q["name"] = str(q.get("name") or q["key"])
        q["type"] = as_int(q.get("type"), -1)
        if "api" not in q:
            q["api"] = ""
        out.append(q)
    return out


# ------------------------------------------------------------------ 记录类
@dataclass
class ParsedDoc:
    url: str
    kind: str = "unknown"          # config | store | live | unknown
    sites: list[dict] = field(default_factory=list)
    parses: list[dict] = field(default_factory=list)
    lives: list[dict] = field(default_factory=list)
    channel_groups: list[dict] = field(default_factory=list)
    globals: dict = field(default_factory=dict)
    children: list[dict] = field(default_factory=list)   # [{name,url}]
    error: str = ""
    raw_len: int = 0


@dataclass
class SiteRecord:
    backend_id: str
    data: dict
    sources: list[str] = field(default_factory=list)
    variants: int = 1
    alive: int = -1                # 1 活 / 0 死 / -1 未测
    latency_ms: int = -1
    note: str = ""

    @property
    def site_type(self) -> int:
        return as_int(self.data.get("type"), -1)
