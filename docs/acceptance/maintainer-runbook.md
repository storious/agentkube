# 维护者：候选构建与安装验证

这些是维护者的构建、安装和机器校验步骤，不交给体验者复制执行。
体验者使用 [体验菜单](README.md)；下列手动命令仅供维护者排查。
不要求 tag、GitHub Release、npm 发布或合入 `main`。

维护者先运行 `python docs/acceptance/build_candidate.py`，再运行
`python docs/acceptance/experience.py --prepare`。后者复用本地候选物，通过
Agulater 安装 runtime、Skills、Plugins 和 specialist，准备持久化体验目录。
再次准备不会重置会话或已修改的练习文件；日常打开菜单不会触发构建或安装。
准备脚本使用 Python 标准库 argparse/subprocess/json 与现有 Agulater 命令，
没有独立的包管理、终端渲染或调度实现。

额外的故障注入、账本深检和公开证据规则见
[维护者参考](maintainer-reference.md)。历史运行不能代替本次验收。

## 0. 发布边界

在本清单全部通过且你明确批准前：

- 不创建或移动 tag；
- 不创建 GitHub Release，不发布 `agulater`；
- 不把 `dev` 推进 `main`；
- 不把当前候选称为已发布版本。

## 1. 前置条件

在 AgentKube 根目录用 PowerShell 7 执行。构建三个仓库的本地候选物需要
Rust/Cargo、Bun 1.4+、Python 3 和 Git；Bun 只负责从 TypeScript 源码生成
Agulater 独立程序和可选 npm 包。第 3、4 节运行候选程序时不能依赖 Bun、
Node.js 或 npm。模型连接需要：

- `DEEPSEEK_API_KEY`；
- **GLM Coding Plan** 的 `GLM_API_KEY`；
- 可完成官方登录的 Codex CLI/Desktop（第 7 节要求发布所有者亲自登录，不能只沿用已有状态）；
- 多 Agent 本地 worker 使用的 `AGUL_ACCEPTANCE_LOCAL_ENDPOINT` 和
  `AGUL_ACCEPTANCE_LOCAL_MODEL`。这两个值只存在于当前终端和临时 fixture，
  不写入仓库。

```powershell
cargo --version
bun --version
python --version
git --version
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
  throw "DEEPSEEK_API_KEY is missing"
}
if ([string]::IsNullOrWhiteSpace($env:GLM_API_KEY)) {
  throw "GLM_API_KEY for Coding Plan is missing"
}
if ([string]::IsNullOrWhiteSpace($env:AGUL_ACCEPTANCE_LOCAL_ENDPOINT)) {
  throw "AGUL_ACCEPTANCE_LOCAL_ENDPOINT is missing"
}
if ([string]::IsNullOrWhiteSpace($env:AGUL_ACCEPTANCE_LOCAL_MODEL)) {
  throw "AGUL_ACCEPTANCE_LOCAL_MODEL is missing"
}
$LocalUri = [uri]$env:AGUL_ACCEPTANCE_LOCAL_ENDPOINT
if (-not $LocalUri.IsAbsoluteUri -or
    $LocalUri.Scheme -notin @("http", "https")) {
  throw "AGUL_ACCEPTANCE_LOCAL_ENDPOINT must be an absolute HTTP(S) URL"
}
```

- [ ] 所有命令均打印版本。
- [ ] 两个 key 与两个本地 worker 变量存在，且终端没有打印其内容。
- [ ] 三仓均在 `dev`，没有无关改动。

## 2. 生成本地三仓候选包

脚本会编译 Agul、生成本机发布压缩包、把 Agulater 编译为独立程序及本机
Release 压缩包、打包可选 npm artifact、写本地 Runtime 索引，并记录版本、
commit、dirty 状态和 SHA-256。Bun 只在这一构建步骤运行；两个面向用户的
程序都没有外部 Bun 依赖。脚本不会发布任何内容。

