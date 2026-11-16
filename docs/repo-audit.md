# TVBox 源仓库审阅报告（聚合器前置事实）

- 审阅对象：`sources\cliya`、`sources\qist`、`sources\tvbox`(=noimank/tvbox)、`sources\tvyuan`
- 数据来源：本目录下 `tools\audit_*.py` 的实际运行输出（`tools\out\*.txt`），全部数字可复现
- 统计口径：`walk_files()` 跳过 `.git`；"配置 JSON" 指能解析且含 `sites`/`lives` 等 TVBox 顶层字段的对象；JSON5 清洗 = string-aware 去 `//`、`/* */` 注释 + 去尾逗号
- 生成时间：2026-11-15

---

## 0. 结论速览（先看这 10 条）

1. **只有 2 个仓库真正装配置**：`qist`（17 个配置 JSON）和 `tvyuan`（3 个）。`cliya` 与 `noimank/tvbox` 只是**多仓索引**，不含任何 sites 条目。
2. 4 仓合计可解析配置 **20 个**，含 **2989 条 sites**；按 `(type, api)` 归一化去重后只剩 **1074 条**（去重率 **64.1%**）。跨源重复极其严重。
3. **`key` 不能当主键**：仅按 `key` 去重剩 1870 条（去重 37.4%），但存在 **key 相同而 api 不同**（如 `key=玩偶` 对应 3 个不同 `csp_` 类）和 **api 相同而 key 不同**（如 `api=lib/drpy2.min.js` 挂 231 个不同 key）两种反向冲突，两个方向都有实测样本。
4. `type=3` 占 **85.2%**（2546/2989），其中 `api` 为 `csp_XXX` 的 **1864 条（62.4%）**——`csp_` 是**jar 内类名标记**，`csp_DouDouGuard` 实际指向 dex 里的 `Lcom/github/catvod/spider/DouDouGuard;`。**key 与类名无必然关系**（1669 条 key 不带 `csp_` 前缀但 api 带）。
5. **jar 与配置必须绑死**：按"每个配置自带的 spider jar 里是否真有该 csp_ 类"实测，`qist/0821.json` 只有 25/38 可解析、`qist/0825.json` 76/83；全仓 673 个不同 `csp_` 类，本地 9 个 jar 合计只能覆盖 **255 个（38%）**，其余 418 个依赖未落地的远程 jar。
6. **相对路径是最大陷阱**：`./lib/drpy2.min.js` 这类 api 是**相对配置自身所在仓库**的路径。`qist` 内 858 条可解析 / 220 条悬空；`tvyuan` 内 **180 条全部悬空**（该仓根本不带 js/lib 资源）——聚合时若不改写成绝对 URL，跨仓合并必然碎掉。
7. 多仓格式有 **2 套键名**：`{"urls":[{"url","name"}]}`（5 个文件）与 `{"storeHouse":[{"sourceName","sourceUrl"}]}`（2 个文件），合计 7 个文件 177 条条目，其中 `qist/0707.json` 用**相对路径** `./99188.json` 指向同仓配置。
8. 坏数据可控但**不能只靠 `json.loads`**：268 个 JSON 候选里裸解析成功 221 个（82.5%），去注释+去尾逗号后 267 个（99.6%），再用 `raw_decode()` 截断尾部垃圾 → **268/268 全可读**（唯一需要截断的是 `qist/json/dj看球.json`：合法对象后面粘了整段 HTML）。另有 4 个 BOM、47 个带注释、5 个尾逗号、30 个含 base64、**1 个 UTF-16LE 直播源**、**1 个改了扩展名的 jar（`qist/jar/fan.txt`）**、**1 个 .jpg 伪装的远程 jar**。
9. `qist` 的 257 个 JSON **大部分不是配置**：只有 17 个是 TVBox 配置，其余是 XYQ/XBPQ 爬虫规则（102+32）、class/filter 片段（37）、biliext（12）、cat 系另一套 schema（6）、纯数组（14）、杂项（35）。且 **33 组内容完全相同的镜像**（84 个文件），`xiaosa/` 目录整体是仓库根的子集副本。
10. `tvyuan/update.py` 的聚合逻辑有 8 处硬缺陷，最致命的是**只按 key 去重**（第 185 行）和**spider 取"出现次数最多的 jar"**（第 271 行）——后者会让全部 `csp_` 站点与 jar 错配而集体失效。

---

## 1. 四仓库规模与定位

### 1.1 文件规模（`tools/out/01_inventory.txt`）

| 仓库 | 文件数 | 子目录数 | 体积 | 扩展名分布 | 形态 |
|---|---|---|---|---|---|
| `cliya` | 8 | 0 | 647,553 B | json 4 / txt 2 / m3u 1 / md 1 | 全平铺，纯多仓索引 + 直播 |
| `qist` | 1098 | 29 | 113,881,863 B | js 694 / json 257 / py 62 / txt 32 / md5 10 / gz 9 / jpg 8 / jar 8 / md 7 / m3u 5 / yml 2 | 巨型资源仓（代码+规则+jar+直播+网盘） |
| `tvbox` (noimank) | 2 | 0 | 3,648 B | `README.md` + `tvboxmuti.json` | 只有一个 14 条目的多仓索引 |
| `tvyuan` | 10 | 2 | 614,175 B | json 4 / md 2 / txt 1 / py 1 / yml 1 / gitignore 1 | 聚合器仓：`update.py` + 生成物 |

### 1.2 内容构成（按 `classify()` 分类，仅 JSON-ish 候选 = `.json` + 以 `{`/`[` 开头的 `.txt`）

| 类别 | cliya | qist | tvbox | tvyuan | 说明 |
|---|---|---|---|---|---|
| `tvbox-config` | 0 | **17** | 0 | **3** | 真正的 TVBox 配置 |
| `multi-urls` | 2 | 1 | 1 | 0 | `{"urls":[...]}` 多仓 |
| `multi-storeHouse` | 2 | 0 | 0 | 1 | `{"storeHouse":[...]}` 多仓 |
| `xyq-spider-rule` | 0 | 102 | 0 | 0 | XYQ/XBPQ 爬虫规则（中文键） |
| `class-filters` | 0 | 37 | 0 | 0 | `{"class":[...],"filters":{...}}` |
| `csp-site-rule` | 0 | 32 | 0 | 0 | 单站 `{"规则名":...}` 变体 |
| `biliext` | 0 | 12 | 0 | 0 | `{"cookie","classes","filter"}` |
| `cat-open-config` | 0 | 6 | 0 | 0 | `{"video","read","comic","pan","color"}` 另一套 schema |
| `json-array` | 0 | 14 | 0 | 0 | 顶层数组（alist / 课堂 / 直播数据） |
| `other-dict` | 0 | 35 | 0 | 0 | singbox 配置、日志、杂项 |
| `UNPARSEABLE` | 0 | 1 | 0 | 0 | `qist/json/dj看球.json` |

**配置 JSON 清单（20 个）**

- `qist`（17）：`0821.json` `0825.json` `0826.json` `0827.json` `367.json` `9918.json` `99188.json` `dianshi.json` `fty.json` `js.json` `jsm.json` `XYQ.json`（需去注释）`cat/tjs/18_tv_config.json` `cat/tjs/tv_config.json` `tools/dianshi.json` `tools/jsm.json` `xiaosa/api.json`
- `tvyuan`（3）：`tvbox.json` `tvbox_collect.json` `tvbox_full.json`（4 个 tvyuan JSON 全部裸解析通过，无注释/BOM）
- `cliya` / `tvbox`：**0 个**

### 1.3 直播源文件（39 个，`tools/out/07_extra.txt` Q1a）

