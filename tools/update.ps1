# TVBox 聚合器每日更新（Windows 计划任务调用）
# 流程：拉取代码 → 发现/抓取 → 去重/探测 → 生成 → 校验/报告 → 推送 dist 分支
param(
    [int]$MaxUrls = 8000,
    [int]$Budget = 1800,
    [switch]$NoPush,
    [switch]$PublishOnly
)

$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$logDir = Join-Path $root 'data\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("update-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function L([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Run([string]$what, [scriptblock]$sb) {
    L "→ $what"
    & $sb 2>&1 | ForEach-Object { Add-Content -Path $log -Value $_ -Encoding utf8 }
    $code = $LASTEXITCODE
    if ($code -ne 0) { L "  ! $what 退出码 $code" } else { L "  ✓ $what" }
    return $code
}

$env:PYTHONIOENCODING = 'utf-8'
$py = (Get-Command py -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { L '找不到 python/py，退出'; exit 1 }
L "python: $py"

$originUrl = ''
try { $originUrl = (git -C $root remote get-url origin) } catch {}
L "远端: $originUrl"

# 1) 同步代码（失败不阻塞，本地可能领先）
if (-not $PublishOnly) {
L '→ git pull'
git pull --ff-only -q 2>&1 | Add-Content -Path $log -Encoding utf8
}

# 2) 发现新仓库并只拉配置文件（需要网络与 git）
if (-not $PublishOnly) {
if ($env:GITHUB_TOKEN) {
    Run 'gh_discover' { & $py tools/gh_discover.py search }
} else {
    L '  跳过 gh_discover（无 GITHUB_TOKEN）'
}
Run 'gh_pull' { & $py tools/gh_pull.py --max-repos 80 --max-files 100 --workers 6 }

# 3) 主流水线
Run 'discover' { & $py -m tvh discover }
Run 'crawl'    { & $py -m tvh crawl --max-urls $MaxUrls --workers 64 --per-host 8 --timeout 12 --budget $Budget }
# 3.1 先抓上一轮结果做快照，供 build 后对比
if ($originUrl -match 'github\.com/([^/]+/[^/]+?)(\.git)?/?$') {
    $rawBase = 'https://raw.githubusercontent.com/' + ($matches[1] -replace '\.git$', '')
    try {
        Invoke-WebRequest "$rawBase/dist/index.json" -OutFile (Join-Path $root 'data\state\prev_index.json') -UseBasicParsing -TimeoutSec 120
        L "  已取上一轮快照 ← $rawBase/dist/index.json"
    } catch { L '  取上一轮快照失败（首次运行可忽略）' }
}
Run 'build'    { & $py -m tvh build --workers 96 --timeout 8 --jar-top 30 }

# 4) 校验与报告（校验失败只记日志，不阻断发布）
Run 'validate' { & $py tools/validate.py --all }
Run 'report'   { & $py tools/report.py }
Run 'diff'     { & $py tools/diff_report.py --out docs/changes.md }
}

$idx = Join-Path $root 'dist\index.json'
if (-not (Test-Path $idx)) { L '没有生成 dist/index.json，退出'; exit 1 }
$sites = (& $py -c "import json;print(len(json.load(open(r'$idx',encoding='utf-8'))['sites']))")
L "站点数: $sites"

# 5) 发布到 dist 分支（单提交 + 强推，仓库不会随时间膨胀）
if ($NoPush) { L '跳过发布（-NoPush）'; exit 0 }

$pub = Join-Path $env:TEMP ("tvh-pub-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $pub | Out-Null
Copy-Item (Join-Path $root 'dist\*.json') $pub -Force
Copy-Item (Join-Path $root 'docs\aggregation-report.md') (Join-Path $pub 'REPORT.md') -Force
if (Test-Path (Join-Path $root 'docs\changes.md')) { Copy-Item (Join-Path $root 'docs\changes.md') (Join-Path $pub 'CHANGES.md') -Force }

Push-Location $pub
try {
    $originUrl = (git -C $root remote get-url origin)
    git init -q -b dist 2>&1 | Add-Content -Path $log -Encoding utf8
    git remote add origin $originUrl 2>&1 | Add-Content -Path $log -Encoding utf8
    git -c user.name='tvbox-bot' -c user.email='tvbox-bot@users.noreply.github.com' add -A 2>&1 | Add-Content -Path $log -Encoding utf8
    $msg = "build: {0} / {1} sites" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ'), $sites
    git -c user.name='tvbox-bot' -c user.email='tvbox-bot@users.noreply.github.com' commit -q -m $msg 2>&1 | Add-Content -Path $log -Encoding utf8
    $push = git push --force origin dist:dist 2>&1
    $push | Add-Content -Path $log -Encoding utf8
    if ($LASTEXITCODE -eq 0) { L "✓ 已发布 dist 分支（$sites 站）" } else { L "! 发布失败: $($push -join ' ')" }
} finally {
    Pop-Location
    Remove-Item $pub -Recurse -Force -ErrorAction SilentlyContinue
}

# 6) 保留最近 30 份日志
Get-ChildItem $logDir -Filter 'update-*.log' | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 | Remove-Item -Force -ErrorAction SilentlyContinue

L '完成'