```powershell
python docs/acceptance/build_candidate.py
$CandidateRoot = Resolve-Path .tmp/acceptance-candidate
$Candidate = Get-Content (Join-Path $CandidateRoot "candidate.json") -Raw |
  ConvertFrom-Json
$Candidate | ConvertTo-Json -Depth 8
```

- [ ] 版本为 Agul `0.6.0-rc.1`、Agulater `0.2.1-rc.2`、AgentKube
  `0.2.3-rc.1`。
- [ ] 清单记录三个精确 commit，以及 Agul archive、Agulater standalone、
  Agulater release archive、可选 npm 包四个 artifact hash。
- [ ] 最终验收时三项 `dirty` 都是 `false`。
- [ ] Agul ZIP 内有 `agul.exe`、`LICENSE`、`THIRD_PARTY_NOTICES.md`、
  `Cargo.lock`、`README.md`、`CONTRIBUTING.md`、`docs/`、`schemas/`
  和当前 GIF。
- [ ] Agulater release archive 以版本化目录为顶层，内有 standalone、
  `LICENSE` 和 `THIRD_PARTY_NOTICES`。

开发中可以测试 dirty bundle，但不能批准它发布。

## 3. 先验证不依赖 Bun 的 Agul

直接解压候选包并运行 Agul；这才是最短的用户路径：

```powershell
$Standalone = Join-Path $CandidateRoot "standalone"
Expand-Archive $Candidate.artifacts.agul.path $Standalone -Force
$Agul = (Get-ChildItem $Standalone -Recurse -Filter agul.exe |
  Select-Object -First 1).FullName
& $Agul --version
```

- [ ] 不安装 Bun、Node.js 或 Agulater 也能运行 `agul.exe`。
- [ ] 解压目录同时包含 `LICENSE`、`THIRD_PARTY_NOTICES.md`、`Cargo.lock`、
  `README.md`、`CONTRIBUTING.md`、`docs/`、`schemas/` 和当前 GIF。

## 4. 验证无 Bun 的 Agulater 生命周期

下面隔离用户 home 和 Agul prefix，并临时从 `PATH` 移除 Bun、Node.js、npm
和机器里可能已有的 Agulater。它用本地 `gh` 替身让正式安装脚本消费候选
release archive；不访问 GitHub，也不绕过 archive 布局直接运行裸程序。

```powershell
$CleanRoot = Join-Path $CandidateRoot ("clean-user-" + [guid]::NewGuid().ToString("N"))
$CleanHome = Join-Path $CleanRoot "home"
$InstallDir = Join-Path $CleanRoot "agulater-bin"
$AgulPrefix = Join-Path $CleanRoot "agul"
New-Item -ItemType Directory -Force $CleanHome | Out-Null
$OriginalPath = $env:Path
$OriginalHome = $env:HOME
$OriginalUserProfile = $env:USERPROFILE
$OriginalAcceptanceArchive = $env:AGULATER_ACCEPTANCE_ARCHIVE
$env:AGULATER_ACCEPTANCE_ARCHIVE = $Candidate.artifacts.agulater_release.path

if (-not $IsWindows) {
  $Shell = (Get-Command sh -ErrorAction Stop).Source
  $ToolBin = Join-Path $CleanRoot "system-tools"
  New-Item -ItemType Directory -Force $ToolBin | Out-Null
  foreach ($Name in @("uname", "tar", "gzip", "mktemp", "mkdir", "cp", "chmod", "rm")) {
    $Source = (Get-Command $Name -ErrorAction Stop).Source
    New-Item -ItemType SymbolicLink -Path (Join-Path $ToolBin $Name) `
      -Target $Source | Out-Null
  }
}

