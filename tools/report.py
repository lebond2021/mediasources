"""根据 dist/ 产物生成聚合报告 docs/aggregation-report.md。"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
DOCS = os.path.join(ROOT, "docs")


def load(name, default=None):
    p = os.path.join(DIST, name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def kb(name) -> str:
    p = os.path.join(DIST, name)
    return f"{os.path.getsize(p) / 1024:.0f} KB" if os.path.exists(p) else "-"


def main() -> int:
    st = load("stats.json", {}) or {}
    idx = load("index.json", {}) or {}
    allc = load("index_all.json", {}) or {}
    lite = load("index_lite.json", {}) or {}
    lives = load("index_lives.json", {}) or {}
    store = load("storehouse.json", {}) or {}
    src = load("sources.json", {}) or {}
    pub = load("published.json", {})

    sites = idx.get("sites") or []
    types = Counter(s.get("type") for s in sites)
    hosts = Counter()
    for s in sites:
        api = str(s.get("api") or "")
        if api.startswith("http"):
            host = api.split("/")[2] if api.count("/") > 2 else api
            hosts[host.lower()] += 1

    kind_cnt = Counter(v.get("kind") for v in src.values())
    ok_cnt = sum(1 for v in src.values() if v.get("status") == 200)
    dup = st.get("dup") or {}
    probe = st.get("probe") or {}
    spider = st.get("spider") or {}

    lines = []
    A = lines.append
    A("# TVBox 媒体源聚合报告")
    A("")
    A(f"生成时间：{time.strftime('%Y-%m-%d %H:%M')} ｜ 工作目录：`{ROOT}`")
    A("")
    A("## 1. 一句话结论")
    A("")
    A(f"从 **{st.get('sources_crawled', 0)}** 个可解析配置中抓到 **{st.get('raw_sites', 0):,}** 条站点条目，"
      f"按后端指纹去重后剩 **{st.get('sites_total', 0):,}** 个独立站点，"
      f"其中严格可用（爬虫类名可解析 + 未判死）**{len(sites):,}** 个，"
      f"最终合成一份 `index.json`（{kb('index.json')}），在 TVBox 里填一条链接即可加载全部源。")
    A("")
    A("## 2. 关键数字")
    A("")
    A("| 指标 | 数值 |")
    A("| --- | --- |")
    A(f"| 候选 URL（种子 + 发现） | {st.get('urls_seen', 0):,} |")
    A(f"| 实际抓取成功（HTTP 200 且可解析） | {ok_cnt:,} / {len(src):,} |")
    A(f"| 文档类型分布 | " + "、".join(f"{k} {v}" for k, v in kind_cnt.most_common()) + " |")
    A(f"| 原始站点条目 | {st.get('raw_sites', 0):,} |")
    A(f"| 去重后独立站点（全部） | {st.get('sites_full', 0):,} |")
    A(f"| 主配置站点数 | {len(sites):,} |")
    A(f"| 按后端去重率 | {dup.get('dup_rate_backend', 0):.1%} |")
    A(f"| 按 key 去重率 | {dup.get('dup_rate_key', 0):.1%} |")
    A(f"| 名称消歧 / key 冲突修正 | {dup.get('names_fixed', '-')} / {dup.get('keys_fixed', '-')} |")
    A(f"| 探测：活 / 死 / 未测 | {probe.get('alive', 0):,} / {probe.get('dead', 0):,} / {probe.get('unknown', 0):,} |")
    A(f"| 全局 spider | `{spider.get('chosen') or '(无)'}` |")
    A(f"| strict 剔除（爬虫类名缺失） | {spider.get('strict_dropped', 0):,} |")
    A(f"| 直播源（去重后） | {st.get('lives', 0):,} |")
    A(f"| 解析器（parses） | {st.get('parses', 0):,} |")
    A(f"| 多仓来源 | {len(store.get('storeHouse') or []):,} |")
    A("")
    A("## 3. 产物清单")
    A("")
    A("| 文件 | 站点数 | 体积 | 说明 |")
    A("| --- | --- | --- | --- |")
    for name, desc in [
        ("index.json", "主配置（严格 + 探测，日常填这个）"),
        ("index_all.json", "全量（不做 strict-spider 过滤）"),
        ("index_lite.json", "精简 300 站，低配盒子用"),
        ("index_collect.json", "只要采集站（不依赖 jar）"),
        ("index_spider.json", "只要 csp 爬虫站（已配站点级 jar）"),
        ("index_lives.json", "直播源全量（含频道分组）"),
        ("storehouse.json", "多仓：每个来源一条"),
        ("stats.json", "统计原始数据"),
        ("sources.json", "每个来源 URL 的状态"),
    ]:
        obj = load(name, {}) or {}
        n = len(obj.get("sites") or []) if "sites" in obj else (
            len(obj.get("storeHouse") or []) if "storeHouse" in obj else "-")
        A(f"| `{name}` | {n} | {kb(name)} | {desc} |")
    A("")
    A("## 4. 站点类型分布（主配置）")
    A("")
    A("| type | 含义 | 数量 |")
    A("| --- | --- | --- |")
    names = {0: "xml 采集", 1: "json 采集", 2: "json 扩展采集", 3: "csp 爬虫", 4: "csp 爬虫(ext)",
             5: "json 采集(嵌套)", 6: "xml 采集(嵌套)", 7: "json 采集", 8: "xml 采集",
             9: "csp 爬虫", 10: "js 爬虫", 11: "js 爬虫"}
    for t, n in types.most_common():
        A(f"| {t} | {names.get(t, '其它')} | {n:,} |")
    A("")
    A("## 5. 站点来源 Top 20（按域名）")
    A("")
    for h, n in hosts.most_common(20):
        A(f"- `{h}` — {n}")
    A("")
    A("## 6. 数据来源")
    A("")
    A("1. 4 个指定仓库：`noimank/tvbox`、`25175/tvyuan`、`qist/tvbox`、`cliya/TVBox`（完整审阅见 `docs/repo-audit.md`）。")
    A("2. GitHub 搜索 + 选择性拉取：73 个仓库，只 checkout `.json/.txt/.m3u`，见 `tools/gh_pull.py`。")
    A("3. 互联网侦察：4677 条经 HTTP 200 验证的源地址，见 `seeds/web_sources.txt` 与 `docs/recon-web.md`。")
    A("4. BFS 抓取：配置内 `storeHouse`/`urls`、列表页 `data-url`/`href`、纯文本清单。")
    A("")
    if pub and (pub.get("vod") or pub.get("url")):
        A("## 7. 发布链接")
        A("")
        vod = pub.get("vod") or {}
        live = pub.get("live") or {}
        if vod:
            A(f"- **点播主链接**：{vod.get('primary')}（{vod.get('sites')} 站）")
            A(f"- 点播镜像：{vod.get('mirror')}")
        else:
            A(f"- **主链接（一条搞定）**：{pub['url']}")
        if live:
            A(f"- **直播主链接**：{live.get('primary')}（{live.get('lives')} 条）")
            for name, u in (live.get("mirrors") or {}).items():
                A(f"  - 直播镜像 {name}：{u}")
            if live.get("note"):
                A(f"  - 注意：{live['note']}")
        for name, u in (pub.get("mirrors") or {}).items():
            A(f"- 镜像 {name}：{u}")
        for name, u in (pub.get("variants") or {}).items():
            A(f"- 变体 {name}：{u}")
        A("")
    A("## 8. 复现")
    A("")
    A("```powershell")
    A("py -m tvh all            # discover → crawl → build")
    A("py tools/validate.py --all")
    A("py tools/report.py")
    A("py tools/publish.py --to catbox")
    A("```")

    os.makedirs(DOCS, exist_ok=True)
    out = os.path.join(DOCS, "aggregation-report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"→ {out}（{len(lines)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
