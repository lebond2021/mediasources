"""源发现：本地仓库扫描、GitHub/GitLab 仓库内文件枚举、列表页/README 抽取。"""
from __future__ import annotations

import os
import re
import subprocess
from html import unescape
from urllib.parse import urljoin, urlsplit

from .parse import extract_config_urls_from_text
from .util import is_http, loads_json

JSONISH = (".json", ".txt", ".m3u", ".m3u8")
JAR_RE = re.compile(r"""https?://[^\s"'<>\\]+?\.jar(?:;(?:md5|pk);[A-Za-z0-9+/=]+)?""", re.I)
DATA_URL_RE = re.compile(r"""data-url\s*=\s*["']([^"']+)["']""", re.I)
HREF_RE = re.compile(r"""(?:href|src|content|value)\s*=\s*["']([^"']+)["']""", re.I)
ANY_URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""")
SKIP_HOST_PARTS = ("github.com/", "githubusercontent.com", "gitlab.com", "gitee.com",
                   "jsdelivr.net", "unpkg.com", "npmjs.com", "w3.org", "schema.org")
CONFIG_NAME_HINT = re.compile(
    r"(tvbox|tbox|box|config|api|接口|源|site|vod|spider|json|仓库|多仓|store|线路|live|tv|影视)", re.I)


def _git(repo_dir: str, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, timeout=30)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def repo_remote(repo_dir: str) -> tuple[str, str]:
    url = _git(repo_dir, "remote", "get-url", "origin")
    branch = _git(repo_dir, "branch", "--show-current") or "main"
    return url, branch


def raw_url_for(repo_dir: str, rel_path: str) -> str:
    url, branch = repo_remote(repo_dir)
    rel_path = rel_path.replace("\\", "/")
    if not url:
        return ""
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{branch}/{rel_path}"
    m = re.search(r"gitlab\.com[:/](.+?)(?:\.git)?$", url)
    if m:
        return f"https://gitlab.com/{m.group(1)}/-/raw/{branch}/{rel_path}"
    return ""


def scan_repo(repo_dir: str, *, max_kb: int = 4096) -> tuple[list[dict], list[str]]:
    """扫描本地仓库：返回 (本地配置条目, 从 md/txt 抽到的 URL)。

    条目结构 {"local": 路径, "url": 对应线上 raw url 或 "", "name": 文件名}
    """
    entries: list[dict] = []
    found_urls: list[str] = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith((".git", "node_modules", "__pycache__"))]
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, repo_dir)
            low = fn.lower()
            try:
                if os.path.getsize(p) > max_kb * 1024:
                    continue
            except OSError:
                continue
            if low.endswith(".md"):
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                found_urls.extend(extract_config_urls_from_text(txt))
                found_urls.extend(DATA_URL_RE.findall(txt))
                continue
            if not low.endswith(JSONISH):
                continue
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            obj, _ = loads_json(txt)
            looks_cfg = isinstance(obj, dict) and any(
                k in obj for k in ("sites", "parses", "spider", "lives", "urls", "storeHouse"))
            looks_store = isinstance(obj, dict) and isinstance(obj.get("urls"), list)
            if not (looks_cfg or looks_store):
                continue
            entries.append({"local": p, "url": raw_url_for(repo_dir, rel),
                            "name": f"{os.path.basename(repo_dir)}/{rel}"})
    return entries, list(dict.fromkeys(u for u in found_urls if is_http(u)))


def extract_from_page(text: str, page_url: str) -> list[str]:
    """从 HTML/README 里抽候选配置 URL。"""
    out: list[str] = []
    for m in DATA_URL_RE.findall(text or ""):
        out.append(unescape(m.strip()))
    out.extend(extract_config_urls_from_text(text or ""))
    for m in HREF_RE.findall(text or ""):
        u = unescape(m.strip())
        if u.startswith(("http://", "https://")) and u.lower().endswith(JSONISH):
            out.append(u)
    res = []
    for u in out:
        if not u or u.startswith(("#", "javascript:", "mailto:")):
            continue
        u = urljoin(page_url, u) if not u.startswith("http") else u
        if is_http(u):
            res.append(u.rstrip(".,;\"'"))
    # 去重，保留顺序
    return list(dict.fromkeys(res))


def extract_jar_urls(text: str) -> list[str]:
    """从页面/配置里抽 spider jar 链接（含 `;md5;` 后缀的原样保留）。"""
    out = []
    for m in JAR_RE.findall(text or ""):
        u = m.strip().rstrip(".,;)")
        if is_http(u):
            out.append(u)
    return list(dict.fromkeys(out))


def github_tree(owner: str, repo: str, branch: str = "", session=None,
                token: str = "") -> list[str]:
    """通过 GitHub API 递归列出仓库文件（不 clone 也能拿全量 .json）。"""
    import requests

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "tvh-aggregator"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        if not branch:
            r = session.get(api, headers=headers, timeout=20) if session else requests.get(api, headers=headers, timeout=20)
            if r.status_code != 200:
                return []
            branch = r.json().get("default_branch", "main")
        r = session.get(f"{api}/git/trees/{branch}?recursive=1", headers=headers, timeout=30) \
            if session else requests.get(f"{api}/git/trees/{branch}?recursive=1", headers=headers, timeout=30)
        if r.status_code != 200:
            return []
        tree = r.json().get("tree") or []
        out = []
        for node in tree:
            if node.get("type") != "blob":
                continue
            path = node.get("path", "")
            if path.lower().endswith((".json", ".txt")) and node.get("size", 0) < 3_000_000:
                out.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}")
        return out
    except Exception:
        return []


def guess_repo_from_url(url: str) -> tuple[str, str] | None:
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", url or "")
    if m:
        return m.group(1), re.sub(r"\.git$", "", m.group(2))
    return None