| 类型 | 代表文件 | 行数 | 备注 |
|---|---|---|---|
| `#genre#` 分格式 txt | 见下表 | 40–4560 | `分类名,#genre#` + `频道名,url[,额外列...]` |
| m3u | 见下表 | 119–51643 | 标准 `#EXTM3U` + `#EXTINF` |
| 裸 url 列表 | `qist/live/山东联通.txt` `辽宁移动华为/烽火.txt` `live/河南联通单播.txt`(rtsp) | 178 / 390 / 105 | 无分组头 |
| 网盘分享清单 | `qist/json/{115,alishare,alishare.ebook,quarkshare,ucshare,thundershare,pushshare,sambashare}*.txt` | 7–645 | `shareid?password=xxx 名称 1`，**不是直播** |
| 订阅格式说明 | `qist/js/lf_live.txt` | 40 | 自述 `#订阅名` / 相对路径规则 |
| **伪装的 jar** | `qist/jar/fan.txt` | — | 1,397,957 B，`PK\x03\x04` 开头，**实为 jar**（0821/0826/fty 的 spider 指向它） |

主要直播文件实测行数/字节（`tools/out/14_verify.txt`）：

| 文件 | 行数 | 字节 | 编码 |
|---|---|---|---|
| `cliya/18live.txt` | 4,560 | 488,997 | utf-8 |
| `cliya/live.txt` | 123 | 7,549 | utf-8 |
| `cliya/live.m3u` | 1,146 | 139,139 | utf-8 |
| `qist/listx.m3u` | **51,643** | 6,322,832 | utf-8 |
| `qist/livex.m3u` | 29,304 | 1,053,416 | utf-8 |
| `qist/zb.txt` | 2,998 | 236,816 | utf-8 |
| `qist/list.m3u` | 1,649 | 88,791 | utf-8 |
| `qist/radio.m3u` / `radio.txt` | 2,957 / 1,485 | 160,844 / 107,296 | utf-8 |
| `qist/tvlive.txt` / `tvboxtv.txt` | 1,455 / 1,425 | 158,895 / 156,020 | utf-8 |
| `qist/listx.txt` / `list.txt` | 1,305 / 206 | 117,939 / 16,038 | utf-8 |
| `qist/ITV.txt` | 648 | 88,216 | utf-8 |
| `qist/FTY/id.m3u` / `id.txt` | 119 / 67 | 15,119 / 9,615 | utf-8 |
| `qist/live/辽宁移动华为.txt` / `烽火.txt` | 390 / 390 | 32,843 / 39,473 | utf-8 |
| `qist/live/广东联通内网.txt` / `山东联通.txt` | 192 / 178 | 62,942 / 25,050 | utf-8 |
| `qist/live/河南联通单播.txt` | 105 | 53,746 | utf-8（rtsp） |
| `qist/live/辽宁联通.txt` | 152 | 25,732 | **utf-16le + BOM** |

**编码陷阱**：`qist/live/辽宁联通.txt` 是 **UTF-16LE + BOM**（首字节 `\xff\xfe`，25,732 B），按 UTF-8 读会整片乱码；其余 38 个为 UTF-8。行形态统计：裸 url 43,527 / 注释或 `#` 行 43,455 / `name,url` 16,976 / 其它 3,427 / `name,url,extra` 1,654 / `#genre#` 头 111。

### 1.4 spider jar

| 文件 | 字节 | md5 | 备注 |
|---|---|---|---|
| `qist/jar/pg23a94bb_upgraded.jar` | 11,725,653 | `7c8f662c…` | 最大，dex 5.97 MB |
| `qist/jar/pg_upgraded.jar` | 2,912,031 | `e58c3a29…` | 0825/9918/js 使用 |
| `qist/jar/spider.jar` | 1,929,492 | `cbe016eb…` | dianshi/jsm 使用；`xiaosa/spider.jar` 与其 **md5 完全相同** |
| `qist/jar/fty.jar` | 640,982 | `b25d0e7f…` | |
| `qist/jar/XBPQ_upgraded.jar` | 659,007 | `c10ebfca…` | 与 `csp_XBPQ` 站点配套 |
| `qist/jar/XYQ.jar` | 393,490 | `705ba6e2…` | 与 `XYQ.json` 配套 |
| `qist/jar/custom_spider.jar` | 266,777 | `41c87635…` | 0827 使用 |
| `qist/jar/fan.txt` | 1,397,957 | — | **改名的 jar**，含 `DouDouGuard` 等 Guard 类 |
| `qist/xiaosa/spider.jar` | 1,929,492 | `cbe016eb…` | `spider.jar` 的副本 |

配套 `.md5` 文件 10 个（`cat/*/index*.js.md5`、`lib/*.md5`），是 cat 系前端的资源校验，不是 jar 校验。

### 1.5 js / py

- **js 694 个**：`qist/js` 269、`qist/cat/js` 165、`qist/xiaosa/js` 83、`qist/cat/tjs/js` 65、`qist/cat/tjs/lib` 40、`qist/FTY` 30、`qist/lib` 29、`qist/cat/js/lib` 8、`cat/dist` 2、`cat/18_dist` 2、`tools` 1。
- **py 62 个**：`xiaosa/py` 32、`py` 22、`tools` 6、`json` 1、`lib` 1、`tvyuan/update.py` 1。最大者为 `qist/py/红果短剧.py`（326,612 B，与 `xiaosa/py/红果短剧.py` 同尺寸=镜像）。
- `qist/tools/build_local.py`(16,159 B)、`qist/tools/tvbox.py`(16,136 B) 是该仓自己的构建脚本。

---

## 2. 配置 JSON 的真实 schema（Q2）

### 2.1 顶层 key 频次（N=20 个配置文件）

| key | 出现文件数 | 占比 | 值类型 | 备注 |
|---|---|---|---|---|
| `sites` | 20 | 100% | list | 唯一必备 |
| `lives` | 19 | 95% | list | |
| `spider` | 18 | 90% | str | 2 个 cat 配置与 2 个 tvyuan 生成物为空/缺 |
| `wallpaper` | 17 | 85% | str | 单 URL |
| `rules` | 16 | 80% | list | 嗅探/去广告规则 |
| `parses` | 14 | 70% | list | |
| `doh` | 12 | 60% | list | |
| `ads` | 12 | 60% | list | 纯字符串数组 |
| `flags` | 9 | 45% | list | 纯字符串数组 |
| `logo` | 7 | 35% | str | |
| `danmaku` | 5 | 25% | str | 弹幕 API |
| `ijk` | 4 | 20% | list | 播放器参数组 |
| `hosts` | 3 | 15% | list | 字符串数组 |
| `warningText` | 1 | 5% | str | 只有 `367.json` |
| `proxy` `notice` `headers` `timeout` `style` `ext` `homepage` | **0** | 0% | — | 文档里常见，**这 20 个配置里一次都没出现**（`style`/`timeout` 只作为 sites 条目内字段存在） |

**关键事实**：顶层没有 `proxy`/`notice`/`homepage`/`timeout`/`headers`/`ext`。写聚合器时不要假设它们存在，也不要往顶层塞 `style`——它属于 `sites[]`。

### 2.2 子结构

| 数组 | 字段（按频次） | 样本 |
|---|---|---|
| `sites[]` | 见 §3 | — |
| `parses[]`（14 文件，337 条） | `name` 337 / `type` 337 / `url` 337 / `ext` 185 / `header` 7 / `i` 1 | `{"name":"Json聚合","type":3,"url":"Demo"}`；`{"name":"虾米","type":0,"url":"https://jx.xmflv.com/?url=","ext":{"flag":["qq","腾讯",...]}}` |
| `lives[]`（19 文件，174 条） | `name` 174 / `url` 174 / `type` 169 / `epg` 103 / `logo` 101 / `playerType` 99 / `ua` 97 / `timeout` 38 / `pass` 7 / `boot` 2 / `timeZone` 2 / `click` 1 | `{"name":"初秋语•ipv4","type":0,"url":"./list.txt","playerType":2,"epg":"http://epg.cdn.loc.cc/?ch={name}&date={date}","logo":"https://live.fanmingming.com/tv/{name}.png"}` |
| `rules[]`（16 文件，172 条） | `name` 172 / `hosts` 172 / `regex` 148 / `script` 15 / `host` 6 / `rule` 6 | `{"name":"bf","hosts":["bfzy"],"regex":["#EXT-X-DISCONTINUITY\\r*\\n*#EXTINF:3,[\\s\\S]*?#EXT-X-DISCONTINUITY"]}` |
| `ads[]`（12 文件，554 条） | 全部为 `str` | 域名/正则字符串 |
| `flags[]`（9 文件，438 条） | 全部为 `str` | |
| `doh[]`（12 文件，60 条） | `name` / `url` / `ips` 各 60 | `{"name":"Google","url":"https://dns.google/dns-query","ips":["8.8.4.4","8.8.8.8"]}` |
| `ijk[]`（4 文件，8 组） | `group` 8 / `options` 8 | `{"group":"软解码","options":[{"category":4,"name":"opensles","value":"0"},...]}` |
| `hosts[]`（3 文件，12 条） | 全部为 `str` | |

