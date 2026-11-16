# TVBox 媒体源聚合器（tvh）

把全网可获得的 TVBox / 影视仓 / OK影视 配置接口抓下来，做**结构化去重、爬虫（jar）归属、可用性探测**，
最后合成**一条配置链接**——用户只要在 TVBox 里填这一个地址，就等于同时加载了所有源。

```
seeds/*.txt ──┐
sources/*     ├─► discover ─► crawl ─► build ─► dist/index.json ─► 发布成一条链接
GitHub 搜索 ──┘                            │
                                           ├─ dist/index_all.json     全量（不筛爬虫）
                                           ├─ dist/index_lite.json    精简（300 站，最稳）
                                           ├─ dist/index_collect.json 纯采集站
                                           ├─ dist/index_spider.json  纯 csp 爬虫站
                                           ├─ dist/index_lives.json   直播源（含频道分组）
                                           ├─ dist/storehouse.json    多仓（每仓库一条）
                                           └─ dist/stats.json         统计
```

## 1. 快速开始

```powershell
# 0) 依赖：Python 3.9+（本机用 py 启动），无需 pip 安装
py -m tvh all                 # 一条龙：发现 → 抓取 → 构建
py -m tvh all --no-verify     # 不探测可用性，10 秒出结果
py tools/serve.py             # 起本地服务，打印可填进 TVBox 的链接
py tools/validate.py --all    # 结构校验
py tools/publish.py           # 上传到公共图床/文件床，拿到公网链接
```

单步：

```powershell
py -m tvh discover            # 汇总种子 + 扫描本地仓库 → data/state/urls_seed.json
py -m tvh crawl --max-urls 4000 --budget 1200
py -m tvh build --no-verify
```

## 2. 数据从哪来

| 来源 | 说明 |
| --- | --- |
| `seeds/seed_curated.txt` | 手写核心种子（qist、tvyuan、cliya、noimank、liu673cn、gaotianliuyun 等） |
| `seeds/seed_from_collectors.txt` | 从 `25175/tvyuan` 的 `sources.txt` 与各仓库 README 抽取（147 条） |
| `seeds/web_sources.txt` | 互联网侦察得到的聚合站/接口（recon 子任务产出） |
| `sources/*` | 选择性拉取的 GitHub 仓库（只取 .json/.txt/.m3u，不整仓克隆） |
| BFS 抓取 | 配置里的 `storeHouse`/`urls`、列表页里的 `data-url`/`href`、纯文本 URL 清单 |

仓库发现与拉取：

```powershell
py tools/gh_discover.py search     # GitHub 搜索 → data/state/gh_repos.json
py tools/gh_pull.py --list         # 看要拉哪些仓库
py tools/gh_pull.py                # partial clone + 只 checkout 配置类文件
```

## 3. 去重策略（核心）

TVBox 配置里同一个站点会以几十种写法重复出现，`tvh` 用四级指纹：

| 级别 | 指纹 | 用途 |
| --- | --- | --- |
| `backend` | `h\|type\|canon_api(api)` / `c\|type\|api\|ext` / `j\|` / `e\|` / `n\|` / `m\|` | 主去重键：**同一后端只保留一条** |
| `exact` | type + api + ext + jar 全等 | 精确重复 |
| `key` | 站点 key | 兼容旧式（按 key 去重） |
| `name` | 归一化站点名 | 统计同名冲突 |

`canon_api()` 会去掉 `ac/wd/ids/pg/t/at` 这类查询参数、`/json`、`/at/json`、`index.php` 后缀、尾斜杠、`www.`，
所以下面这些都被认成同一个站：

```
http://www.360zy.com/api.php/provide/vod/?ac=list
https://360zy.com/api.php/provide/vod/at/json
360zy.com/api.php/provide/vod
```

去重后还会做三件收尾：

1. **名称消歧**：同名不同后端 → `名称·短标识`（csp 用类名，采集站用域名）。
2. **key 修正**：key 冲突加 `_2`/`_3`，超 64 字符截断（TVBox 对 key 长度敏感）。
3. **相对路径改写**：`./lib/drpy2.min.js` 按所在文档的 URL 绝对化，避免跨仓库合并后失效。

## 4. 爬虫（jar）归属

csp 类型站点（`type:3` + `csp_XXX`）必须由 jar 里的同名类实现，否则点了就报错。

1. 从所有文档里收集 `.jar` 候选（含 `;md5;`/`;pk;` 后缀形式）；
2. 并发下载，解 zip 里的 `.dex`，提取类名/标识符集合；
3. 对每个 `csp_XXX` 找「包含它的最稳 jar」（优先级：github/jsdelivr/gitee/ghproxy > 其它；再按引用次数、体积）；
4. 给该站点写**站点级 `"jar"`**（TVBox 支持 `sites[].jar` 覆盖全局 `spider`），类名找不到的站点在严格模式下剔除。