try {
  $env:HOME = $CleanHome
  $env:USERPROFILE = $CleanHome
  $env:Path = if ($IsWindows) {
    "$env:SystemRoot\System32;$env:SystemRoot"
  } else {
    $ToolBin
  }
  if (Get-Command bun,node,npm,agulater -ErrorAction SilentlyContinue) {
    throw "language runtime or global Agulater leaked into standalone smoke"
  }

  if ($IsWindows) {
    function global:gh {
      if ($args[0] -eq "auth" -and $args[1] -eq "status") {
        $global:LASTEXITCODE = 0
        return
      }
      $DirIndex = [Array]::IndexOf($args, "--dir")
      if ($DirIndex -lt 0 -or $DirIndex + 1 -ge $args.Count) {
        $global:LASTEXITCODE = 2
        return
      }
      Copy-Item -LiteralPath $env:AGULATER_ACCEPTANCE_ARCHIVE `
        -Destination $args[$DirIndex + 1]
      $global:LASTEXITCODE = 0
    }
    & (Resolve-Path "agulater/scripts/install.ps1") `
      -Version $Candidate.versions.agulater `
      -InstallDir $InstallDir `
      -SetupHome $CleanHome `
      -NoModifyPath
    $Agulater = Join-Path $InstallDir "agulater.exe"
  } else {
    $Installer = (Resolve-Path "agulater/scripts/install.sh").Path
    $InstallCommand = @'
gh() {
  if [ "$1 $2" = "auth status" ]; then return 0; fi
  destination=
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--dir" ]; then shift; destination=$1; fi
    shift
  done
  cp "$AGULATER_ACCEPTANCE_ARCHIVE" "$destination/"
}
. "$1" --version "$2" --install-dir "$3" --home "$4"
'@
    & $Shell -c $InstallCommand acceptance `
      $Installer $Candidate.versions.agulater $InstallDir $CleanHome
    $Agulater = Join-Path $InstallDir "agulater"
  }
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Agulater)) {
    throw "Agulater release archive installation failed"
  }

  & $Agulater --version
  & $Agulater setup user --if-missing --home $CleanHome

  $Install = & $Agulater runtime install `
    --channel next `
    --url $Candidate.artifacts.runtime_index `
    --prefix $AgulPrefix `
    --json | ConvertFrom-Json

  & $Agulater runtime status --prefix $AgulPrefix --json
  & $Install.shim --version
  $Agul = $Install.shim
  $env:AGUL_SUBAGENT_BINARY = $Install.executable

  & $Agulater runtime update `
    --channel next `
    --url $Candidate.artifacts.runtime_index `
    --prefix $AgulPrefix `
    --json
} finally {
  $env:Path = $OriginalPath
  $env:HOME = $OriginalHome
  $env:USERPROFILE = $OriginalUserProfile
  $env:AGULATER_ACCEPTANCE_ARCHIVE = $OriginalAcceptanceArchive
  if ($IsWindows) {
    Remove-Item Function:\global:gh -ErrorAction SilentlyContinue
  }
}
```

- [ ] Bun、Node.js、npm 和全局 Agulater 均不在这段测试的命令路径中。
- [ ] 正式 installer 从候选 `agulater_release` archive 安装，而不是直接运行
  `artifacts.agulater` 裸程序。
- [ ] standalone `agulater --version` 是候选版。
- [ ] `setup user --if-missing` 创建 `$CleanHome/.agents` 并注册 AgentKube Catalog，但没有
  擅自下载扩展。
- [ ] `runtime status` 为 `installed: true` 且版本准确。
- [ ] 当前终端直接运行返回的 `shim` 成功。
- [ ] Windows 同目录没有旧 `agul.exe` 遮蔽受管 `agul.cmd`。
- [ ] 再运行一次 `runtime update --prefix ...` 后仍可用。

公开后，普通 Agulater 用户也走独立安装脚本或压缩包；npm/Bun 只是一条可选
兼容路径。发布前直接验证本地 standalone，避免“为了验收先发布”的循环。

## 5. DeepSeek minimal 模式与 TUI

不要加载 AgentKube：

```powershell
& $Agul chat --workspace (Join-Path $PWD "agul") `
  --provider deepseek `
  --reasoning-effort high