`lives[].url` 形态：http 149 / **相对路径 23** / 空串 1 / 非字符串 1（`{}` 空对象）/ **base64 1**（`aHR0cDovLzU1MC4zdmNuLndvcmsvanl0di5qc29u` = `http://550.3vcn.work/jytv.json`）。即：lives 的 url 也可能是 base64，需要尝试解码。

---

## 3. `sites` 条目形态统计（Q3）

### 3.1 字段频次（N=2989）

| 字段 | 次数 | 占比 | 字段 | 次数 | 占比 |
|---|---|---|---|---|---|
| `key` | 2989 | 100% | `playerType` | 183 | 6% |
| `name` | 2989 | 100% | `jar` | 173 | 6% |
| `type` | 2989 | 100% | `categories` | 70 | 2% |
| `api` | 2989 | 100% | `header` | 63 | 2% |
| `searchable` | 2037 | 68% | `playUrl` | 60 | 2% |
| `ext` | 1761 | 59% | `recordable` | 45 | 2% |
| `quickSearch` | 1556 | 52% | `genre` | 43 | 1% |
| `changeable` | 1350 | 45% | `indexs` | 39 | 1% |
| `filterable` | 1026 | 34% | `类型` | 12 | 0% |
| `style` | 544 | 18% | `homePage` | 11 | 0% |
| `timeout` | 519 | 17% | `hide`/`order_num` | 10 | 0% |

注意几个**非标准/脏字段**：`类型`（12，中文键）、`playurl`（4，小写）与 `playUrl`（60）并存、`url`（3）、`click`（1）、`type_flag`（1）、`lang`（1）、`proxy`（1）、`ua`（1）。`headers`（复数）在所有 sites 里**一次都没出现**，只有 `header`（单数，2%）。

### 3.2 `type` 取值分布

| type | 条数 | 占比 | 语义（由 api 形态反推） |
|---|---|---|---|
| `3` | 2546 | 85.2% | 爬虫/spider 站（jar 类、js、py） |
| `1` | 282 | 9.4% | 采集站 JSON（`api.php/provide/vod`） |
| `0` | 84 | 2.8% | 采集站 XML（`at/xml`） |
| `4` | 76 | 2.5% | 混合（php 采集 49 / http 其它 17 / vod 10） |
| `"3"`（字符串） | 1 | 0.0% | `{"key":"csp_AList","api":"csp_AList","type":"3"}` |

**type 是字符串一次就足以让强类型解析炸**，聚合时必须 `int()` 容错。

### 3.3 `api` 形态 × `type` 交叉表

| api 形态 | 条数 | 占比 | type=3 | type=1 | type=0 | type=4 |
|---|---|---|---|---|---|---|
| `csp_XXX`（jar 类名） | 1864 | 62.4% | 1863 | 0 | 0 | 0 |
| 相对路径 `.js` | 488 | 16.3% | 488 | 0 | 0 | 0 |
| `http…api.php/provide/vod` | 335 | 11.2% | 0 | 276 | 49 | 10 |
| `http` 其它 | 142 | 4.8% | 125 | 0 | 0 | 17 |
| `http…*.php`（非 provide/vod） | 90 | 3.0% | 0 | 6 | 35 | 49 |
| 相对路径 `.py` | 68 | 2.3% | 68 | 0 | 0 | 0 |
| 其它（裸 token） | 2 | 0.1% | 2 | 0 | 0 | 0 |

相对路径按目录细分：`./lib/*` 431、`./js/*` 59、`./py/*` 49、`./cat/*` 6、`./FTY/*` 5、`./drpy_libs/*` 2、`./liba/*` 2、`./ext/*` 1、根目录 1。

**裸 token 实例**：`{"key":"py_cctv","name":"[1434ms|金鹰] 🇨🇳央视","api":"py_cctv","type":3}` —— api 既不是 URL 也不是路径，而是内置播放器/内置源的标记名。聚合器必须保留未知 api 形态而不是丢弃。

### 3.4 `ext` 形态（N=2989）

| 形态 | 条数 | 占比 | 实例 |
|---|---|---|---|
| 缺失（无 `ext` 键） | 1228 | 41.1% | — |
| 其它字符串（相对路径/裸名） | 802 | 26.8% | `"./json/alist.json"`、`"./js/360影视.js"` |
| **JSON 对象** | 540 | 18.1% | `{"Cloud-drive":"tvfan/Cloud-drive.txt","from":"4k|auto","siteUrl":"https://www.wogg.com/","danMu":"弹"}` |
| http URL | 286 | 9.6% | `"https://www.zxzjhd.com/"` |
| **疑似 base64** | 98 | 3.3% | `"rfOX1voDIQhH8epBwtCFsq+8syyZ18T30GkibomjS1xHcE9fpWU7oKJ1cO9K0M5hrnOHZ9dKjiJz5HEyTr57RZHCqunfFT7jH/mEy+uqVyo="`（`csp_AppSKGuard` 的 ext） |
| 空串 | 23 | 0.8% | `""`（`csp_DaShiXiong`、`./js/ss/porn.py`） |
| **JSON 字符串**（未展开的字符串化对象） | 12 | 0.4% | `"{\"username\":\"fanty\",\"password\":\"qqq111\",\"searchurl\":\"https://zhaoziyuan1.cc/so?filename={wd}\"}"` |

结论：`ext` 是**多态字段**，聚合器必须按 `(type, api 前缀)` 分别处理，且"JSON 字符串"要二次 `json.loads` 才能拿到结构。

### 3.5 `key` 命名规律

- 总数 2989，去重 **1902**；其中 `csp_` 前缀仅 **179 个去重 key / 206 次出现**（6.9%），**绝大多数 key 不带前缀**。
- 字符形态：含中文 972 / 纯 ASCII token 749 / `csp_` 前缀 179 / 其它 2。
- **跨仓库重复 key 300 个**（几乎全是 `qist ↔ tvyuan` 的重叠，因为 tvyuan 就是抓 qist 这类源生成的）。
- **key 前缀与 api 前缀经常不一致**：`api=csp_*` 但 key 不带 `csp_` 的 **1669 条**（例：`key=豆 api=csp_DouDouGuard`）；反向只有 **11 条**（`key=csp_xml_索尼资源 api=https://suoniapi.com/...`）。
- 同一文件内 key 重复最多：`push_agent` 16、`玩偶` 11、`量子` 10、`非凡` 10、`配置中心` 10、`新6V` 9、`cc` 9。
- **key 就是 spider 类的注册名**（对 `csp_` 站而言），但同一逻辑站点在不同仓库用了不同 key（`玩偶` / `Wogg` / `Doll` 混用），所以 key 既不是全局唯一 ID，也不能反推站点身份。

### 3.6 其它常见字段的取值

- `playerType`：`2` 90 / `0` 38 / `1` 21 / `"2"` 20 / `"1"` 14 —— **int 与 str 混用**。
- `timeout`：`60` 231 / `30` 137 / `10` 100 / `15` 16 / `120` 15 / `12` 11 / `50` 9。
- `style`：`{"type":"list"}` 124 / `{"type":"rect","ratio":1.597}` 70 / `{"type":"rect","ratio":1}` 60 / `{"type":"rect","ratio":1.33}` 56 / `{"type":"rect","ratio":1.618}` 50 / `{"type":"list","ratio":1.433}` 43 …… 即 `style` 是**对象**（偶见字符串化的对象），不是字符串枚举。
- `jar`（173）：`http://我不是.摸鱼儿.top/by/jar/moyuer.php;md5;b752c…` 45 / `./xyqxbpq.jar` 38 / `./jar/XBPQ_upgraded.jar;md5;c10ebfca…` 15 / `./jar/gm.jar` 6 / `https://wp.kayyw.com/f/...` 6 …；格式恒为 `路径或URL[;md5;HASH]`。
- `header`（63）：对象，键为 UA/Referer 等；`headers` 复数不存在。
- `extend` / `clickSelector` / `searchUrl` / `playerUrl` / `referer`：**0 次**。`categories` 70、`indexs` 39、`recordable` 45、`genre` 43、`homePage` 11 属于少数派字段。

