# TVBox 媒体源聚合报告

生成时间：2026-11-18 20:02 ｜ 工作目录：`C:\Users\Nick\Documents\tvbox`

## 1. 一句话结论

从 **6760** 个可解析配置中抓到 **644,567** 条站点条目，按后端指纹去重后剩 **7,238** 个独立站点，其中严格可用（爬虫类名可解析 + 未判死）**107** 个，最终合成一份 `index.json`（83 KB），在 TVBox 里填一条链接即可加载全部源。

## 2. 关键数字

| 指标 | 数值 |
| --- | --- |
| 候选 URL（种子 + 发现） | 8,001 |
| 实际抓取成功（HTTP 200 且可解析） | 6,903 / 8,001 |
| 文档类型分布 | config 4525、store 1581、fail 1098、unknown 555、text 232、live 10 |
| 原始站点条目 | 644,567 |
| 去重后独立站点（全部） | 71,875 |
| 主配置站点数 | 107 |
| 按后端去重率 | 88.7% |
| 按 key 去重率 | 94.0% |
| 名称消歧 / key 冲突修正 | 2336 / 2160 |
| 探测：活 / 死 / 未测 | 2,479 / 2,705 / 2,530 |
| 全局 spider | `https://gh-proxy.com/https://raw.githubusercontent.com/gaotianliuyun/gao/master/jar/pg.jar` |
| strict 剔除（爬虫类名缺失） | 2,819 |
| 直播源（去重后） | 43,122 |
| 解析器（parses） | 200 |
| 多仓来源 | 4,525 |

## 3. 产物清单

| 文件 | 站点数 | 体积 | 说明 |
| --- | --- | --- | --- |
| `index.json` | 107 | 83 KB | 主配置（严格 + 探测，日常填这个） |
| `index_all.json` | 70311 | 30943 KB | 全量（不做 strict-spider 过滤） |
| `index_lite.json` | 17 | 35 KB | 精简 300 站，低配盒子用 |
| `index_collect.json` | 1792 | 873 KB | 只要采集站（不依赖 jar） |
| `index_spider.json` | 5232 | 2064 KB | 只要 csp 爬虫站（已配站点级 jar） |
| `index_lives.json` | - | 6 KB | 直播源全量（含频道分组） |
| `storehouse.json` | 4525 | 695 KB | 多仓：每个来源一条 |
| `stats.json` | - | 9 KB | 统计原始数据 |
| `sources.json` | - | 1643 KB | 每个来源 URL 的状态 |

## 4. 站点类型分布（主配置）

| type | 含义 | 数量 |
| --- | --- | --- |
| 3 | csp 爬虫 | 90 |
| 1 | json 采集 | 17 |

## 5. 站点来源 Top 20（按域名）

- `ys.cxkjg.cn` — 3
- `www.lovedan.net` — 1
- `cfkua.wokaotianshi.eu.org` — 1
- `caiji.mgzyapi.com` — 1
- `ikunzy.vip` — 1
- `360zyzz.com` — 1
- `caiji.xgzyapi.com` — 1
- `api.changzhang.tv` — 1
- `www.ryzy5.tv` — 1
- `mujiziyuan00.com` — 1
- `www.qlys.cc` — 1
- `dy.7772888.xyz` — 1
- `api.ponyo.fun` — 1
- `cmsyun2.qijiyun.vip` — 1
- `2229527.xyz` — 1

## 6. 数据来源

1. 4 个指定仓库：`noimank/tvbox`、`25175/tvyuan`、`qist/tvbox`、`cliya/TVBox`（完整审阅见 `docs/repo-audit.md`）。
2. GitHub 搜索 + 选择性拉取：73 个仓库，只 checkout `.json/.txt/.m3u`，见 `tools/gh_pull.py`。
3. 互联网侦察：4677 条经 HTTP 200 验证的源地址，见 `seeds/web_sources.txt` 与 `docs/recon-web.md`。
4. BFS 抓取：配置内 `storeHouse`/`urls`、列表页 `data-url`/`href`、纯文本清单。

## 8. 复现

```powershell
py -m tvh all            # discover → crawl → build
py tools/validate.py --all
py tools/report.py
py tools/publish.py --to catbox
```
