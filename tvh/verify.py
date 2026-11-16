"""可用性探测：采集站真请求 ac=list 校验结构；csp 站以 ext 可达性代理；其它宽松判定。"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .http import Fetcher, Result
from .model import SiteRecord
from .util import as_int, is_http, norm_url

XML_HINT = re.compile(r"<\?xml|<rss|<list\b|<video|<class>", re.I)
JSON_HINT = re.compile(r'"(list|class|vod_id|vod_name)"\s*:')


def _join(api: str, params: str) -> str:
    return api.rstrip("/") + ("&" if "?" in api else "?") + params


class Prober:
    def __init__(self, fetcher: Fetcher, *, state_path: str | None = None,
                 ttl: int = 6 * 3600, verbose: bool = False):
        self.f = fetcher
        self.state_path = state_path
        self.ttl = ttl
        self.verbose = verbose
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
        if state_path and os.path.exists(state_path):
            try:
                with open(state_path, encoding="utf-8") as fp:
                    self._state = json.load(fp)
            except Exception:
                self._state = {}

    # ---------------------------------------------------------------- state
    def _cached(self, key: str):
        e = self._state.get(key)
        if not e:
            return None
        if time.time() - e.get("ts", 0) > self.ttl:
            return None
        return e

    def _save(self, key: str, alive: int, latency: int, note: str):
        with self._lock:
            self._state[key] = {"alive": alive, "latency": latency, "note": note, "ts": time.time()}

    def flush(self):
        if not self.state_path:
            return
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp = self.state_path + ".tmp"
        with self._lock:
            data = {k: v for k, v in self._state.items()
                    if time.time() - v.get("ts", 0) < self.ttl * 4}
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    # ---------------------------------------------------------------- probe
    def probe_site(self, rec: SiteRecord) -> SiteRecord:
        s = rec.data
        t = as_int(s.get("type"), -1)
        api = str(s.get("api") or "")
        ext = s.get("ext")
        key = f"site:{norm_url(api) if is_http(api) else api}|{t}|{str(ext)[:80]}"

        cached = self._cached(key)
        if cached:
            rec.alive, rec.latency_ms, rec.note = cached["alive"], cached["latency"], cached["note"]
            return rec

        alive, lat, note = self._probe_one(t, api, ext)
        rec.alive, rec.latency_ms, rec.note = alive, lat, note
        self._save(key, alive, lat, note)
        return rec

    def _probe_one(self, t: int, api: str, ext) -> tuple[int, int, str]:
        # 1) 采集站：真搜一次
        if t in (0, 1, 2, 5, 6, 7, 8) and is_http(api):
            r = self.f.get(_join(api, "ac=list"), use_cache=False)
            body = (r.text or "")[:6000]
            if r.status == 200 and body:
                if t == 0 and XML_HINT.search(body):
                    return 1, r.elapsed_ms, "xml-ok"
                if t in (1, 5, 7) and JSON_HINT.search(body):
                    return 1, r.elapsed_ms, "json-ok"
                if t == 0 and JSON_HINT.search(body):
                    return 1, r.elapsed_ms, "xml-api-json-ok"
                if len(body) > 200 and ("<" in body or "{" in body):
                    return 1, r.elapsed_ms, "loose-ok"
                # 再看裸 api
                r2 = self.f.get(api, use_cache=False)
                if r2.status == 200 and len(r2.text or "") > 100:
                    return 1, r2.elapsed_ms, "root-ok"
                return 0, r.elapsed_ms, "empty-list"
            if r.status in (404, 410):
                return 0, r.elapsed_ms, f"http-{r.status}"
            if r.error:
                return 0, r.elapsed_ms, "net-err"
            return 0, r.elapsed_ms, f"http-{r.status}"

        # 2) csp 爬虫：ext 可达性
        if t in (3, 4, 9):
            if isinstance(ext, str) and is_http(ext):
                r = self.f.get(ext, use_cache=False)
                if r.status == 200 and len(r.text or "") > 20:
                    return 1, r.elapsed_ms, "ext-ok"
                return (0, r.elapsed_ms, f"ext-http-{r.status}") if r.status else (0, r.elapsed_ms, "ext-net-err")
            if isinstance(ext, dict) and ext:
                return 1, -1, "ext-inline"
            if str(s := api).lower().startswith("csp_"):
                return -1, -1, "csp-jar"
            return -1, -1, "unknown"

        # 3) js / 本地
        if t in (10, 11):
            if is_http(api):
                r = self.f.get(api, use_cache=False)
                return (1, r.elapsed_ms, "js-ok") if r.status == 200 else (0, r.elapsed_ms, f"js-http-{r.status}")
            return -1, -1, "js-local"

        if is_http(api):
            r = self.f.get(api, use_cache=False)
            return (1 if r.status == 200 else 0), r.elapsed_ms, f"http-{r.status}"
        return -1, -1, "unknown"

    def probe_many(self, records: list[SiteRecord], workers: int = 48) -> dict:
        todo = [r for r in records]
        done = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(self.probe_site, r) for r in todo]
            for fut in futures:
                try:
                    fut.result()
                except Exception:
                    pass
                done += 1
                if self.verbose and done % 50 == 0:
                    print(f"      探测 {done}/{len(todo)}  {time.time() - t0:.0f}s")
        self.flush()
        stats = {"alive": 0, "dead": 0, "unknown": 0}
        for r in records:
            stats["alive" if r.alive == 1 else "dead" if r.alive == 0 else "unknown"] += 1
        return stats