### 3.7 `csp_XXX` 到底是什么（可验证结论）

用 zipfile 读出 jar 内全部 `classes*.dex`，按 dex 类型描述符 `Lcom/github/catvod/spider/<Name>;` 检索：

| jar | dex 字节 | `/DouDouGuard;` | `/XBPQ;` | `/Bili;` | `Lcom/github/catvod/spider` 出现次数 |
|---|---|---|---|---|---|
| `qist/jar/fan.txt`（伪装 jar） | 37,992 | **1** | 0 | 0 | 79 |
| `qist/jar/pg_upgraded.jar` | 7,043,744 | 0 | 0 | 1 | 1094 |
| `qist/jar/pg23a94bb_upgraded.jar` | 5,965,264 | 0 | 0 | 1 | 1106 |
| `qist/jar/spider.jar` | 4,960,220 | 0 | 1 | 1 | 3361 |
| `qist/jar/XYQ.jar` | 990,256 | 0 | 0 | 1 | 716 |
| `qist/jar/custom_spider.jar` | 1,156,116 | 0 | 0 | 1 | 549 |
| `qist/jar/XBPQ_upgraded.jar` | 1,548,408 | 0 | 1 | 0 | 1765 |
| `qist/jar/fty.jar` | 1,509,644 | 0 | 1 | 1 | 928 |

**结论**：`api=csp_DouDouGuard` = 调用 jar 里 `com.github.catvod.spider.DouDouGuard` 类；`csp_` 是**前缀标记**，真正的类名是去掉 `csp_` 的部分。因此**只按 api 去重会把"同名类+不同 ext 配置"的站点错误合并**（见 §4.4 `csp_xbpq` 142 条），而**丢掉 key 就等于丢掉配置注册名**。

### 3.8 每个配置的 spider 与其 csp_ 类是否匹配（实测）

| 配置 | spider | csp_ 站点 | 不同 csp_ | 类在本 jar 内找到 | 缺失示例 |
|---|---|---|---|---|---|
| `qist/0821.json` | `fan.txt` | 42 | 38 | **25/38** | `csp_LiteAppleGuard` `csp_SbaibaiGuard` |
| `qist/0825.json` | `pg_upgraded.jar` | 106 | 83 | **76/83** | `csp_YGP` `csp_NanGua` `csp_Ikanbot` |
| `qist/0826.json` | `fan.txt` | 48 | 37 | **25/37** | 同 0821 |
| `qist/0827.json` | `custom_spider.jar` | 26 | 26 | 23/26 | `csp_NiNi` `csp_Ying` `csp_Dovx` |
| `qist/367.json` | `http://…moyu.php`（远程） | 95 | 67 | 无法校验 | — |
| `qist/9918.json` | `pg_upgraded.jar` | 24 | 22 | 22/22 | — |
| `qist/99188.json` | `pg23a94bb_upgraded.jar` | 24 | 22 | 22/22 | — |
| `qist/dianshi.json` | `spider.jar` | 113 | 89 | 89/89 | — |
| `qist/fty.json` | `fan.txt` | 46 | 38 | 37/38 | `csp_XPathGuard` |
| `qist/js.json` | `pg_upgraded.jar` | 71 | 63 | 60/63 | `csp_NanGua` `csp_Gitcafe` `csp_Dovx` |
| `qist/jsm.json` | `spider.jar` | 113 | 89 | 89/89 | — |
| `qist/XYQ.json` | `XYQ.jar` | 42 | 24 | 24/24 | — |
| `qist/xiaosa/api.json` | `spider.jar` | 114 | 91 | 91/91 | — |
| `qist/tools/dianshi.json` `tools/jsm.json` | `./jar/spider.jar` | 5 | 5 | **文件不存在** | — |
| `tvyuan/tvbox_full.json` | `…/7b563c7039830e7c712e93f27fd2e102.jpg` | **990** | 553 | 无法校验（远程 .jpg） | — |

全仓维度：**673 个不同 `csp_` 类，本地 9 个 jar 合计只能解析 255 个（38%）**，418 个依赖未落地的远程 jar。

> 聚合器含义：`spider` 必须**跟着站点走**（每个 site 记录它来自哪个配置、那个配置的 spider 是谁），不能在合并产物里只留一个 `spider`。

---

## 4. 跨源重复度实测（Q4）

### 4.1 全量去重（2989 条，20 个配置）

| 去重键 | 去重后条数 | 重复条数 | 重复率 | 保留比例 |
|---|---|---|---|---|
| 原始条目 | 2989 | 0 | 0.0% | 100.0% |
| `(type, api)` 归一化 | **1074** | 1915 | **64.1%** | 35.9% |
| `api` 归一化 | 1073 | 1916 | 64.1% | 35.9% |
| `name` 归一化 | 2376 | 613 | 20.5% | 79.5% |
| `key` | **1870** | 1119 | **37.4%** | 62.6% |
| `(name, api)` | 2416 | 573 | 19.2% | 80.8% |
| `(key, api)` | 1997 | 992 | 33.2% | 66.8% |
| `(key, type, api)` | 1998 | 991 | 33.2% | 66.8% |

归一化规则（`tools/audit_dedup.py:norm_api`）：api → `urlsplit()` 后 **scheme 保留**、host 小写、去 `:80`/`:443`、path 去尾部 `/`、**query 保留**；`./x` → `x`；name → 只保留字母数字与汉字并小写；key → `strip().lower()`。

**口径敏感性（同为实测）**：若把 scheme 也剥掉、并把 `?query` 一起丢弃，`(type,api)` 唯一数从 **1074 → 1042**（119 条 api 带 query，如 `api.php/provide/vod/?ac=list`）。→ 去重口径必须写死在聚合器里，并**优先按"去掉 query 后的 base api + 归一化 ext"配对**，否则请求参数不同的同一站点会被当成两个、或反之。

**为什么不能只用 `key`**：key 去重剩 1870，比 `(type,api)` 多 796 条 —— 这 796 条是"同 key 不同 api"（真冲突，丢了就丢站点）；而 key 去重后又保留了 992 条 `(key,api)` 重复，说明"同 api 同 key 但被不同文件重复收录"仍大量存在。**没有单一字段能同时避免误合与漏合**。

### 4.2 按仓库

| 仓库 | 条目 | `(type,api)` | `name` | `key` | `(key,type,api)` |
|---|---|---|---|---|---|
| `qist` | 1519 | **383** | 916 | 730 | 772 |
| `tvyuan` | 1470 | **890** | 1460 | 1448 | 1460 |
| `cliya` | 0 | — | — | — | — |
| `tvbox` | 0 | — | — | — | — |

`qist` 自身重复率 (1519→383) 高达 **74.8%**，因为 `js.json` 一个文件就贡献 298 条里只有 69 条唯一 `(type,api)`。

### 4.3 按文件（条目数 top 18）

| 文件 | 条目 | `(type,api)` | `key` | `name` |
|---|---|---|---|---|
| `tvyuan/tvbox_full.json` | 1451 | 888 | 1434 | 1441 |
| `qist/js.json` | 298 | **69** | 296 | 296 |
| `qist/dianshi.json` | 163 | 113 | 163 | 163 |
| `qist/jsm.json` | 162 | 113 | 162 | 162 |
| `qist/0825.json` | 135 | 93 | 134 | 134 |
| `qist/xiaosa/api.json` | 116 | 93 | 116 | 116 |
| `qist/367.json` | 106 | 74 | 103 | 105 |
| `qist/0821.json` | 86 | 48 | 84 | 86 |
| `qist/99188.json` | 64 | 59 | 64 | 63 |
| `qist/9918.json` | 61 | 56 | 61 | 60 |
| `qist/0826.json` | 54 | 39 | 54 | 54 |
| `qist/tools/dianshi.json` | 53 | 27 | 53 | 53 |
| `qist/tools/jsm.json` | 52 | 27 | 52 | 52 |
| `qist/fty.json` | 49 | 39 | 49 | 49 |
| `qist/XYQ.json` | 49 | 25 | 49 | 49 |
| `qist/0827.json` | 33 | 33 | 33 | 33 |
| `tvyuan/tvbox.json` | 10 | 6 | 9 | 10 |
| `tvyuan/tvbox_collect.json` | 9 | 8 | 9 | 9 |