```

要求它读取 `README.md`、执行一个无副作用的仓库命令，并用一个 Markdown 标题和
短列表回答。

- [ ] 进入独立 alternate-screen 页面，退出后恢复原 shell。
- [ ] 首条消息上方、回答与输入框之间都有留白。
- [ ] 用户消息、推理、最终回答、工具名、工具参数样式明确不同。
- [ ] 标题、列表、行内代码、代码块有 Markdown 高亮。
- [ ] 输入框四周内缩；状态栏和输入框对齐，不贴终端边缘。
- [ ] 输出过程中状态栏一直存在，并显示模型、强度、turns、tools、tokens、KV、
  时间和可用时的已用/总上下文。
- [ ] 推理或工具运行时输入框仍可编辑。
- [ ] 输入 `/`、`@` 立刻出现命令和 Skill 菜单。
- [ ] steer 输入可中断并续接；`/stop` 和 Ctrl+C 可只停止当前 turn。
- [ ] PageUp/PageDown 保留滚屏；调整窗口大小不破版。
- [ ] `/exit` 后只打印简短 saved/resume 提示。
- [ ] minimal 模式仅有 `read`、`write`、`edit`、`shell` 四个内置工具。

如果输入框在流式输出时消失、页面退回旧 inline 布局或阅读明显压迫，直接判定
阻塞并截图，不要“先适应”。

## 6. GLM Coding Plan

公开的 GLM 入口只有一个：`glm` 就是 Coding Plan。普通 GLM API 不属于本验收。

先看真实 TUI：

```powershell
& $Agul chat --workspace (Join-Path $PWD "agul") `
  --provider glm `
  --reasoning-effort high
```

要求精确回复 `GLM_CODING_READY`，查看 `/usage` 后 `/exit`。再锁定机器契约：

```powershell
$Glm = & $Agul chat `
  --workspace (Join-Path $PWD "agul") `
  --provider glm `
  --reasoning-effort high `
  --prompt "Do not use tools. Reply exactly GLM_CODING_READY." `
  --json | ConvertFrom-Json

if (-not $Glm.ok) { throw "GLM Coding Plan request failed" }
if ($Glm.model -ne "glm-4.7") { throw "GLM route did not use glm-4.7" }
if ($Glm.billing -ne "subscription_quota") {
  throw "GLM request was not recorded as subscription quota"
}
$Bad = @($Glm.usage.entries | Where-Object {
  $_.provider -ne "glm" -or
  $_.origin -ne "https://open.bigmodel.cn" -or
  $_.unpriced_reason -ne "subscription_quota" -or
  $null -ne $_.cost -or
  $null -ne $_.price_ref
})
if ($Bad.Count -gt 0) { throw "GLM Usage Ledger contract changed" }
```

- [ ] 请求真实走通 Coding Plan。
- [ ] 模型为 `glm-4.7`，billing 为 `subscription_quota`。
- [ ] token/KV 被记录，cost 与 price reference 为 null。
- [ ] 没有运行普通 GLM 余额/API 诊断。

## 7. ChatGPT 账户与真实 Web Search

```powershell
& $Agul account status
# 本次候选必须由发布所有者亲自执行一次；不能只用已有登录跳过：
& $Agul account login
& $Agul account status

& $Agul chat --workspace (Join-Path $PWD "agul") `
  --engine codex `
  --reasoning-effort high
```

询问一个必须联网确认的当前事实，并要求给出两个来源链接。

- [ ] 使用官方账户流程，没有索要 API key。
- [ ] 发布所有者在本次验收中亲自完成登录，随后状态显示可用的 ChatGPT/Codex 额度。
- [ ] 回答含真实 Web Search 返回的来源 URL。
- [ ] 计费显示 ChatGPT/Codex quota，不伪造 API 费用。
- [ ] 账户会话与 native 会话容易区分。

## 8. 不记 ID 的会话恢复

在同一 workspace 至少保存两个会话：

```powershell
& $Agul chat --workspace (Join-Path $PWD "agul") --continue
& $Agul chat --workspace (Join-Path $PWD "agul") --resume
```

- [ ] `--continue` 自动续接该 workspace 最近会话。
- [ ] `--resume` 给出人类可读选择器，不要求复制 ID。
- [ ] 可见历史、模型路由、usage 和续接前缀跨进程保留。
- [ ] 空会话和 ephemeral 会话不污染选择器。

