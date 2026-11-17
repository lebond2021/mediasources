# TVBox 媒体源聚合报告

生成时间：2026-11-17 21:33 ｜ 工作目录：`C:\Users\Nick\Documents\tvbox`

## 1. 一句话结论

从 **6594** 个可解析配置中抓到 **630,031** 条站点条目，按后端指纹去重后剩 **7,201** 个独立站点，其中严格可用（爬虫类名可解析 + 未判死）**4,509** 个，最终合成一份 `index.json`（1679 KB），在 TVBox 里填一条链接即可加载全部源。

## 2. 关键数字

| 指标 | 数值 |
| --- | --- |
| 候选 URL（种子 + 发现） | 8,001 |
| 实际抓取成功（HTTP 200 且可解析） | 6,804 / 8,001 |
| 文档类型分布 | config 4407、store 1532、fail 1197、unknown 618、text 236、live 11 |
| 原始站点条目 | 630,031 |
| 去重后独立站点（全部） | 70,504 |
| 主配置站点数 | 4,509 |
| 按后端去重率 | 88.6% |
| 按 key 去重率 | 93.9% |
| 名称消歧 / key 冲突修正 | 2328 / 2138 |
| 探测：活 / 死 / 未测 | 2,473 / 2,736 / 2,471 |
| 全局 spider | `https://gh-proxy.com/https://raw.githubusercontent.com/gaotianliuyun/gao/master/jar/pg.jar` |
| strict 剔除（爬虫类名缺失） | 2,826 |
| 直播源（去重后） | 43,220 |
| 解析器（parses） | 200 |
| 多仓来源 | 4,407 |

## 3. 产物清单

| 文件 | 站点数 | 体积 | 说明 |
| --- | --- | --- | --- |
| `index.json` | 4509 | 1679 KB | 主配置（严格 + 探测，日常填这个） |
| `index_all.json` | 68928 | 30380 KB | 全量（不做 strict-spider 过滤） |
| `index_lite.json` | 300 | 413 KB | 精简 300 站，低配盒子用 |
| `index_collect.json` | 1819 | 895 KB | 只要采集站（不依赖 jar） |
| `index_spider.json` | 5163 | 2049 KB | 只要 csp 爬虫站（已配站点级 jar） |
| `index_lives.json` | - | 6 KB | 直播源全量（含频道分组） |
| `storehouse.json` | 4407 | 662 KB | 多仓：每个来源一条 |
| `stats.json` | - | 9 KB | 统计原始数据 |
| `sources.json` | - | 1627 KB | 每个来源 URL 的状态 |

## 4. 站点类型分布（主配置）

| type | 含义 | 数量 |
| --- | --- | --- |
| 3 | csp 爬虫 | 3,683 |
| 1 | json 采集 | 506 |
| 4 | csp 爬虫(ext) | 218 |
| 0 | xml 采集 | 88 |
| 8 | xml 采集 | 11 |
| 2 | json 扩展采集 | 2 |
| 6 | xml 采集(嵌套) | 1 |

## 5. 站点来源 Top 20（按域名）

- `gh-proxy.org` — 690
- `raw.githubusercontent.com` — 141
- `gh-proxy.com` — 132
- `ghfast.top` — 83
- `catbox.n13.club` — 78
- `clun.top` — 67
- `play.iptv365.org` — 35
- `mpimg.cn` — 34
- `7337.kstore.vip` — 22
- `jsnz.pages.dev` — 21
- `lytvs.top` — 21
- `daili.korice.eu.org` — 19
- `gh.halonice.com` — 18
- `qist.wyfc.qzz.io` — 17
- `androidcatvodspider.pages.dev` — 16
- `gitee.com` — 15
- `fastly.jsdelivr.net` — 14
- `ghproxy.com` — 14
- `qu.ax` — 14
- `cdn.jsdelivr.net` — 14

## 6. 数据来源

1. 4 个指定仓库：`noimank/tvbox`、`25175/tvyuan`、`qist/tvbox`、`cliya/TVBox`（完整审阅见 `docs/repo-audit.md`）。
2. GitHub 搜索 + 选择性拉取：73 个仓库，只 checkout `.json/.txt/.m3u`，见 `tools/gh_pull.py`。
3. 互联网侦察：4677 条经 HTTP 200 验证的源地址，见 `seeds/web_sources.txt` 与 `docs/recon-web.md`。
4. BFS 抓取：配置内 `storeHouse`/`urls`、列表页 `data-url`/`href`、纯文本清单。

## 7. 发布链接

- **点播主链接**：https://raw.githubusercontent.com/lebond2021/mediasources/dist/index.json（4509 站）
- 点播镜像：https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index.json
- **直播主链接**：https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_lives.json（8 条）
  - 直播镜像 pomf2.lain.la：https://pomf2.lain.la/f/dcdls81s.json
  - 直播镜像 kappa.lol：https://kappa.lol/JtqqX6
  - 直播镜像 raw(仅供点播加载器)：https://raw.githubusercontent.com/lebond2021/mediasources/dist/index_lives.json
  - 注意：直播加载器要求配置 JSON 的 Content-Type 是 application/json（raw 返回 text/plain 会被静默忽略）；而它会把 m3u 总表当 JS 模块解析，jsDelivr 对 .m3u 返回 audio/x-mpegurl 会报 evaluateModule 错误，所以总表用 .txt（text/plain）。lives[0] 指向我们自己合并去重后的总频道表。
- 变体 index_lite.json（300 站精简）：https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_lite.json
- 变体 storehouse.json（多仓）：https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/storehouse.json
- 变体 index_all.json（全量）：https://raw.githubusercontent.com/lebond2021/mediasources/dist/index_all.json
- 变体 index_lives_grouped.json（频道组）：https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_lives_grouped.json

## 8. 复现

```powershell
py -m tvh all            # discover → crawl → build
py tools/validate.py --all
py tools/report.py
py tools/publish.py --to catbox
```