> 前 12 行按条目数排序（`tools/out/14_verify.txt` 复核）。若改用"剥 scheme + 剥 query"的严口径，`tvyuan/tvbox_full.json` 从 888 降到 **845**、`qist/99188.json` 从 59 到 57、`qist/9918.json` 从 56 到 54 —— 即**同一批数据在不同归一化下相差 5% 左右**，聚合器必须固定口径。

### 4.4 证明一：**key 相同、api 不同**（不能只按 key 去重）

| key | 条目数 | 不同 api 数 | 实例（api / name / 出处） |
|---|---|---|---|
| `玩偶` | 11 | 3 | `csp_WoGGGuard`（👽玩偶哥哥┃4K弹幕 @qist/0821.json）<br>`csp_Wogg`（玩偶 @qist/0827.json）<br>`csp_Doll`（玩偶 @qist/9918.json） |
| `苹果` | 7 | 3 | `csp_LiteAppleGuard`（🍎苹果┃不卡 @qist/0821.json）<br>`csp_AppDrama`（苹果 • APP @qist/dianshi.json）<br>`csp_LiteApple`（[33ms\|我] 苹果 @tvyuan/tvbox_full.json） |
| `贱贱` | 5 | 3 | `csp_JPJGuard`（🐭荐片┃P2P @qist/0821.json）<br>`https://gitlab.com/fantaiying/ext/-/raw/main/drpy2.min.js`（🐭贱贱┃P2P┃纯净 @qist/367.json）<br>`./lib/apiv461drpy2.min.js`（[1434ms\|金鹰] 🎬荐片┃影视 @tvyuan/tvbox_full.json） |
| `push_agent` | 16 | 3 | `csp_PushGuard`（🛴手机┃推送 @qist/0821.json）<br>`csp_Push`（推送 @qist/0825.json）<br>`csp_PushAgent`（📽推送 @qist/XYQ.json） |

> 同一个 key 在不同源里指向**不同的 jar 类**甚至**完全不同的实现方式**（jar 类 vs 远程 drpy js）。按 key 去重 = 随机保留一个实现，其余静默消失。

### 4.5 证明二：**api 相同、key 不同**（不能只按 api 去重）

| api | 条目数 | 不同 key 数 | 实例 |
|---|---|---|---|
| `lib/drpy2.min.js` | **413** | **231** | `drpy_js_360影视`（官源┃360[js]）/ `drpy_js_奇珍异兽`（官源┃爱奇艺[js]）/ `drpy_js_百忙无果`（官源┃芒果[js]）/ `drpy_js_腾云驾雾`（官源┃腾讯[js]）@qist/0821.json |
| `csp_xbpq` | 142 | 129 | `小白` / `BT天堂` / `布谷tv` / `haokongbu` @qist/0825.json |
| `csp_appget` | 55 | 49 | `忍者`（🥷忍者┃蓝光┃弹幕）/ `彼岸` / `橘子` / `雨滴` @qist/367.json |
| `csp_bili` | 77 | 39 | `csp_Bili` / `哔哩` / `哔哩合集` / `哔哩哔哩音乐` @qist/0825+0827+dianshi |
| `csp_xyqhiker` | 40 | 36 | `csp_XYQHiker_影搜` / `csp_XYQHiker_哔嘀影视` / `csp_XYQHiker_兔小贝` @qist/XYQ.json |
| `csp_panwebshare` | 37 | 16 | `MoggV2` / `UcXmV2` / `QuarkLaBiV2` / `QuarkzzV2` @qist/367.json |

> `api=lib/drpy2.min.js` 是**同一个 drpy 引擎**，真正的差异全在 `ext`（指向 `./js/xxx.js`）与 `key`。按 api 去重会把 413 个源压成 1 个。

**聚合器的正确去重键**（建议）：`(type, 归一化 api, 归一化 ext, key)` 四元组；`ext` 为对象时按规范化 JSON 串参与哈希。若需更激进的合并，至少用 `(type, api, ext)` 三元组并保留 key 别名列表。

### 4.6 api 主机频次（top 8，反映代理依赖）

`catbox.n13.club` 62、`suoniapi.com` 17、`gh-proxy.net` 15、`cj.lziapi.com` 15、`gh-proxy.com` 15、`bfzyapi.com` 13、`www.agit.ai` 12、`jszyapi.com` 10 —— 前几名几乎都是 **GitHub 反代/图床/中转**，聚合器要预留"同一 api 多反代"的改写位。

---

## 5. 多仓格式（Q5）

### 5.1 全部多仓文件（7 个，177 条条目）

| 仓库 | 路径 | 包装键 | 条目字段 | 条数 | 解析模式 |
|---|---|---|---|---|---|
| `cliya` | `18.json` | `urls` | `url`+`name` | 16 | json5-clean（头部注释） |
| `cliya` | `cangku.json` | `urls` | `url`+`name` | 32 | json5-clean |
| `cliya` | `18duocang.json` | `storeHouse` | `sourceName`+`sourceUrl` | 4 | json5-clean |
| `cliya` | `duocang.json` | `storeHouse` | `sourceName`+`sourceUrl` | 17 | json5-clean |
| `qist` | `0707.json` | `urls` | `url`+`name` | 1 | raw |
| `tvbox` | `tvboxmuti.json` | `urls` | `url`+`name` | 14 | raw |
| `tvyuan` | `tvbox_multi.json` | `storeHouse` | `sourceName`+`sourceUrl` | 93 | raw |

字段结构（两套完全等价、只是键名不同）：

```json
{ "urls":       [ {"url": "https://…/xxx.json", "name": "🚀1-心魔在线"} ] }
{ "storeHouse": [ {"sourceName": "[32ms] 高天流云", "sourceUrl": "https://…/xxx.json"} ] }
```

- 条目只有 2 个键，**没有** `type`/`group`/`icon`/`desc`/`spider` 等扩展键。
- URL scheme：`https` 125 / `http` 51 / **无 scheme 1**（`http://www.饭太硬.cc/tv` 这类中文域名 + 相对路径 `./99188.json`）。
- `[<n>ms]` 前缀：**93 条全部来自 `tvyuan/tvbox_multi.json`**（即 `update.py` 写入的测速前缀），其余 6 个文件 84 条无前缀。→ 解析 `sourceName` 时必须剥前缀。
- 文件内重复 URL：`cliya/18.json` 16→15（`https://agit.ai/hu/hcr/raw/branch/master/1012.txt` 重复 2 次）、`tvyuan/tvbox_multi.json` 93→92（`https://9280.kstore.space/wex.json` 重复 2 次）。**写聚合器要按 URL 去重**。
- **多仓可嵌套**（5 处实测）：`cliya/18.json` 内含指向自身远端副本的 `https://agit.ai/wuheng42/TVBOXZY/raw/branch/main/18.json`；`cliya/18duocang.json` → `…/mengzehe/tvbox/main/18.json`；`cliya/duocang.json` → `…/mengzehe/tvbox/main/cangku.json`；`tvyuan/tvbox_multi.json` → `noimank/tvbox/…/tvboxmuti.json`（两个不同代理地址）。**展开多仓必须做环路检测 + 深度上限**。

### 5.2 相关但不同族的"多仓"

- `qist/cat/js/config_open*.json`（4 个，29 KB 级）与 `qist/cat/tjs/{open_config,18_open_config}.json`：顶层是 `{"video":{...},"read":{...},"comic":{...},"pan":{...},"color":...}`，是 **cat 系（另一 App 家族）的聚合配置**，内部才嵌 `video.sites`。不要当成 TVBox 多仓解析。
- `qist/0707.json` 是唯一使用**相对路径**的多仓条目（`{"url":"./99188.json","name":"高天流云 18+"}`），展开时需以文件所在目录（或仓库 raw 前缀）为基准。