## 9. 把 AgentKube 扩展装进 master 根

新建根 Agent，并安装当前本地源码。不要把 root starter 错装成嵌套 Package：

```powershell
$Master = Join-Path $CandidateRoot "master"
& $Agulater create self-maintainer --path $Master
& $Agulater add (Resolve-Path plugins/coordinator) `
  --type plugin --name coordinator --path $Master
& $Agulater add (Resolve-Path plugins/web-search) `
  --type plugin --name web-search --path $Master
foreach ($Role in @(
  "repository-scout",
  "focused-tester",
  "docs-editor",
  "short-patcher"
)) {
  & $Agulater add (Resolve-Path "agents/$Role/.agents") `
    --type package --name $Role --path $Master
}
$LocalContextWindow = if (
  [string]::IsNullOrWhiteSpace($env:AGUL_ACCEPTANCE_LOCAL_CONTEXT_WINDOW)
) { 32768 } else { [int]$env:AGUL_ACCEPTANCE_LOCAL_CONTEXT_WINDOW }
$LocalMaxConcurrency = if (
  [string]::IsNullOrWhiteSpace($env:AGUL_ACCEPTANCE_LOCAL_MAX_CONCURRENCY)
) { 1 } else { [int]$env:AGUL_ACCEPTANCE_LOCAL_MAX_CONCURRENCY }
$LocalTimeoutSeconds = if (
  [string]::IsNullOrWhiteSpace($env:AGUL_ACCEPTANCE_LOCAL_TIMEOUT_SECONDS)
) { 600 } else { [int]$env:AGUL_ACCEPTANCE_LOCAL_TIMEOUT_SECONDS }
if ($LocalContextWindow -le 0 -or
    $LocalMaxConcurrency -le 0 -or
    $LocalTimeoutSeconds -le 0) {
  throw "local Pool numeric settings must be positive"
}

$Pools = [ordered]@{
  format = "agulater/pools/v2"
  default_pool = "local-default"
  pools = @(
    [ordered]@{
      id = "local-default"
      engine = "native"
      description = "Maintainer-supplied local worker"
      labels = @("local", "bounded")
      provider = "openai-compatible"
      endpoint = $env:AGUL_ACCEPTANCE_LOCAL_ENDPOINT
      model = $env:AGUL_ACCEPTANCE_LOCAL_MODEL
      reasoning_effort = "medium"
      context_window = $LocalContextWindow
      capabilities = @("read", "write", "edit", "shell")
      max_concurrency = $LocalMaxConcurrency
      request_timeout_seconds = $LocalTimeoutSeconds
    },
    [ordered]@{
      id = "deepseek-subagent"
      engine = "native"
      description = "DeepSeek API worker"
      labels = @("remote", "general")
      provider = "deepseek"
      endpoint = "https://api.deepseek.com/chat/completions"
      model = "deepseek-v4-flash"
      api_key_env = "DEEPSEEK_API_KEY"
      reasoning_effort = "high"
      context_window = 32768
      capabilities = @("read", "write", "edit", "shell")
      max_concurrency = 1
      request_timeout_seconds = 600
    },
    [ordered]@{
      id = "codex-account"
      engine = "codex"
      description = "ChatGPT account-backed worker"
      labels = @("account", "general")
      capabilities = @("read", "write", "edit", "shell")
      max_concurrency = 1
      request_timeout_seconds = 900
    }
  )
}
$Pools | ConvertTo-Json -Depth 8 |
  Set-Content (Join-Path $Master ".agents/pools.json") -Encoding utf8
& $Agulater prepare --path $Master

$MasterLaunch = Join-Path $Master ".agents/runtime/launch.json"
Get-Content $MasterLaunch
Get-Content (Join-Path $Master ".agents/runtime/specialists.json")
Get-Content (Join-Path $Master ".agents/runtime/pools.json")

$PatchFixture = Join-Path $CandidateRoot "repair-fixture"
New-Item -ItemType Directory -Force $PatchFixture | Out-Null
@'
def add(left, right):
    return left - right
