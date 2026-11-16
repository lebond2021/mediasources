"""配置文档解析：识别 单仓配置 / 多仓 / 直播源 / 纯文本列表，并抽出子链接。"""
from __future__ import annotations

import re
from typing import Any

from .model import ParsedDoc, parse_lives, parse_parses, parse_sites
from .util import is_http, loads_json, try_b64

STORE_KEYS = ("urls", "storeHouse", "storehouse", "store", "repos", "sources", "list")
CHILD_URL_KEYS = ("url", "sourceUrl", "source", "api", "src", "link", "path")
CHILD_NAME_KEYS = ("name", "sourceName", "title", "label")

URL_RE = re.compile(r"https?://[^\s\"'<>\\^`{|}\[\]()（）,，]+")
CONFIG_HINT_KEYS = ("sites", "parses", "spider", "lives", "flags", "rules", "ijk", "ads")


def _children_from(node: Any, depth: int = 0) -> list[dict]:
    out: list[dict] = []
    if depth > 4:
        return out
    if isinstance(node, list):
        for x in node:
            out.extend(_children_from(x, depth + 1))
        return out
    if not isinstance(node, dict):
        return out
    url = ""
    for k in CHILD_URL_KEYS:
        v = node.get(k)
        if isinstance(v, str) and is_http(v):
            url = v
            break
    if url:
        name = ""
        for k in CHILD_NAME_KEYS:
            if isinstance(node.get(k), str) and node[k].strip():
                name = node[k].strip()
                break
        out.append({"name": name or url, "url": url})
        return out
    for k, v in node.items():
        if k in ("sites", "parses", "lives", "flags"):
            continue
        if isinstance(v, (list, dict)):
            out.extend(_children_from(v, depth + 1))
    return out


def is_store(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    if any(k in doc for k in CONFIG_HINT_KEYS):
        return False
    for k in STORE_KEYS:
        v = doc.get(k)
        if isinstance(v, list) and any(isinstance(x, dict) and any(
                isinstance(x.get(u), str) and is_http(x.get(u)) for u in CHILD_URL_KEYS) for x in v):
            return True
    return False


def parse_document(url: str, text: str) -> ParsedDoc:
    doc = ParsedDoc(url=url, raw_len=len(text or ""))
    if not text or not text.strip():
        doc.error = "empty body"
        return doc

    obj, how = loads_json(text)
    if obj is None:
        dec = try_b64(text)
        if dec:
            obj, how = loads_json(dec)
    if obj is None:
        # 纯文本列表：一行一个 URL
        urls = [u for u in URL_RE.findall(text) if is_http(u)]
        if urls:
            doc.kind = "text"
            doc.children = [{"name": u, "url": u} for u in dict.fromkeys(urls)]
            return doc
        doc.error = f"not json ({how})"
        return doc

    if isinstance(obj, list):
        kids = _children_from(obj)
        if kids:
            doc.kind = "store"
            doc.children = kids
            return doc
        doc.error = "json list without urls"
        return doc

    if not isinstance(obj, dict):
        doc.error = "json not object"
        return doc

    if is_store(obj):
        doc.kind = "store"
        for k in STORE_KEYS:
            if k in obj:
                doc.children.extend(_children_from(obj[k]))
        if not doc.children:
            doc.children = _children_from(obj)
        # 去重
        seen, kids = set(), []
        for c in doc.children:
            if c["url"] in seen:
                continue
            seen.add(c["url"])
            kids.append(c)
        doc.children = kids
        return doc

    # 直播源？
    if ("channels" in obj or "lives" in obj or "urls" in obj) and "sites" not in obj and "parses" not in obj:
        if "channels" in obj or ("lives" in obj and "spider" not in obj and "sites" not in obj):
            doc.kind = "live"
            doc.lives, doc.channel_groups = parse_lives(obj.get("lives") if "lives" in obj else obj)
            if doc.lives or doc.channel_groups:
                return doc

    has_any = any(k in obj for k in CONFIG_HINT_KEYS)
    if not has_any:
        doc.error = "no tvbox keys"
        return doc

    doc.kind = "config"
    doc.sites = parse_sites(obj.get("sites"))
    doc.parses = parse_parses(obj.get("parses"))
    if "lives" in obj:
        doc.lives, doc.channel_groups = parse_lives(obj["lives"])
    if isinstance(obj.get("lives"), str) and is_http(obj["lives"]):
        doc.lives.append({"name": "直播", "url": obj["lives"], "group": "直播"})
    doc.globals = {k: v for k, v in obj.items()
                   if k not in ("sites", "parses", "lives") and v not in (None, "", [], {})}
    # 配置里可能还内嵌了其它源（少见的嵌套多仓）
    extra = obj.get("urls")
    if isinstance(extra, list):
        doc.children = [c for c in _children_from(extra)]
    return doc


def extract_config_urls_from_text(text: str) -> list[str]:
    """从 README / HTML / 任何文本里抠出可能是配置的 URL。"""
    out = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:)）】\"'")
        if any(u.lower().endswith(ext) for ext in (".json", ".txt", ".m3u", ".m3u8", ".js", ".jar")):
            out.append(u)
    return list(dict.fromkeys(out))