### 5.3 订阅/直播清单格式（`qist/js/lf_live.txt` 自述）

```
#订阅名
地址(支持 m3u 订阅、tvbox 配置文件中 live 选项的直播地址订阅)
相对路径：以 ./ 开头相对本订阅文件；以 / 开头是存储卡根目录
```

---

## 6. 坏数据清单（Q6）

### 6.1 总览（268 个 JSON 候选 = 266 个 `.json` + 2 个 JSON 内容的 `.txt`）

| 指标 | 数量 | 比例 |
|---|---|---|
| 裸 `json.loads` 成功 | **221 / 268** | **82.5%** |
| 去注释 + 去尾逗号后成功 | **267 / 268** | **99.6%** |
| `raw_decode` 截断后再补 1 个 | **268 / 268** | **100%** |
| 含 BOM | 4 | 1.5% |
| 裸解析失败、需 JSON5 清洗 | **47** | 17.5% |
| 含尾逗号 `,]` / `,}` | 5 | 1.9% |
| 含 ≥40 字符 base64 片段 | 30 | 11.2%（见 §6.5 口径说明） |
| 另需跳过：UTF-16LE 文本 | 1 | `qist/live/辽宁联通.txt` |

### 6.2 47 个裸解析失败的文件（实测清单，`tools/out/14_verify.txt` 复核）

| 仓库 | 文件 | 首错位置 | 错误 | 去注释后可修 |
|---|---|---|---|---|
| `cliya` | `18.json` `18duocang.json` `cangku.json` `duocang.json`（4） | 1:1 | `Expecting value` | 4/4 可修（文件以 `//=====更新日期=====` 注释块开头） |
| `qist` | `XYQ.json` | 29:9 | `Expecting value` | 可修 |
| `qist` | `json/dj看球.json` | 5:5 | `Expecting property name` | **唯一不可修**（见 6.3，需 `raw_decode`） |
| `qist` | `XYQHiker/*`（**13**）、`xiaosa/XYQHiker/*`（**12**）、`XBPQ/bttt.json` `XBPQ/养生堂.json` `xiaosa/XBPQ/养生堂.json`、`json/{BSDM,DYG,JQYS,dmw,nmys,api黑木耳,企鹅直播,厂长影视}.json`（8）+ `json/dj看球.json`、`xiaosa/json/{BSDM,DYG,JQYS}.json`、`FTY/nmys.json`、`XYQBiu/网易CC直播.json` | 多为 16:5 / 17:5 / 3:5 | `Expecting property name enclosed in double quotes` | 全部可修（`//"DEBUG":"1"`、`//"规则名":...` 这类行内注释） |

（合计 4（cliya）+ 43（qist）= 47；`tvyuan` 的 4 个 JSON 全部裸解析通过。）

代表性首 200 字符：

- `cliya/18.json`：`"//=============成人单仓更新日期 2023/04/13=============\r\n\r\n//本成人单仓库在线链接：\r\n//https://ghproxy.net/…"`（注释头 + 后续对象）
- `qist/XYQHiker/可可影视.json`：`"{\r\n    \"规则名\": \"可可影视\",\r\n    //\"DEBUG\":\"1\",\r\n    \"规则作者\": \"香雅情\",…"`（对象内行内注释）
- `qist/XYQBiu/网易CC直播.json`：`"//写法思路来自biubiu影院，海阔视界，xpath筛选。\r\n//项目魔改至github开源仓库…\r\n{\r\n    //规则名\r\n    \"title\": \"网易CC直播\",…"`

### 6.3 唯一"清洗后仍失败"的文件：`qist/json/dj看球.json`

- 大小 11,112 B，UTF-8，顶层是一个合法的爬虫规则对象。
- 在第 1665 字符（字符索引，对应清洗后第 72 行）处**直接粘上整段 HTML**：`}\r\n\r\n<html><head>\r\n<meta charset="UTF-8">\r\n<meta name="renderer" content="webkit">…`
- `json.loads` 报 `Extra data: line 72 column 1 (char 1665)`；JSON5 清洗（去注释/尾逗号）**不解决**，因为它不是语法噪声而是尾部多余内容。
- **唯一统一兜底**：`json.JSONDecoder().raw_decode(cleaned)` 取第一个对象即成功 —— 47 个清洗后可解析的文件里 46 个用 `json.loads` 就够，但这 1 个必须 `raw_decode`。建议**一律用 `raw_decode`**。

### 6.4 BOM / 注释 / 尾逗号文件清单

- **BOM（4）**：`qist/cat/js/config_open99.json`、`qist/cat/js/config_open99_online.json`、`qist/cat/js/config_open_online.json`、`qist/xiaosa/json/哔哩视频.json`
- **带注释、必须 JSON5 清洗（47 = cliya 4 + qist 43）**：
  - cliya：`18.json` `18duocang.json` `cangku.json` `duocang.json`
  - qist 根：`XYQ.json`
  - `qist/XYQHiker/`（13）：996影视、七新影视、剧圈影视、可可影视、哔嘀影视、巴士动漫、播视童趣、来看影视、河马短剧、爱你短剧、玩偶哥哥、电影港、短剧屋
  - `qist/xiaosa/XYQHiker/`（12）：BT天堂、七新影视、九八影视、八号影视、剧圈影视、巴士动漫、来看影视、电影港、盒子影视、看看影视、短剧屋、骚火影视
  - `qist/json/`（9）：BSDM、DYG、JQYS、api黑木耳、dj看球、dmw、nmys、企鹅直播、厂长影视
  - `qist/xiaosa/json/`（3）：BSDM、DYG、JQYS；`qist/XBPQ/`（2）：bttt、养生堂；`qist/xiaosa/XBPQ/`（1）：养生堂
  - `qist/FTY/nmys.json`、`qist/XYQBiu/网易CC直播.json`
- **尾逗号（5）**：`qist/dianshi.json` `qist/jsm.json` `qist/tools/dianshi.json` `qist/tools/jsm.json` `qist/json/dj看球.json`

### 6.5 base64 文件（30 个，top 8）

口径：正则 `[A-Za-z0-9+/]{40,}={0,2}` 命中次数（`.json` + JSON 内容的 `.txt`；含 cliya 4 个注释头文件）。注意该正则也会命中**长 URL 路径/长 token**（`qist/live/*.txt`、`qist/json/pushshare.txt` 等 19 个纯文本文件同样命中），需人工确认是否真为 base64。

`tvyuan/tvbox_full.json` 172 处、`qist/cat/tjs/tv_config.json` 46、`qist/cat/tjs/open_config.json` 45、`qist/xiaosa/json/采集静态.json` 15、`qist/367.json` 14、`qist/0821.json` 12、`qist/0826.json` 12、`qist/xiaosa/api.json` 10（其后 `dianshi/jsm/fty` 各 9、`qist/json/market.json` 8、`tvyuan/tvbox_multi.json` 5）。

base64 出现的位置：`sites[].ext`（98 条，见 §3.4）、`lives[].url`（1 条）、以及 cat 系配置里的图标/脚本内联。

### 6.6 非 JSON 的编码/格式坑（同样会让聚合器崩）

| 文件 | 问题 | 处理 |
|---|---|---|
| `qist/live/辽宁联通.txt` | **UTF-16LE + BOM**（`\xff\xfe`），25,732 B | 先看 BOM 再选 codec，否则整文件乱码 |
| `qist/jar/fan.txt` | **扩展名 .txt，内容是 jar**（`PK\x03\x04`，含 dex） | spider 字段的值不能按扩展名判断类型 |
| `qist/listx.m3u` | 51,643 行 / 6.3 MB，单文件巨量条目 | 流式解析 |
| `qist/json/*share*.txt` | 网盘分享清单（`shareid?password=xxx 名称 1`），不是直播也不是 JSON | 按目录/字段数分流，勿当 live 解析 |
| `qist/lib/*.gz` `qist/json/*.db.gz` | 9 个 gz（含 10.8 MB sing-box） | 二进制资源，跳过 |