## 5. 可用性探测

| 站点类型 | 判活方式 |
| --- | --- |
| 0/1/2/5/6/7/8（采集） | 真请求 `?ac=list`，校验 XML/JSON 结构，再看裸 api |
| 3/4/9（csp） | `ext` 可达性代理（ext 是线路配置，死了基本就是死站）；无 ext 记 `unknown` |
| 10/11（js） | 请求 api 判断 200 |

结果缓存 `data/state/health.json`（默认 6 小时），`--no-verify` 可跳过。

## 6. 产物说明

| 文件 | 内容 | 适用 |
| --- | --- | --- |
| `index.json` | 严格模式：爬虫类名可解析 + 探测未判死 | **主推，日常用这个** |
| `index_all.json` | 不做严格过滤的全量站点 | 想要"全都要" |
| `index_lite.json` | 按可用性/延迟排序的前 300 站 | 低配盒子、加载慢 |
| `index_collect.json` | 只要采集站（无 jar 依赖，最稳） | 不想依赖爬虫 |
| `index_spider.json` | 只要 csp 爬虫站（已配站点级 jar） | 想看更多片源 |
| `index_lives.json` | 直播源，`lives` 带频道分组 | 看电视直播 |
| `storehouse.json` | 多仓：每个来源仓库一条 | 想自己挑仓库 |

## 7. 目录结构

```
tvh/
  util.py     字符串/URL/JSON 修补工具
  http.py     带缓存、重试、限并发的抓取器
  model.py    站点指纹、canon_api、配置解析
  parse.py    文档识别（配置/多仓/直播/文本）
  extract.py  仓库扫描、列表页链接抽取、GitHub API
  dedupe.py   四级去重、名称消歧、key 修正
  verify.py   可用性探测
  spider.py   jar 下载与类名覆盖分析
  merge.py    全局字段合并、排序、配置生成
  cli.py      discover / crawl / build / all
tools/
  make_seeds.py  gh_discover.py  gh_pull.py  serve.py  publish.py  validate.py
```

## 8. 发布成"一条链接"

**官方链接（仓库 `lebond2021/mediasources` 的 `dist` 分支，每天自动重建）：**

| 用途 | 链接 |
| --- | --- |
| 主链接（jsDelivr 加速，国内可用） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index.json |
| 直连 raw（最新，无需 CDN 缓存） | https://raw.githubusercontent.com/lebond2021/mediasources/dist/index.json |
| 精简版（300 站，低配盒子） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_lite.json |
| 多仓版（影视仓） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/storehouse.json |
| 全量档（约 7 万站，仅供归档，勿填盒子） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_all.json |
| GitHub Pages（待 Actions 恢复后启用） | https://lebond2021.github.io/mediasources/index.json |

`dist` 分支永远只有一个提交（每次强推覆盖），所以仓库体积不会随天数膨胀；`main` 分支只放代码。

**三种发布方式：**

1. **本机/局域网**：`py tools/serve.py` → `http://<你的IP>:8080/index.json`。
2. **GitHub（当前采用）**：`tools/update.ps1` 每天把 `dist/` 强推到 `dist` 分支。
3. **匿名文件床**（临时备用）：`py tools/publish2.py dist/index.json`（pomf + kappa + uguu，自动回读校验）。

## 8.5 每日自动更新

| 通道 | 状态 | 说明 |
| --- | --- | --- |
| Windows 计划任务 `TVBox-Aggregator-Daily` | **已启用** | 每天 04:10 跑 `tools/update.ps1`：发现新仓库 → 抓取 → 去重 → 探测剔除失效 → 生成 → 强推 `dist` 分支 |
| GitHub Actions `.github/workflows/update.yml` | 已提交，待启用 | 账号级被 GitHub 关闭（`422 Actions has been disabled for this user`），在 https://github.com/settings 里恢复 Actions 后自动按 cron `10 20 * * *`（UTC，= 北京 04:10）运行 |

手动跑一次：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\update.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\update.ps1 -PublishOnly   # 只重发当前 dist
```

日志在 `data/logs/update-*.log`（保留最近 30 份）。计划任务开启「错过补跑」，关机错过的会在下次开机后补一次。

每轮还会生成两份对比文件，随构建一起发布到 `dist` 分支：

- `CHANGES.md`（= `docs/changes.md`）：本轮**新增 / 移除**的站点清单
- `REPORT.md`（= `docs/aggregation-report.md`）：规模、type 分布、域名排行

```powershell
py tools/diff_report.py --out docs/changes.md   # 手动查看本轮变化
```

## 9. 已知限制

- csp 站点的真实播放能力无法在不运行 jar 的前提下验证，只能保证「类名存在 + ext 可达」。
- 部分源站有 UA/Referer/IP 限制，探测通过不代表任何网络环境都能播。
- 上游站点随时失效，建议每天重建一次（`py -m tvh all`）。
