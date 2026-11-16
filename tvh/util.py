"""通用工具：URL 归一化、脏 JSON 修复、base64、名称归一化、哈希。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

# 归一化时丢弃的跟踪参数（保留对内容有意义的参数）
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "share_token", "ref", "referer",
}

DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443"}


def strip_bom(s: str) -> str:
    return s.lstrip("\ufeff\ufffe").strip()


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm_url(u: str, *, keep_query: bool = True, sort_query: bool = True) -> str:
    """URL 归一化：小写 scheme/host、去默认端口、折叠重复斜杠、去跟踪参数、去 fragment。

    用于「同一后端」判定。不改变路径大小写（部分站点路径区分大小写）。
    """
    if not u:
        return ""
    u = u.strip()
    if u.startswith("//"):
        u = "http:" + u
    try:
        p = urlsplit(u)
    except ValueError:
        return u.lower()
    if not p.scheme and not p.netloc:
        return u
    scheme = (p.scheme or "http").lower()
    try:
        host = (p.hostname or "").lower()
    except ValueError:
        host = ""
    if not host:
        return u
    try:
        port = p.port
    except ValueError:
        port = None
    netloc = host
    if port and str(port) != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    if p.username:
        netloc = f"{p.username}@{netloc}"
    path = re.sub(r"/{2,}", "/", p.path or "")
    if len(path) > 1:
        path = path.rstrip("/")
    query = p.query
    if keep_query and query:
        try:
            pairs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                     if k.lower() not in TRACKING_PARAMS]
        except Exception:
            pairs = []
        if sort_query:
            pairs.sort()
        query = urlencode(pairs, doseq=True, safe="/:@")
    else:
        query = ""
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(u: str) -> str:
    try:
        return (urlsplit(u).hostname or "").lower()
    except ValueError:
        return ""


def is_http(u: str) -> bool:
    return isinstance(u, str) and u.lower().startswith(("http://", "https://"))


REL_PATH_RE = re.compile(r"^(?:\.{0,2}/)?[\w\-.%~/+]+\.(?:js|json|py|txt|jar|m3u|m3u8|xml|php|html?)$", re.I)
_MD5_TAIL = re.compile(r"^(.*?)(;(?:md5|pk);[A-Za-z0-9+/=]+)$", re.I)


def absolutize(v, base: str):
    """把配置里的相对路径（`./lib/drpy2.min.js`、`lib/x.jar`）解析成绝对 URL。

    这些路径相对于「配置自身所在的仓库/目录」，聚合时必须改写，否则跨源合并后必失效。
    """
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s or is_http(s) or s.startswith(("csp_", "py_", "js://", "py://", "assets://",
                                            "file://", "clan://", "data:", "//")):
        return v
    # 形如 `./jar/x.jar;md5;ABCD`：分离校验后缀，只解析前半段
    tail = ""
    m = _MD5_TAIL.match(s)
    if m:
        s, tail = m.group(1), m.group(2)
    if not REL_PATH_RE.match(s):
        return v
    if not base or not is_http(base):
        return v
    try:
        return urljoin(base, s) + tail
    except Exception:
        return v


def safe_url(u: str) -> str:
    """把含中文域名/空格/未编码字符的 URL 变成 requests 能吃的形式。"""
    if not is_http(u):
        return u
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return u.strip()
    host = p.netloc
    # 中文域名 -> punycode
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        try:
            host = host.encode("idna").decode("ascii")
        except Exception:
            host = quote(host, safe=":[]{}-._~")
    path = quote(p.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(p.query, safe="/%:@!$&'()*+,;=-._~?")
    return urlunsplit((p.scheme, host, path, query, ""))


# ---------------------------------------------------------------- 名称归一化
_NAME_STRIP = re.compile(
    r"[\s\u3000\-_·•\|/,，。:：;；!！?？()（）\[\]【】{}<>《》\"'`~@#$%^&*+=]")


def norm_name(n: str) -> str:
    """名称归一化，用于「同名站点」聚类。处理全角、大小写、标点、常见装饰前缀。"""
    if not isinstance(n, str):
        return ""
    s = unicodedata.normalize("NFKC", n).lower()
    # 去掉 [xxx] 之类的来源/延迟标记
    s = re.sub(r"[\[【（(][^\]】）)]{0,20}(?:ms|kb/s|mb/s|测速|源|可用|失效)[^\]】）)]{0,10}[\]】）)]", "", s)
    s = re.sub(r"[\[【（(]\s*\d+\s*[\]】）)]", "", s)
    s = _NAME_STRIP.sub("", s)
    # HD/4K 之类的画质后缀不参与区分
    s = re.sub(r"(4k|8k|hd|fhd|uhd|蓝光|超清|高清|原画|抢先版?)$", "", s)
    return s.strip()


# ---------------------------------------------------------------- 脏 JSON 修复
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_UNQUOTED_KEY = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]{0,40})\s*:')


def repair_json_text(raw: str) -> str:
    s = strip_bom(raw)
    # 去掉 JS 注释（但不要破坏 http:// 里的 //）
    s = re.sub(r"(?<![:\"])//[^\n\"']*$", "", s, flags=re.M)
    s = _BLOCK_COMMENT.sub("", s)
    s = _TRAILING_COMMA.sub(r"\1", s)
    s = s.replace("\u00a0", " ")
    return s


def loads_json(raw: str, _depth: int = 0):
    """尽最大努力解析 JSON，返回 (obj, how)。"""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty"
    raw = strip_bom(raw)
    for how, text in (("strict", raw), ("repaired", repair_json_text(raw))):
        try:
            return json.loads(text, strict=False), how
        except Exception:
            pass
    # 截取最外层 {} 或 []
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = raw.find(opener), raw.rfind(closer)
        if 0 <= i < j:
            seg = repair_json_text(raw[i:j + 1])
            try:
                return json.loads(seg, strict=False), "sliced"
            except Exception:
                pass
    # JSON Lines：每行一个对象
    if _depth == 0 and "\n" in raw:
        lines = [ln for ln in raw.splitlines() if ln.strip().startswith("{")]
        if 1 < len(lines) <= 5000:
            objs = []
            for ln in lines:
                o, _ = loads_json(ln, _depth + 1)
                if isinstance(o, dict):
                    objs.append(o)
            if objs:
                return objs, "jsonl"
    return None, "unparseable"


# ---------------------------------------------------------------- base64
_B64_RE = re.compile(r"^[A-Za-z0-9+/\-_=\s]{16,}$")


def try_b64(raw: str) -> str | None:
    """若文本像 base64 编码的 JSON，解码后返回字符串。"""
    s = strip_bom(raw)
    if not s or not _B64_RE.match(s):
        return None
    compact = re.sub(r"\s+", "", s)
    if len(compact) < 16:
        return None
    pad = "=" * (-len(compact) % 4)
    for alt in (compact.replace("-", "+").replace("_", "/"), compact):
        for candidate in (alt + pad, alt):
            try:
                dec = base64.b64decode(candidate, validate=False)
            except (binascii.Error, ValueError):
                continue
            try:
                txt = dec.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "{" in txt[:200] or "[" in txt[:200]:
                return txt
    return None


def deep_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return default
    return cur if cur is not None else default


def as_int(v, default=-1):
    try:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            return int(v.strip())
    except Exception:
        pass
    return default


def human(n: int) -> str:
    for unit in ("", "K", "M", "G"):
        if abs(n) < 1000:
            return f"{n:.0f}{unit}" if unit == "" else f"{n:.1f}{unit}"
        n /= 1000.0
    return f"{n:.1f}T"