'@ | Set-Content (Join-Path $PatchFixture "calculator.py") -Encoding utf8
@'
import unittest
from calculator import add

class CalculatorTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

if __name__ == "__main__":
    unittest.main()
'@ | Set-Content (Join-Path $PatchFixture "test_calculator.py") -Encoding utf8
```

- [ ] root launch 有 Coordinator 和 Web Search。
- [ ] registry 有四个 specialist。
- [ ] runtime pools 有 `local-default`、`deepseek-subagent`、`codex-account`。
- [ ] 仓库和公共 starter 没有维护者网络地址；临时 Pool 只由当前终端的
  `AGUL_ACCEPTANCE_LOCAL_*` 变量生成。
- [ ] Plugins 额外只要求 PATH 中有 Python 3。

用 GLM Coding Plan 启动 master：

```powershell
& $Agul chat `
  --workspace $PWD `
  --launch $MasterLaunch `
  --provider glm `
  --reasoning-effort high `
  --timeout-seconds 600
```

依次：

1. `/skills` 检查 prepared 与 System Skills。
2. 让 `web_open` 打开 `https://example.com/`，不要配置搜索引擎。
3. 若有 `SEARXNG_URL` 或 `TAVILY_API_KEY`，再让 `web_search` 搜索并打开一个结果。

- [ ] `web_open` 无搜索服务也能用。
- [ ] 只有 `web_search` 才要求 SearXNG/Tavily。
- [ ] Plugin 只追加紧凑进度行，不重写对话。

## 10. 真实本地 + DeepSeek 子 Agent

本地服务可能需要冷启动；在配置的
`AGUL_ACCEPTANCE_LOCAL_TIMEOUT_SECONDS` 超时前不要误判失败。临时 Pool 将本地
worker 的默认推理强度设为 `medium`；不要为了缩短等待临时降回 `low`。输入：

```text
/agent {"tasks":[{"id":"local-read","specialist":"repository-scout","pool":"local-default","task":"Read README.md and report the project boundary with path evidence.","paths":["README.md"]},{"id":"deepseek-read","specialist":"repository-scout","pool":"deepseek-subagent","task":"Read catalog/README.md and report the Catalog boundary with path evidence.","paths":["catalog/README.md"]}]}
```

再输入下面的自然语言要求；master 必须只调用一次 `delegate_tasks`：

```text
只调用一次 delegate_tasks：先让 local-default 的 repository-scout 诊断 .tmp/acceptance-candidate/repair-fixture 中失败的加法测试，再让 deepseek-subagent 的 short-patcher 只修复该目录的 calculator.py。最后由你查看该 fixture 的 diff，并在该目录运行 python -m unittest -v 复核后再回答。
```

这个 fixture 已在第 9 节创建，不会改动产品源码。

- [ ] 两个 child 有不同 session/task/specialist/pool 和正确 parent attribution。
- [ ] read 可并发，write 仍串行。
- [ ] 成功 child 都以合法 `agul/handoff/v1` 收尾。
- [ ] master 自己复核 patch 与测试后才回答。
- [ ] 本地 usage 保留真实 endpoint 且不定价；DeepSeek 使用版本化 USD 价卡；
  GLM master 仍是 subscription quota。
- [ ] `/stop` 能终止 coordinator/child，已完成 usage 不丢，输入框不消失。

## 11. 最终记录

| 项目 | 结果 |
| --- | --- |
| candidate manifest 与 SHA | |
| AgentKube commit | |
| Agul commit | |
| Agulater commit | |
| Windows 隔离安装 | |
| DeepSeek minimal/TUI | |
| GLM Coding Plan | |
| ChatGPT + live Web Search | |
| continue/resume | |
| AgentKube Web Open/Search | |
| 本地 + DeepSeek 委派 | |
| 阻塞截图或备注 | |

所有必选项通过且没有未解决的可用性阻塞，才可以明确批准发布。批准后再推进
`main`、创建不可变 tag、发布 artifacts/package，并从全新环境补一次真实公网下载
smoke；发布后的 smoke 不能倒过来替代本次亲自体验。