---

## 7. `qist` 的 257 个 JSON 到底是什么（Q7）

### 7.1 分类（`tools/out/08_q7.txt`）

| 类别 | 数量 | 目录分布 | 本质 |
|---|---|---|---|
| `tvbox-config` | **17** | 根 12、`cat/tjs` 2、`tools` 2、`xiaosa` 1 | 真正的 TVBox 配置（唯一可直接合并的部分） |
| `xyq-spider-rule` | **102** | `XYQHiker` 14、`XBPQ` 23、`xiaosa/XBPQ` 35、`xiaosa/XYQHiker` 14、`json` 10、`xiaosa/json` 6 | 单站爬虫规则（中文键 `规则名`/`首页列表数组规则`…），**不是配置** |
| `class-filters` | 37 | `json` 8、`xiaosa/json` 21、`FTY` 8 | `{"class":[...],"filters":{...}}` 分类片段 |
| `csp-site-rule` | 32 | `xiaosa/json` 32 | 单站规则变体（`简介`/`嗅探词`/`分类url`…） |
| `other-dict` | 35 | `json` 16、`XYQHiker` 6、`lib` 3、`XYQBiu` 2、`xiaosa/json` 5、`FTY` 1、`xiaosa/XYQHiker` 2 | singbox 配置、日志、杂项 |
| `json-array` | 14 | `json` 8、`js` 2、`xiaosa/json` 4 | 顶层数组（alist 站列表、课堂、直播数据） |
| `biliext` | 12 | `biliext` 7、`FTY` 2、`json` 2、`xiaosa/json` 1 | `{"cookie","classes","filter"}` B 站扩展 |
| `cat-open-config` | 6 | `cat/js` 4、`cat/tjs` 2 | 另一套 App schema（`video/read/comic/pan/color`） |
| `multi-urls` | 1 | 根 `0707.json` | 多仓索引 |
| `UNPARSEABLE` | 1 | `json/dj看球.json` | 见 §6.3 |

### 7.2 镜像关系（内容完全相同的文件）

- 266 个 `.json` 只有 **215 种不同内容**；**33 组重复、涉及 84 个文件**。
- `xiaosa/` 整体是仓库根的子集副本：`json/BSDM.json` == `xiaosa/json/BSDM.json` == `xiaosa/XYQHiker/巴士动漫.json` == `XYQHiker/巴士动漫.json`（4 份同内容，md5 `dc5642066e`）；`json/DYG.json` == `xiaosa/json/DYG.json` == `XYQHiker/电影港.json` == `xiaosa/XYQHiker/电影港.json`（`8d9deae7ca`）。
- 同 basename 出现在多目录的共 41 组：**28 组内容完全相同**（纯镜像），**13 组内容不同**（版本分叉）：`alist.json`（`js/` vs `json/` vs `xiaosa/json/`）、`dianshi.json`（根 vs `tools/`）、`jsm.json`（根 vs `tools/`）、`nmys.json`（`FTY/` vs `json/`）、`wogg.json`、`七新影视.json`、`农民影视.json`（3 份全不同）、`可可影视.json`（XBPQ vs XYQHiker）、`骚火影视.json`、`初中课堂/小学课堂/高中课堂/少儿教育`（biliext vs FTY vs xiaosa 三份不同）。
- 引用情况（按 basename 匹配 `sites/lives/parses` 的 `api`/`ext`/`url`）：`qist` 的 257 个 `.json` 里**只有 101 个**被某个配置引用过，其余 **156 个是孤儿**（规则库/资源库，供人工挑选，聚合器扫到它们只会增加噪声）。全仓 20 个配置共引用 160 个不同的 `.json` 文件名。

### 7.3 抽样：10 个不同子目录（每目录取首个）

| 路径 | 大小 | 类别 | 顶层键 / 内容判定 |
|---|---|---|---|
| `0707.json` | 102 B | multi-urls | `urls`（1 条，`./99188.json`）→ 多仓索引 |
| `FTY/Bili1.json` | 11,649 B | class-filters | `class`/`filters` → B 站分类片段 |
| `XBPQ/VidHub.json` | 612 B | csp-site-rule | `简介`/`嗅探词`/` 数组`/`线路数组`… → 单站爬虫规则（注意键名带前导空格 `" 数组"`） |
| `XYQBiu/88看球.json` | 1,913 B | other-dict | `title`/`author`/`UserAgent`/`class_url`/`filterdata`… → biubiu 系规则 |
| `XYQHiker/996影视.json` | 3,574 B | xyq-spider-rule | `规则名`/`规则作者`/`请求头参数`/`首页列表数组规则`… → XYQ 爬虫规则（需去注释） |
| `biliext/Bili.json` | 52,293 B | biliext | `cookie`/`classes`/`filter` → B 站扩展（cookie 指向 `clan://XYQTVBox/bilicookie.txt`） |
| `cat/js/config_open.json` | 29,140 B | cat-open-config | `video`/`read`/`comic`/`pan`/`color` → **另一 App 家族**的聚合配置 |
| `cat/tjs/18_open_config.json` | 3,560 B | cat-open-config | `video`/`read`/`pan`（内含 `video.sites`） |
| `js/alist.json` | 1,683 B | json-array | 顶层数组 9 项（`name`/`server`/`startPage`/`params`）→ alist 站清单 |
| `json/BSDM.json` | 3,250 B | xyq-spider-rule | `规则名=动漫巴士`…；**镜像**于 `xiaosa/json/BSDM.json`、`XYQHiker/巴士动漫.json`、`xiaosa/XYQHiker/巴士动漫.json` |
| `lib/singbox.json` | 4,234 B | other-dict | `log`/`dns`/`inbounds`/`outbounds`/`route` → **sing-box 代理配置**，与 TVBox 无关 |
| `tools/dianshi.json` | 23,373 B | tvbox-config | `spider`/`lives`/`wallpaper`/`danmaku`/`sites`… → 真配置（`spider=./jar/spider.jar;md5;c6985455…` 但**该 md5 的 jar 不存在**） |

**结论**：257 个 JSON 里只有 **17 个（6.6%）是配置**；其余是「爬虫规则库 + 分类片段 + 另一 App 的配置 + 代理/杂项」，且 `xiaosa/` 下有大面积镜像。聚合器不能"把仓里所有 JSON 当配置扫"。

---

## 8. `tvyuan/update.py` 审阅（Q8）

### 8.1 做法要点（330 行，单文件）

1. **源发现**：`curl https://tvbox.clbug.com/user.php`，正则 `data-url="([^"]+)"` 取 URL、`<td class="td-name">([^<]+)</td>` 取名称（第 140–145 行），组成 `sources`。
2. **测延迟**：对每个源 `curl -o /dev/null -w %{http_code}`，`2xx/3xx` 记为可用并记 ms，其余 99999 丢弃（第 150–163 行），按延迟升序。
3. **合并**：逐源抓取 → `parse_json`（去 BOM + 去尾逗号 + `strict=False` + 退化到首个 `{`…末个 `}` 截取）→ 收集 `sites`/`lives`/`parses`/`spider`，sites 用 **key** 去重，lives 用 **url** 去重，parses 用 **url** 去重；站点 `name` 被改写为 `[{lat}ms|{源名}] {原名}`（第 185–201 行）。
4. **采集站播放测速**：对 `type∈{0,1}` 且 api 为 http 的站，`ac=list` → 取 3 个 vod_id → `ac=detail` → 抽 m3u8 → 拉 master/media → 下载分片，`2xx` 且 >1000 B 记成功，最多 3 次尝试（第 3 次走 `CF_PROXY`），按 `(速度降序, 首帧升序)` 排序；`PINNED_APIS=["suoniapi.com","360zy.com"]` 强制置顶（第 204–232 行）。
5. **产出 3 个文件**：`tvbox_full.json`（全量，采集站在前按播放速度、爬虫站在后按源延迟，`spider` 取**出现次数最多的 jar**）、`tvbox_multi.json`（`storeHouse` + `[lat] 源名`，含索尼/360 的源整体置顶）、`tvbox.json`（前 10 个最快采集站，`name` 带 `[速度KB/s|延迟ms|稳/中/慢]` 前缀），另写 `sources.txt`（`[lat] name\nurl\n\n`）。
6. 由 `.github/workflows/update.yml` 每小时跑一次；所有网络访问走 `curl` 子进程。

