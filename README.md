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
| `index_lives.json` | 直播配置：`lives[0]` 是聚合总表，其后是 7 条备用列表 | 看电视直播 |
| `live_all.m3u` | 聚合总表本体：频道归一 + 测速 + 同频道多源（一频道最多 3 条线路） | 想直接看全表 |
| `index_home.json` | 首页站源候选（实测可用 + 质量排序，首位已改名 `★主站`） | 不想自己挑首页站源 |
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
| **点播主链接**（最新，无需 CDN 缓存） | https://raw.githubusercontent.com/lebond2021/mediasources/dist/index.json |
| 点播镜像（jsDelivr 加速，国内可用） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index.json |
| **直播主链接**（`application/json`，实测可用） | https://pomf2.lain.la/f/dcdls81s.json |
| 直播备用镜像 | https://kappa.lol/JtqqX6 ／ https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_lives.json |
| 直播总表（77 频道 / 118 源，可直接当播放列表） | https://raw.githubusercontent.com/lebond2021/mediasources/dist/live_all.m3u |
| **免选首页站源**（实测站点 + 质量排序，首位即默认站） | https://raw.githubusercontent.com/lebond2021/mediasources/dist/index_home.json |
| 精简版（300 站，低配盒子） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_lite.json |
| 多仓版（影视仓） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/storehouse.json |
| 全量档（约 6.9 万站，仅供归档，勿填盒子） | https://cdn.jsdelivr.net/gh/lebond2021/mediasources@dist/index_all.json |

### 直播为什么要分两个文件、还挑主机

真机实测（BlueStacks + TVBox `com.github.tvbox.osc.jun`）踩出来的三条硬规则：

1. **配置 JSON 必须是 `application/json`**。raw 返回 `text/plain`，直播加载器会静默忽略并回落到内置「测试频道」；点播加载器不挑，所以点播可以放 raw。
2. **总表 m3u 必须走 `text/plain`**。jsDelivr 对 `.m3u` 返回 `audio/x-mpegurl`，实测会被当 JS 模块解析并报 `evaluateModule-error ... unexpected token '#EXTM3U'`；`.txt` 也一样走模块解析。用 raw 的 `live_all.m3u`（`text/plain`）稳。
3. **`dist` 分支每次必须整目录强推**。曾经手推单个 `index_lives.json` 把 `live_all.m3u` 从分支上冲掉，raw 直接 404，直播立刻回落测试频道。

换新配置后如果直播页仍是「测试频道」，先 `am force-stop` 再重进；`LivePlayActivity` 已在栈上时不会重读配置。

`dist` 分支永远只有一个提交（每次强推覆盖），所以仓库体积不会随天数膨胀；`main` 分支只放代码。

**三种发布方式：**

1. **本机/局域网**：`py tools/serve.py` → `http://<你的IP>:8080/index.json`。
2. **GitHub（当前采用）**：`tools/update.ps1` 每天把 `dist/` 强推到 `dist` 分支。
3. **匿名文件床**（临时备用）：`py tools/publish_live.py`（上传直播配置到 pomf + kappa 并回读校验，同时刷新 `dist/published.json`）。

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

每天这一轮还会额外做三件事：

| 步骤 | 命令 | 作用 |
| --- | --- | --- |
| 首页站源 | `py tools/make_home.py --probe 300 --keep 120` → `py tools/promote_home.py` | 实测采集站的分类数与延迟，把最能用的站前置成 `sites[0]`（TVBox 留空首页站源时用它） |
| 直播整合 | `py tools/build_live.py --workers 128 --min-kbps 180 --per-channel 3` | 频道名归一去重 → 逐条真拉流测速 → 同频道合并多源、慢源直接丢 |
| 直播装配 | `py tools/emit_lives.py` | 把总表写进 `index_lives.json` 的 `lives[0]`，再挂 7 条备用列表 |

直播测速的门槛是 **180 KB/s**（低于此值不进产物），每频道最多保留 3 条线路，按实测速度降序——TVBox 播不动会自动切下一条。

## 8.6 聚合点播：一个站点吃多个源

TVBox 原生的「聚合搜索」只能**跨站搜**，点开某一部片还是落在单个站里，线路也只有那一家的。如果想让**一个站点**就包含多个采集站的内容（同一条影片直接列出 3~8 条线路，播不动就换线），需要在本地跑一个聚合服务：

```powershell
py tools/agg_server.py --port 8008 --sites-file data\agg_sites.json --append-sites 200
```

启动后它做三件事：

1. `http://<本机局域网IP>:8008/api.php/provide/vod/` —— 一个标准苹果 CMS 接口，内部把 12 个采集站合起来：
   - `ac=list` / `ac=videolist&t=&pg=`：多站内容混排，按片名去重，卡片角标显示「N源」
   - `ac=detail&ids=gXXXX`：把同一条影片在多个站的线路合并成 `线路1/2/3…`（按首集地址去重）
   - `wd=关键词&ac=detail`：一次搜索打到所有站，结果按片名合并（带 5 分钟缓存）
2. `http://<本机局域网IP>:8008/` —— 顺带把整份配置也发出去：`sites[0]` 就是「聚合点播·多源」，后面跟 200 个常规站。**TVBox 里只填这一个地址**即可。
3. 批量取详情（TVBox 一次会发上百个 id）走「轻量」路径，0 秒返回卡片信息；真正点开某一部片时才做多源合并，避免首页转圈。

真机验证（BlueStacks + TVBox）：首页显示「聚合点播·12源」，卡片带 9源/7源/6源 角标；详情页两条线路「🍭无尽动漫🍭·wjm3u8」「猫眼资源(CMS·mym3u8」；第 01 集正常播放；搜索「庆余年」返回 14 条合并结果（3源/11源/9源…）。

**要出门用（电视盒子不在同一局域网）**，把服务放到有公网地址的机器上，或用内网穿透：

```powershell
# 方式 A：VPS / NAS 上直接跑，--public 写对外地址
py tools/agg_server.py --port 8008 --public https://your-host.example.com

# 方式 B：本机 + cloudflared 临时隧道
cloudflared tunnel --url http://127.0.0.1:8008
py tools/agg_server.py --port 8008 --public https://<隧道域名>
```

注意：这条链路依赖你的服务在跑，关机就没了；它是**可选增强**，`dist` 分支上的静态配置（4509 站 + 原生聚合搜索）不依赖它。

## 9. 已知限制

- csp 站点的真实播放能力无法在不运行 jar 的前提下验证，只能保证「类名存在 + ext 可达」。
- 部分源站有 UA/Referer/IP 限制，探测通过不代表任何网络环境都能播。
- 上游站点随时失效，建议每天重建一次（`py -m tvh all`）。
