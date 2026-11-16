"""流水线入口：discover / crawl / build / all。"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import re
import sys
import time
from collections import defaultdict

from . import __version__
from .dedupe import (collapse_by_api, dedupe_channel_groups, dedupe_lives,
                     dedupe_parses, dedupe_sites, disambiguate_names, dup_stats,
                     fix_keys)
from .extract import (extract_from_page, extract_jar_urls, github_tree,
                      guess_repo_from_url, raw_url_for, scan_repo)
from .http import Fetcher
from .merge import (build_config, merge_globals, stats_of, store_house, write_json)
from .model import TYPE_NAMES, site_backend_id
from .parse import parse_document
from .spider import resolve_spiders
from .util import absolutize, as_int, host_of, is_http, loads_json, norm_url
from .verify import Prober

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "state")
CACHE = os.path.join(DATA, "cache")
DIST = os.path.join(ROOT, "dist")
SEEDS = os.path.join(ROOT, "seeds")
SOURCES_DIR = os.path.join(ROOT, "sources")


def log(*a):
    print(*a, flush=True)


def _seed_files() -> list[str]:
    out = []
    if not os.path.isdir(SEEDS):
        return out
    for fn in sorted(os.listdir(SEEDS)):
        if fn.endswith((".txt", ".list")):
            out.append(os.path.join(SEEDS, fn))
    return out


def load_seed_urls() -> list[str]:
    urls: list[str] = []
    for p in _seed_files():
        try:
            for line in open(p, encoding="utf-8", errors="replace"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 允许 "URL<TAB>名称" / "名称 URL" 混合格式
                m = re.search(r"https?://[^\s\t]+", line)
                if m:
                    urls.append(m.group().rstrip(".,;）)】"))
        except Exception:
            continue
    return list(dict.fromkeys(urls))


# --------------------------------------------------------------------- discover
def cmd_discover(args) -> int:
    os.makedirs(STATE, exist_ok=True)
    found: dict[str, dict] = {}

    def add(url: str, name: str = "", origin: str = ""):
        if not url or not is_http(url):
            return
        u = url.strip()
        if u not in found:
            found[u] = {"url": u, "name": name or u, "origin": origin}

    seeds = load_seed_urls()
    log(f"  种子 URL: {len(seeds)}")
    for u in seeds:
        add(u, origin="seed")

    # 本地仓库
    if os.path.isdir(SOURCES_DIR):
        for repo in sorted(os.listdir(SOURCES_DIR)):
            p = os.path.join(SOURCES_DIR, repo)
            if not os.path.isdir(p):
                continue
            entries, urls = scan_repo(p)
            log(f"  仓库 {repo}: 本地配置 {len(entries)} 个, 文本链接 {len(urls)} 条")
            for e in entries:
                if e.get("url"):
                    add(e["url"], e["name"], f"repo:{repo}")
                add_local = e
            for u in urls:
                add(u, origin=f"repo:{repo}")

    # GitHub 仓库树（可选，需 --github）
    if args.github:
        token = os.environ.get("GITHUB_TOKEN", "")
        repos = []
        for u in list(found.keys()):
            g = guess_repo_from_url(u)
            if g:
                repos.append(g)
        for fn in _seed_files():
            for line in open(fn, encoding="utf-8", errors="replace"):
                g = guess_repo_from_url(line)
                if g:
                    repos.append(g)
        repos = list(dict.fromkeys(repos))
        log(f"  GitHub 仓库枚举: {len(repos)} 个")
        for owner, repo in repos:
            files = github_tree(owner, repo, token=token)
            if files:
                log(f"    {owner}/{repo}: {len(files)} 个文件")
            for f in files:
                add(f, origin=f"gh:{owner}/{repo}")

    write_json(os.path.join(STATE, "urls_seed.json"),
               sorted(found.values(), key=lambda x: x["url"]))
    log(f"  发现候选 URL: {len(found)}  → data/state/urls_seed.json")
    return 0


# ------------------------------------------------------------------------ crawl
def _url_score(u: str) -> int:
    """抓取优先级：配置类链接优先，图片/二进制垫底。"""
    s = (u or "").lower()
    score = 0
    if s.endswith(".json"):
        score += 6
    elif s.endswith((".txt", ".m3u", ".m3u8")):
        score += 3
    if any(k in s for k in ("tvbox", "tbox", "config", "/api", "spider", "yingshi", "ys")):
        score += 3
    if any(k in s for k in ("raw.githubusercontent", "gitee.com", "jsdelivr", "gitlab")):
        score += 2
    if any(k in s for k in (".png", ".jpg", ".gif", ".apk", ".jar", ".zip", ".so", ".mp4")):
        score -= 8
    if "clbug.com" in s or "user.php" in s:
        score += 1
    return score


def cmd_crawl(args) -> int:
    os.makedirs(STATE, exist_ok=True)
    seed_path = os.path.join(STATE, "urls_seed.json")
    seeds = []
    if os.path.exists(seed_path):
        seeds = [e["url"] for e in json.load(open(seed_path, encoding="utf-8"))]
    if not seeds:
        seeds = load_seed_urls()
    log(f"  待抓取: {len(seeds)} (max_urls={args.max_urls}, depth={args.depth})")

    fetcher = Fetcher(cache_dir=CACHE, timeout=args.timeout, retries=1,
                      per_host=args.per_host, cache_ttl=args.cache_ttl, verbose=args.verbose)
    docs = []
    seen: set[str] = set()
    queued: set[str] = set()
    url_status: dict[str, dict] = {}
    deadline = time.time() + args.budget if args.budget else None

    local_entries = []
    if os.path.isdir(SOURCES_DIR):
        for repo in sorted(os.listdir(SOURCES_DIR)):
            p = os.path.join(SOURCES_DIR, repo)
            if os.path.isdir(p):
                e, _ = scan_repo(p)
                local_entries.extend(e)

    # ---- 先吃本地文件（省流量、百分百可解析）
    for e in local_entries:
        try:
            txt = open(e["local"], encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        doc = parse_document(e.get("url") or f"file://{e['local']}", txt)
        doc.globals["_local"] = e["local"]
        doc.globals["_name"] = e["name"]
        url_status[doc.url] = {"status": 200, "kind": doc.kind, "sites": len(doc.sites),
                               "parses": len(doc.parses), "lives": len(doc.lives),
                               "error": doc.error, "origin": "local"}
        if doc.kind in ("config", "store", "live"):
            docs.append(doc)
    log(f"  本地配置解析成功: {len(docs)}")

    i = 0
    seq = 0
    heap: list = []
    MAX_KIDS = 80
    BATCH = max(8, args.workers)

    def push(url: str, depth: int, parent: str = "") -> None:
        nonlocal seq
        nu = norm_url(url)
        if not nu or nu in seen or nu in queued:
            return
        queued.add(nu)
        seq += 1
        heapq.heappush(heap, (depth, -_url_score(url), seq, url, parent))

    for u in seeds:
        push(u, 0)

    jar_pool: set[str] = set()

    while heap and len(seen) < args.max_urls:
        if deadline and time.time() > deadline:
            log("  达到时间预算，提前结束抓取")
            break
        # 一轮取一批，批量并发抓，兼顾优先级与吞吐
        batch: list[tuple[int, str, str]] = []
        while heap and len(batch) < BATCH and len(seen) + len(batch) < args.max_urls:
            depth, _, _, url, parent = heapq.heappop(heap)
            nu = norm_url(url)
            if nu in seen:
                continue
            seen.add(nu)
            batch.append((depth, url, parent))
        if not batch:
            break
        i += len(batch)
        if i % 50 < BATCH:
            log(f"    进度 {i} / 队列 {len(heap)} / 文档 {len(docs)}")
        results = fetcher.get_many([u for _, u, _ in batch], workers=BATCH,
                                   use_cache=args.use_cache, cache_ttl=args.cache_ttl)
        for (depth, url, parent), r in zip(batch, results):
            if not r.ok:
                url_status[url] = {"status": r.status, "error": r.error or f"http-{r.status}",
                                   "kind": "fail"}
                continue
            doc = parse_document(url, r.text)
            url_status[url] = {"status": r.status, "kind": doc.kind, "sites": len(doc.sites),
                               "parses": len(doc.parses), "lives": len(doc.lives),
                               "error": doc.error, "ms": r.elapsed_ms}
            if doc.kind in ("config", "store", "live"):
                docs.append(doc)
            for j in extract_jar_urls(r.text)[:40]:
                jar_pool.add(j)
            # 列表页 / 文本源：继续抽取（限流，避免队列爆炸）
            if doc.kind in ("store", "text") or (doc.kind == "unknown" and "<" in r.text[:200]):
                kids = extract_from_page(r.text, url) if "<" in r.text[:400] else []
                kids += [c["url"] for c in doc.children]
                if depth < args.depth:
                    kids = sorted(dict.fromkeys(kids), key=lambda u: -_url_score(u))[:MAX_KIDS]
                    for k in kids:
                        push(k, depth + 1, url)
            # 配置里内嵌的下一级配置（type 10 / 站点指向 json）
            if doc.kind == "config":
                for c in doc.children:
                    push(c["url"], depth + 1, url)
                if depth < args.depth:
                    for s in doc.sites:
                        api = str(s.get("api") or "")
                        if s.get("type") in (10,) and is_http(api) and api.lower().endswith((".json", ".txt")):
                            push(api, depth + 1, url)

    log(f"  抓取完成: 请求 {len(url_status)} 个 URL, 有效文档 {len(docs)}")
    log(f"  抓取统计: {fetcher.stats}")
    if jar_pool:
        write_json(os.path.join(STATE, "jars.json"), sorted(jar_pool))
        log(f"  发现 spider jar 链接 {len(jar_pool)} 个")

    # 落盘：只保留必要字段，压缩体积
    payload = []
    for d in docs:
        payload.append({
            "url": d.url, "kind": d.kind,
            "sites": d.sites, "parses": d.parses, "lives": d.lives,
            "channel_groups": d.channel_groups, "globals": d.globals,
            "children": d.children,
        })
    write_json(os.path.join(STATE, "docs.json"), payload)
    write_json(os.path.join(STATE, "url_status.json"), url_status)
    log(f"  → data/state/docs.json ({len(payload)} 文档)")
    return 0


# ------------------------------------------------------------------------ build
def load_docs() -> list[dict]:
    p = os.path.join(STATE, "docs.json")
    if not os.path.exists(p):
        log("  !! 没有 docs.json，先跑 crawl")
        return []
    return json.load(open(p, encoding="utf-8"))


def _local_remote_base(local_path: str) -> str:
    """本地配置文件 → 它在 GitHub/Gitee 上的 raw URL，用于正确改写相对路径。"""
    try:
        p = os.path.abspath(local_path or "")
        rel = os.path.relpath(p, SOURCES_DIR)
        parts = rel.split(os.sep)
        if len(parts) < 2 or parts[0] == "..":
            return ""
        repo_dir = os.path.join(SOURCES_DIR, parts[0])
        return raw_url_for(repo_dir, "/".join(parts[1:])) or ""
    except Exception:
        return ""


def cmd_build(args) -> int:
    t0 = time.time()
    docs = load_docs()
    if not docs:
        return 1
    log(f"  载入文档 {len(docs)}")

    cfg_docs = [d for d in docs if d.get("kind") == "config"]
    all_sites, all_parses, all_lives, all_groups = [], [], [], []
    spider_refs: dict[str, int] = defaultdict(int)
    globals_list: list[dict] = []

    for d in docs:
        src = d.get("url") or ""
        base = src
        # 本地文件用 raw url 作来源名，并用它在 GitHub 上的地址当 base 改写相对路径
        if d["globals"].get("_local"):
            base = _local_remote_base(d["globals"]["_local"]) or base
        if d["globals"].get("_name"):
            src = f"{d['globals']['_name']}"
        for s in d.get("sites") or []:
            s = dict(s)
            for k in ("api", "ext", "jar"):
                if k in s:
                    s[k] = absolutize(s.get(k), base)
            s["_src"] = src
            all_sites.append(s)
        all_parses.extend(d.get("parses") or [])
        all_lives.extend(d.get("lives") or [])
        all_groups.extend(d.get("channel_groups") or [])
        for g in [d.get("globals") or {}]:
            globals_list.append(g)
            sp = g.get("spider")
            if isinstance(sp, str) and is_http(sp):
                spider_refs[sp] += 1
        for s in d.get("sites") or []:
            jar = s.get("jar")
            if isinstance(jar, str) and is_http(jar):
                spider_refs[jar] += 1

    # 抓取阶段在列表页/README 里发现的 jar 也纳入候选
    jp = os.path.join(STATE, "jars.json")
    if os.path.exists(jp):
        try:
            for j in json.load(open(jp, encoding="utf-8")):
                spider_refs.setdefault(j, 1)
        except Exception:
            pass

    log(f"  原始站点条目: {len(all_sites)}, 解析: {len(all_parses)}, 直播: {len(all_lives)}")
    st = dup_stats(all_sites)
    log(f"  去重前统计: 总 {st['total']} | 按后端 {st['unique_by_backend']} | "
        f"按 key {st['unique_by_key']} | 按名 {st['unique_by_name']} | "
        f"key 去重率 {st['dup_rate_key']:.1%} 后端去重率 {st['dup_rate_backend']:.1%}")

    records = dedupe_sites(all_sites, profile=args.profile)
    log(f"  后端去重后: {len(records)} 个站点")

    # spider jar：① 选全局最优 ② 给每个 csp 站点分配「真正包含该类」的 jar
    spider_url = args.spider or ""
    spider_report = {}
    class_jar: dict[str, str] = {}
    csp_names = {str(r.data.get("api"))[4:].strip() for r in records
                 if str(r.data.get("api", "")).lower().startswith("csp_")}
    csp_names.discard("")
    if spider_refs and csp_names:
        fetcher = Fetcher(cache_dir=CACHE, timeout=args.timeout, retries=0, per_host=4)
        log(f"  候选 spider jar {len(spider_refs)} 个, csp 类名 {len(csp_names)} 个，"
            f"评估覆盖率（top {args.jar_top}）…")
        sel = resolve_spiders(fetcher, dict(spider_refs), csp_names,
                              top=args.jar_top, verbose=True)
        spider_url = spider_url or sel["chosen"]
        spider_report = sel
        class_jar = sel["class_jar"]
        log(f"  全局 spider: {spider_url or '(无)'}")
        log(f"  类名可解析: {sel['covered']}/{sel['total_names']}"
            f"（覆盖 {len(set(class_jar.values()))} 个不同 jar）")

    records_all = list(records)

    # 主配置只取「被多个独立配置引用过」的主流站点 + 全部采集站，避免被某个类的上万条变体淹没
    def _is_collect(r) -> bool:
        return as_int(r.data.get("type"), -1) in (0, 1, 2, 5, 6, 7, 8)

    main_records = [r for r in records
                    if len(r.sources) >= args.min_refs or _is_collect(r)]
    # 同类 csp 限流，保证类型多样性
    if args.per_class_cap:
        seen_cls: dict[str, int] = defaultdict(int)
        capped = []
        for r in sorted(main_records, key=lambda x: -len(x.sources)):
            api = str(r.data.get("api") or "").lower()
            if api.startswith("csp_"):
                cls = api.split("|")[0]
                if seen_cls[cls] >= args.per_class_cap:
                    continue
                seen_cls[cls] += 1
            capped.append(r)
        main_records = capped
    log(f"  主配置候选（引用≥{args.min_refs} 或采集站）: {len(main_records)} 站")

    dropped_csp = 0
    jar_assigned = 0
    if class_jar:
        # ① 给所有站点按类名挂站点级 jar
        for r in records_all:
            api = str(r.data.get("api") or "")
            if api.lower().startswith("csp_"):
                jar = class_jar.get(api[4:].strip())
                if jar and jar != spider_url:
                    r.data["jar"] = jar
                    jar_assigned += 1
        # ② 主配置里剔除类名无人实现的 csp 站（strict-spider）
        if not getattr(args, "no_strict_spider", False):
            keep = []
            for r in main_records:
                api = str(r.data.get("api") or "")
                if api.lower().startswith("csp_") and not class_jar.get(api[4:].strip()):
                    dropped_csp += 1
                    continue
                keep.append(r)
            main_records = keep
        log(f"  站点级 jar 覆盖 {jar_assigned} 个; strict-spider 剔除无法解析的 csp "
            f"{dropped_csp} 个 → 主配置候选 {len(main_records)} 站")

    # 探测（只探主配置候选，几十万条全量探测不现实）
    probe_stats = {}
    if not args.no_verify:
        fetcher = Fetcher(cache_dir=CACHE, timeout=args.timeout, retries=0,
                          per_host=args.per_host, cache_ttl=args.cache_ttl)
        prober = Prober(fetcher, state_path=os.path.join(STATE, "health.json"), ttl=args.health_ttl)
        log(f"  探测 {len(main_records)} 个站点可用性…")
        probe_stats = prober.probe_many(main_records, workers=args.workers)
        log(f"  探测结果: 活 {probe_stats['alive']} / 死 {probe_stats['dead']} / 未测 {probe_stats['unknown']}")

    records = main_records
    api_merged = 0
    if not args.no_api_collapse:
        records, api_merged = collapse_by_api(records)
        log(f"  同接口收敛 {api_merged} 条 → 主配置 {len(records)} 站")
        records_all, _ = collapse_by_api(records_all)

    changed = disambiguate_names(records)
    keyfix = fix_keys(records)
    log(f"  名称消歧 {changed} 条, key 冲突修正 {keyfix} 条")

    parses = dedupe_parses(all_parses, limit=args.parses_limit)
    parses_all = dedupe_parses(all_parses, limit=args.parses_all_limit)
    lives = dedupe_lives(all_lives)
    lives_all = lives[:args.lives_all_limit] if args.lives_all_limit else lives
    groups = dedupe_channel_groups(all_groups)
    g = merge_globals(globals_list)

    # 输出
    os.makedirs(DIST, exist_ok=True)
    main_lives = lives[:args.lives_limit] if args.lives_limit else lives
    main = build_config(records, parses, main_lives, None, g, spider=spider_url,
                        drop_dead=not args.keep_dead, limit=args.limit)
    write_json(os.path.join(DIST, "index.json"), main)

    lite = build_config(records, parses, main_lives, None, g, spider=spider_url,
                        drop_dead=True, limit=args.lite_limit)
    write_json(os.path.join(DIST, "index_lite.json"), lite)

    # 全量档：不做 strict-spider 过滤，保证「所有可获得源」都在
    full = build_config(records_all, parses_all, lives_all, None, g, spider=spider_url,
                        drop_dead=False, limit=0)
    write_json(os.path.join(DIST, "index_all.json"), full)

    collect_only = [r for r in records if r.data.get("type") in (0, 1)]
    spider_only = [r for r in records if r.data.get("type") in (3, 4, 9, 10, 11)]
    write_json(os.path.join(DIST, "index_collect.json"),
               build_config(collect_only, parses, [], [], g, spider=spider_url, drop_dead=False))
    write_json(os.path.join(DIST, "index_spider.json"),
               build_config(spider_only, parses, [], [], g, spider=spider_url, drop_dead=False))

    # 频道组格式（影视仓/新版 FongMi）单独一份，不影响主配置兼容性
    if groups:
        write_json(os.path.join(DIST, "index_lives.json"),
                   build_config(records, parses, [], groups, g, spider=spider_url,
                                drop_dead=not args.keep_dead, limit=args.limit))

    # 多仓：可用的子源
    ok_sources = []
    us = json.load(open(os.path.join(STATE, "url_status.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(STATE, "url_status.json")) else {}
    for u, s in us.items():
        if s.get("kind") == "config" and s.get("status") == 200:
            h = host_of(u) or u
            ok_sources.append({"name": f"{h} ({s.get('sites', 0)}站)", "url": u})
    ok_sources.sort(key=lambda x: -int(re.sub(r"\D", "", x["name"].rsplit("(", 1)[-1]) or 0))
    write_json(os.path.join(DIST, "storehouse.json"), store_house(ok_sources))

    write_json(os.path.join(DIST, "stats.json"),
               {**stats_of(records, len(docs), len(us), len(parses), len(lives), t0),
                "probe": probe_stats,
                "spider": {"chosen": spider_url,
                           "strict_dropped": dropped_csp,
                           "report": spider_report.get("report", [])},
                "dup": {**st, "names_fixed": changed, "keys_fixed": keyfix},
                "raw_sites": len(all_sites),
                "sites_full": len(records_all), "sites_main": len(main["sites"]),
                "channel_groups": len(groups)})
    write_json(os.path.join(DIST, "sources.json"), us)

    log(f"  输出: index.json {len(main['sites'])} 站 | index_all.json {len(full['sites'])} 站 | "
        f"lite {len(lite['sites'])} | 采集 {len(collect_only)} | 爬虫 {len(spider_only)} | "
        f"多仓 {len(ok_sources)}")
    log(f"  完成，用时 {time.time() - t0:.1f}s")
    return 0


# -------------------------------------------------------------------------- cli
def main(argv=None) -> int:
    ap = argparse.ArgumentParser("tvh", description="TVBox 媒体源聚合器")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="收集候选源 URL")
    d.add_argument("--github", action="store_true", help="用 GitHub API 枚举仓库文件树")

    c = sub.add_parser("crawl", help="抓取并解析所有源")
    c.add_argument("--max-urls", type=int, default=1200)
    c.add_argument("--depth", type=int, default=2)
    c.add_argument("--timeout", type=float, default=15)
    c.add_argument("--per-host", type=int, default=6)
    c.add_argument("--workers", type=int, default=48, help="并发抓取数")
    c.add_argument("--cache-ttl", type=int, default=1800)
    c.add_argument("--budget", type=int, default=1800, help="抓取时间预算（秒）")
    c.add_argument("--no-cache", dest="use_cache", action="store_false")
    c.add_argument("--verbose", action="store_true")

    b = sub.add_parser("build", help="去重、探测并生成最终配置")
    b.add_argument("--profile", default="backend", choices=["backend", "exact", "key"])
    b.add_argument("--timeout", type=float, default=8)
    b.add_argument("--per-host", type=int, default=4)
    b.add_argument("--workers", type=int, default=96)
    b.add_argument("--cache-ttl", type=int, default=1800)
    b.add_argument("--health-ttl", type=int, default=6 * 3600)
    b.add_argument("--jar-top", type=int, default=30)
    b.add_argument("--spider", default="", help="强制指定 spider jar")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--min-refs", type=int, default=5,
                   help="主配置只收「被≥N个独立配置引用」的站点（采集站不受限）")
    b.add_argument("--parses-limit", type=int, default=200,
                   help="主配置保留多少条解析器（按被引用次数排序）")
    b.add_argument("--parses-all-limit", type=int, default=800,
                   help="全量档保留多少条解析器")
    b.add_argument("--lives-all-limit", type=int, default=3000,
                   help="全量档保留多少条直播源")
    b.add_argument("--no-api-collapse", action="store_true",
                   help="不按 api 收敛同一采集接口的多种 type 重复条目")
    b.add_argument("--per-class-cap", type=int, default=80,
                   help="同一 csp 类在主配置里最多保留几条（0=不限）")
    b.add_argument("--lives-limit", type=int, default=300,
                   help="主配置里保留多少条直播源（全量见 index_lives.json）")
    b.add_argument("--lite-limit", type=int, default=300)
    b.add_argument("--keep-dead", action="store_true")
    b.add_argument("--no-verify", action="store_true")
    b.add_argument("--no-strict-spider", action="store_true",
                   help="不剔除类名不在 jar 内的 csp 站点")

    a = sub.add_parser("all", help="discover+crawl+build")
    a.add_argument("--github", action="store_true")
    a.add_argument("--max-urls", type=int, default=1200)
    a.add_argument("--depth", type=int, default=2)
    a.add_argument("--budget", type=int, default=1800)
    a.add_argument("--workers", type=int, default=64)
    a.add_argument("--per-host", type=int, default=8)
    a.add_argument("--timeout", type=float, default=8)
    a.add_argument("--no-verify", action="store_true")
    a.add_argument("--keep-dead", action="store_true")
    a.add_argument("--verbose", action="store_true")

    args = ap.parse_args(argv)
    os.makedirs(DATA, exist_ok=True)
    log(f"== TVBox 聚合器 v{__version__} | {args.cmd} ==")

    if args.cmd == "discover":
        return cmd_discover(args)
    if args.cmd == "crawl":
        return cmd_crawl(args)
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "all":
        ns = argparse.Namespace(github=args.github, verbose=args.verbose)
        cmd_discover(ns)
        ns2 = argparse.Namespace(max_urls=args.max_urls, depth=args.depth, timeout=15,
                                 per_host=args.per_host, cache_ttl=1800, budget=args.budget,
                                 use_cache=True, verbose=args.verbose)
        cmd_crawl(ns2)
        # 直接复用 build 子命令的默认值，避免新增参数后 Namespace 缺字段
        ns3 = b.parse_args([])
        ns3.timeout = args.timeout
        ns3.workers = args.workers
        ns3.no_verify = args.no_verify
        ns3.keep_dead = args.keep_dead
        return cmd_build(ns3)
    return 2


if __name__ == "__main__":
    sys.exit(main())
