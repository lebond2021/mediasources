"""带缓存、重试、并发限速的 HTTP 抓取层。"""
from __future__ import annotations

import gzip
import io
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter

from .util import sha1

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "okhttp/3.12.0",
    "Dalvik/2.1.0 (Linux; U; Android 11; MI 9 Build/RKQ1.200826.002)",
]


@dataclass
class Result:
    url: str
    final_url: str = ""
    status: int = 0
    text: str = ""
    content: bytes = b""
    elapsed_ms: int = 0
    error: str = ""
    from_cache: bool = False
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.text or self.content) and not self.error

    def json(self):
        from .util import loads_json
        obj, how = loads_json(self.text)
        if obj is None:
            from .util import try_b64
            dec = try_b64(self.text)
            if dec:
                obj, how = loads_json(dec)
        return obj


class Fetcher:
    def __init__(self, cache_dir: str | None = None, timeout: float = 15.0,
                 retries: int = 2, per_host: int = 4, proxy: str | None = None,
                 cache_ttl: int = 3600, verbose: bool = False):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.retries = retries
        self.per_host = per_host
        self.proxy = proxy
        self.cache_ttl = cache_ttl
        self.verbose = verbose
        self._local = threading.local()
        self._host_sems: dict[str, threading.Semaphore] = {}
        self._host_lock = threading.Lock()
        self._stats = {"hit": 0, "miss": 0, "net": 0, "fail": 0}
        self._stats_lock = threading.Lock()
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------ internals
    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            s.trust_env = True
            self._local.s = s
        return s

    def _sem(self, host: str) -> threading.Semaphore:
        with self._host_lock:
            sem = self._host_sems.get(host)
            if sem is None:
                sem = threading.Semaphore(self.per_host)
                self._host_sems[host] = sem
            return sem

    def _cache_path(self, url: str) -> str | None:
        if not self.cache_dir:
            return None
        return os.path.join(self.cache_dir, sha1(url) + ".cache")

    def _cache_read(self, url: str, ttl: int | None) -> Result | None:
        p = self._cache_path(url)
        if not p or not os.path.exists(p):
            return None
        ttl = self.cache_ttl if ttl is None else ttl
        try:
            age = time.time() - os.path.getmtime(p)
            if ttl >= 0 and age > ttl:
                return None
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return None
        r = Result(url=url, final_url=d.get("final_url", url), status=d.get("status", 0),
                   text=d.get("text", ""), elapsed_ms=d.get("elapsed_ms", 0),
                   error=d.get("error", ""), headers=d.get("headers", {}), from_cache=True)
        return r

    def _cache_write(self, r: Result) -> None:
        p = self._cache_path(r.url)
        if not p or r.status != 200 or not r.text:
            return
        if len(r.text) > 8_000_000:
            return
        tmp = p + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"final_url": r.final_url, "status": r.status, "text": r.text,
                           "elapsed_ms": r.elapsed_ms, "error": r.error,
                           "headers": {k: v for k, v in list(r.headers.items())[:20]}},
                          f, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception:
            pass

    def _bump(self, k: str) -> None:
        with self._stats_lock:
            self._stats[k] = self._stats.get(k, 0) + 1

    @property
    def stats(self) -> dict:
        with self._stats_lock:
            return dict(self._stats)

    # ------------------------------------------------------------ public
    def get(self, url: str, *, use_cache: bool = True, cache_ttl: int | None = None,
            headers: dict | None = None, binary: bool = False,
            allow_redirects: bool = True) -> Result:
        from .util import host_of

        if not url:
            return Result(url=url, error="empty url")
        from .util import safe_url
        url = safe_url(url)
        if use_cache:
            cached = self._cache_read(url, cache_ttl)
            if cached is not None:
                self._bump("hit")
                return cached
        self._bump("miss")

        h = {"User-Agent": random.choice(UA_POOL), "Accept": "*/*",
             "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive"}
        if headers:
            h.update({k: v for k, v in headers.items() if v})
        last = Result(url=url)
        for attempt in range(self.retries + 1):
            t0 = time.time()
            sem = self._sem(host_of(url) or "?")
            with sem:
                try:
                    resp = self._session().get(url, headers=h, timeout=(6, self.timeout),
                                               allow_redirects=allow_redirects, stream=False,
                                               proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None)
                    raw = resp.content
                    enc = (resp.headers.get("Content-Encoding") or "").lower()
                    if enc == "gzip" or (raw[:2] == b"\x1f\x8b"):
                        try:
                            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                        except Exception:
                            pass
                    if binary:
                        text = ""
                    else:
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if "charset=gb" in ctype or "gbk" in ctype:
                            text = raw.decode("gb18030", errors="replace")
                        else:
                            try:
                                text = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                text = raw.decode("gb18030", errors="replace")
                    last = Result(url=url, final_url=resp.url, status=resp.status_code,
                                  text=text, content=raw,
                                  elapsed_ms=int((time.time() - t0) * 1000),
                                  headers=dict(resp.headers))
                    self._bump("net")
                except Exception as e:
                    last = Result(url=url, status=0, error=f"{type(e).__name__}: {e}"[:200],
                                  elapsed_ms=int((time.time() - t0) * 1000))
            if last.status and last.status < 400:
                break
            if last.status in (401, 403, 404, 410, 451):
                break  # 不值得重试
            if attempt < self.retries:
                time.sleep(0.4 + 0.6 * attempt + random.random() * 0.4)
        if not last.ok:
            self._bump("fail")
        elif use_cache:
            self._cache_write(last)
        if self.verbose:
            print(f"    GET {last.status:>3} {last.elapsed_ms:>6}ms {url[:110]} {last.error}")
        return last

    def get_many(self, urls: Iterable[str], *, workers: int = 32, **kw) -> list[Result]:
        urls = [u for u in dict.fromkeys(urls) if u]
        out: list[Result] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(self.get, u, **kw): u for u in urls}
            for i, (fut, u) in enumerate(list(futures.items())):
                try:
                    out.append(fut.result())
                except Exception as e:
                    out.append(Result(url=u, error=str(e)[:120]))
        return out

    def get_binary(self, url: str, *, use_cache: bool = True, cache_ttl: int = 86400 * 7) -> Result:
        return self.get(url, use_cache=use_cache, cache_ttl=cache_ttl, binary=True)