### 8.2 缺陷（8 条，按严重度）

1. **只按 key 去重（第 185 行）**：`if not key or key in site_keys: continue`。实测 key 冲突 1119 条，且存在 4 组"同 key 不同 api"（`玩偶`→3 个 csp 类、`苹果`→3 个、`贱贱`→3 个、`push_agent`→3 个）——**先到的源赢，其余实现被静默丢弃**；同时 api 相同 key 不同的 992 条重复又被全部保留。去重键选错，两个方向同时出错。
2. **spider 取"出现次数最多的 jar"（第 271 行）**：`max(spider_jars, key=spider_jars.get)`。而 `csp_XXX` 站点强依赖**特定 jar 里的特定类**（实测 0821 只有 25/38 类在 `fan.txt` 内、0825 只有 76/83 在 `pg_upgraded.jar` 内）。合并后只留一个 spider，意味着大批 `csp_` 站点指向不存在的类 → 集体失效。产物实测：`tvbox_full.json` 的 spider 是 `http://oss4liview.moji.com/…/7b563c7039830e7c712e93f27fd2e102.jpg`（一个 **.jpg** 伪装的远程 jar），而该文件里有 **990 个 csp_ 站点**。
3. **name 被前缀污染且会累积（第 187 行）**：`f"[{lat}ms|{name}] {原名}"`。产物里可见 `[1434ms|金鹰] 🎬荐片┃影视`、`[33ms|我] 苹果`（源名被截断）——这些名字再被别的聚合器抓走时会**再叠一层前缀**，无幂等性。前缀里还塞了源名，源名一旦含 `|`/`]` 就无法解析。
4. **相对路径不重写**：`sites[].api = "./lib/drpy2.min.js"`、`ext = "./js/xxx.js"` 原样搬运，但 tvyuan 仓里**没有任何 js/lib 资源**——实测 `tvyuan/tvbox_full.json` 内 **180 条相对引用全部悬空**（`./lib/drpy2.min.js` 23 次、`./js/drpy.js` 3 次、`./js/有声小说吧.js` 2 次…）。同理 `spider` 的 `./jar/xxx` 也需按来源仓库 base 解析（第 35–46 行的 `resolve_spider/resolve_url` 只对 `./` 做域名拼接，从不改写 sites 内的相对 api/ext）。
5. **`parse_json` 不处理 `//` 注释（第 25–33 行）**：只去 BOM、尾逗号、`strict=False`。实测 268 个候选中 **47 个因注释裸解析失败**（cliya 全部 4 个、qist 41 个、tvyuan 自身 1 个）——这些源会被直接 `continue` 跳过，聚合结果静默缩水。`strict=False` 也放不进注释。
6. **源发现单点、无兜底（第 140–145 行）**：只抓 `tvbox.clbug.com/user.php` 一个页面 + 依赖两种 HTML 结构正则；页面改版/被墙即 0 源。没有备用页面、没有本地 `sources.txt` 回退、没有重试。同时 `data-url` 正则会把页面里所有 `data-url` 都当成源（不区分区块）。
7. **测速实现不可移植且极慢（第 121–124 行）**：用 `curl -o /dev/null`（Windows 无 `/dev/null`）、串行、每站 3 次尝试 × 3 视频 × 2 m3u8 × 8 分片；`build_url` 仅剥 `ac=list`，对 `?ac=detail`、`&wd=` 之类不处理（第 61–66 行）；`test_play_speed` 里 `stype` 只区分 0/1，type=4 的 php 采集站被当成 JSON 解析。
8. **无 schema 校验 / 无原子写 / 无去重后置校验**：`json.dump` 直接覆盖目标文件（第 273/290/313 行），中途异常会留下半截文件；产物不校验 `sites[].type` 是否 int（源里存在 `"3"`）、不校验 `spider` 是否可下载；`tvbox_multi.json` 也不按 `sourceUrl` 去重（实测 93 条里 1 条重复）。

---

## 9. 对聚合器的硬约束清单（可直接当实现 TODO）

1. **解析**：`decode()` 先判 BOM（UTF-8 BOM / **UTF-16LE BOM**）→ utf-8 → gbk/gb18030 回退；`strip_json5()` 去 `//`、`/* */`、尾逗号；最后用 `JSONDecoder().raw_decode()` 截断尾部垃圾。三层全过再判失败。
2. **配置识别**：`isinstance(obj, dict) and "sites" in obj`；不要扫目录里所有 JSON（qist 257 个里只有 17 个是配置）。
3. **sites 归一化**：`type` → `int()` 容错（有 `"3"`）；`playerType`/`timeout` 同；`ext` 多态处理（缺失 / str / 对象 / JSON 字符串 / base64 / URL）。
4. **去重键**：`(type, 归一化api, 归一化ext, key)`；至少 `(type, api, ext)` + 保留 key 别名。**禁止**只用 key 或只用 api。
5. **相对引用改写**：以"来源配置的 raw URL"为 base 把 `./x` 改写为绝对 URL（`qist` 内 220 条、`tvyuan` 内 180 条悬空即此问题）；`spider` 同理，且必须 **per-site 记录**。
6. **spider 绑定**：每个 site 记录 `source_spider`；不同 spider 的站点不能混在一个产物里（本地 9 个 jar 只覆盖 255/673 个 csp_ 类）。
7. **多仓展开**：同时认 `urls`（`url`/`name`）与 `storeHouse`（`sourceUrl`/`sourceName`）；剥 `[<n>ms]` 前缀；按 URL 去重；环路检测 + 深度上限（实测存在多仓指向自身远端副本）。
8. **lives 合并**：`url` 去重；支持 base64 url 解码；`#genre#` txt 与 m3u 两种格式分流；注意 `name,url,extra1,extra2` 的额外列。
9. **坏字段白名单**：`类型`/`playurl`/`url`/`click`/`type_flag`/`lang`/`proxy`/`ua` 这些非标字段不要丢，也不要当标准字段用；`headers`（复数）在 sites 层从未出现，只有 `header`。
10. **不写 name 前缀**：延迟/速度信息放进独立字段（如 `_lat`），否则二次聚合会累积前缀（tvyuan 已踩坑）。
11. **jar 判定按魔数不按扩展名**：`qist/jar/fan.txt` 是 jar；`…102.jpg` 也是 jar。
12. **原子写 + 产物自检**：先写 `.tmp` 再 `os.replace`；输出前校验 sites 数、type 分布、spider 可达性。

---

## 附录：脚本与输出对照

| 脚本（`tools/`） | 产出（`tools/out/`） | 回答 |
|---|---|---|
| `audit_common.py` | — | 共享解码/JSON5/分类/表格 |
| `audit_inventory.py` | `01_inventory.txt` | Q1 规模、目录、扩展名 |
| `audit_config.py` | `02_schema.txt`、`sites_all.json` | Q2 顶层 key、Q3 sites 形态 |
| `audit_dedup.py` | `04_dedup.txt` | Q4 去重与证明用例 |
| `audit_multi.py` | `05_multi.txt` | Q5 多仓格式 |
| `audit_bad.py` | `06_bad.txt`、`bad_rows.json` | Q6 坏数据 |
| `audit_extra.py` | `07_extra.txt` | Q1 直播/jar/js/py/ext 样本 |
| `audit_q7.py` | `08_q7.txt` | Q7 qist JSON 解剖与镜像 |
| `audit_sub.py` | `09_sub.txt` | Q2 子结构、悬空相对引用 |
| `audit_probe.py` | `10_probe.txt` | jar 内部、key 跨仓重叠 |
| `audit_spider.py` | `12_spider_match.txt` | Q3 每配置 csp_ 类覆盖 |

复现：`cd C:\Users\Nick\Documents\tvbox && py tools\audit_dedup.py`（各脚本独立，读 `sources/` 只读）。
