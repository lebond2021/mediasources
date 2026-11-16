# TVBox 媒体源聚合报告

生成时间：2026-11-16 20:14 ｜ 工作目录：`C:\Users\Nick\Documents\tvbox`

## 1. 一句话结论

从 **6705** 个可解析配置中抓到 **635,231** 条站点条目，按后端指纹去重后剩 **7,363** 个独立站点，其中严格可用（爬虫类名可解析 + 未判死）**4,664** 个，最终合成一份 `index.json`（2181 KB），在 TVBox 里填一条链接即可加载全部源。

## 2. 关键数字

| 指标 | 数值 |
| --- | --- |
| 候选 URL（种子 + 发现） | 8,001 |
| 实际抓取成功（HTTP 200 且可解析） | 6,863 / 8,001 |
| 文档类型分布 | config 4437、store 1613、fail 1138、unknown 560、text 242、live 11 |
| 原始站点条目 | 635,231 |
| 去重后独立站点（全部） | 71,235 |
| 主配置站点数 | 4,664 |
| 按后端去重率 | 88.6% |
| 按 key 去重率 | 93.9% |
| 名称消歧 / key 冲突修正 | 2376 / 2222 |
| 探测：活 / 死 / 未测 | 2,523 / 2,752 / 2,564 |
| 全局 spider | `https://gh-proxy.com/https://raw.githubusercontent.com/gaotianliuyun/gao/master/jar/pg.jar` |
| strict 剔除（爬虫类名缺失） | 2,848 |
| 直播源（去重后） | 43,928 |
| 解析器（parses） | 200 |
| 多仓来源 | 4,437 |

## 3. 产物清单

| 文件 | 站点数 | 体积 | 说明 |
| --- | --- | --- | --- |
| `index.json` | 4664 | 2181 KB | 主配置（严格 + 探测，日常填这个） |
| `index_all.json` | 69676 | 30783 KB | 全量（不做 strict-spider 过滤） |
| `index_lite.json` | 300 | 547 KB | 精简 300 站，低配盒子用 |
| `index_collect.json` | 1827 | 1015 KB | 只要采集站（不依赖 jar） |
| `index_spider.json` | 5327 | 2217 KB | 只要 csp 爬虫站（已配站点级 jar） |
| `index_lives.json` | 4664 | 7953 KB | 直播源全量（含频道分组） |
| `storehouse.json` | 4437 | 677 KB | 多仓：每个来源一条 |
| `stats.json` | - | 9 KB | 统计原始数据 |
| `sources.json` | - | 1641 KB | 每个来源 URL 的状态 |

## 4. 站点类型分布（主配置）

| type | 含义 | 数量 |
| --- | --- | --- |
| 3 | csp 爬虫 | 3,829 |
| 1 | json 采集 | 511 |
| 4 | csp 爬虫(ext) | 219 |
| 0 | xml 采集 | 92 |
| 8 | xml 采集 | 11 |
| 6 | xml 采集(嵌套) | 2 |

## 5. 站点来源 Top 20（按域名）

- `gh-proxy.org` — 690
- `raw.githubusercontent.com` — 141
- `gh-proxy.com` — 129
- `ghfast.top` — 83
- `catbox.n13.club` — 78
- `clun.top` — 67
- `ghproxy.net` — 56
- `8877.kstore.space` — 38
- `mpimg.cn` — 36
- `play.iptv365.org` — 35
- `7337.kstore.vip` — 22
- `jsnz.pages.dev` — 21
- `lytvs.top` — 21
- `daili.korice.eu.org` — 19
- `gh.halonice.com` — 18
- `qist.wyfc.qzz.io` — 17
- `gitee.com` — 16
- `androidcatvodspider.pages.dev` — 16
- `ghproxy.com` — 14
- `qu.ax` — 14

## 6. 数据来源

1. 4 个指定仓库：`noimank/tvbox`、`25175/tvyuan`、`qist/tvbox`、`cliya/TVBox`（完整审阅见 `docs/repo-audit.md`）。
2. GitHub 搜索 + 选择性拉取：73 个仓库，只 checkout `.json/.txt/.m3u`，见 `tools/gh_pull.py`。
3. 互联网侦察：4677 条经 HTTP 200 验证的源地址，见 `seeds/web_sources.txt` 与 `docs/recon-web.md`。
4. BFS 抓取：配置内 `storeHouse`/`urls`、列表页 `data-url`/`href`、纯文本清单。

## 7. 发布链接

- **主链接（一条搞定）**：https://pomf2.lain.la/f/zsfi987w.json
- 镜像 pomf2.lain.la：https://pomf2.lain.la/f/zsfi987w.json
- 镜像 kappa.lol：https://kappa.lol/zkTeVG
- 镜像 uguu.se(3h)：https://d.uguu.se/LAGmdmWzBMSX.json
- 变体 index_lite.json(300站)：https://pomf2.lain.la/f/vg4v8foi.json
- 变体 index_lite.json 镜像：https://kappa.lol/O9XT67
- 变体 storehouse.json(多仓)：https://pomf2.lain.la/f/9bxmppiy.json
- 变体 storehouse.json 镜像：https://kappa.lol/3jUWxg

## 8. 复现

```powershell
py -m tvh all            # discover → crawl → build
py tools/validate.py --all
py tools/report.py
py tools/publish.py --to catbox
```
