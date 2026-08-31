# 三仓复杂模块工程库审计

审计日期：2026-08-30

## 目的与判断原则

本报告审计了 Agul（Rust）、Agulater（TypeScript/Bun）和 AgentKube
（Python 插件）的当前实现，目标是找出已经有成熟工程库、继续自研只会增加维护成本的
部分。它不是通用依赖推荐清单，也不建议因为“有库可用”就迁移。

判断遵循四条规则：

1. 通用协议、文件事务、版本规则和正文抽取优先交给成熟库。
2. Agul 的流式 usage、版本化价卡、ARI、插件协议和三仓职责边界属于产品语义，不能被
   通用库稀释。
3. 替换必须减少代码和故障面；只把自研代码换成一层更厚的适配器，不算收益。
4. 用户可见行为、跨平台表现和账单可追溯性优先于“技术栈统一”。

本文中的“立即替换”指适合进入下一个维护批次，仍须先锁定现有行为测试；“评估后替换”
指先做隔离实验，达到验收门槛才迁移；“保留自研”指当前产品语义与迁移成本明显高于库的
维护收益。

## 总结

| 模块 | 当前实现 | 结论 | 推荐工程库或平台能力 | 核心理由 |
| --- | --- | --- | --- | --- |
| Agul TUI / 终端输入 | Ratatui + Crossterm + ratatui-textarea，外加产品胶水 | **保留现有栈** | 已采用正确的成熟库 | 当前问题不是“没用库”；再次换框架只会重做事件、滚屏和编辑器适配 |
| Agul Markdown / 高亮 | pulldown-cmark + Syntect | **保留** | 已采用成熟库 | 自研只剩终端样式映射，属于必要胶水 |
| Agul HTTP/provider | Reqwest + provider 方言映射 | **保留** | Reqwest | DeepSeek、GLM、本地 OpenAI-compatible 与 Codex usage 语义不能交给单一厂商 SDK |
| Agul HTTP 测试服务 | 固定响应采用库，字节级协议测试保留 raw socket | **分层采用** | `httpmock` 0.8.3 | 普通请求匹配和响应不再手写 HTTP；chunk、断流、取消时序仍需精确控制连接 |
| Agul SSE framing | 自研逐字节 SSE decoder | **评估后替换** | `eventsource-stream` | 标准 framing 可交给库，但取消、`[DONE]` 和失败时 partial usage 必须保持 |
| ARI JSON-RPC | 换行分隔 JSON-RPC 2.0 小实现 | **保留** | 暂不引入 `jsonrpsee` | 当前只有 stdio、串行请求和通知；库会比协议外壳更重 |
| Codex app-server transport | 类 JSON-RPC 的专用协议 | **保留** | 无通用替代 | 对端消息没有 JSON-RPC 2.0 必需的 `jsonrpc` 字段，不能硬套通用库 |
| 会话 JSON 覆盖写 | `atomic-write-file` 薄适配器 | **已采用** | `atomic-write-file` 0.3.1 | 提交前保留旧 session，提交后原子切换 |
| 账单同步状态覆盖写 | 复用同一覆盖写适配器 | **已采用** | `atomic-write-file` 0.3.1 | 仅覆盖 `sync.json`；价卡不可覆盖创建保持原语义 |
| usage ledger / 版本化价卡 | 定点金额、逐响应归属、自研格式 | **保留自研** | 无通用替代 | 这是 Agul 的可追溯计费能力，不是通用记账 CRUD |
| 插件发现 | 显式根目录或一层子目录 `plugin.json` | **保留自研** | 无需 `walkdir` 或插件框架 | 发现语义有意保持浅层、可预测；库不会替代错误报告和产品约束 |
| 插件进程协议 | 子进程 + NDJSON invocation/event | **保留自研** | 无通用替代 | 语言无关的进程边界是设计目标，动态链接式插件框架反而改变架构 |
| 子进程树控制 | Unix process group + Windows Job Object 自研 | **评估后替换平台层** | `command-group` | 可删除 Win32 `unsafe` 和外部 `kill` 胶水；输出截断、取消和事件流仍保留 |
| 核心“沙箱” | 工作区工具与进程运行约定 | **不引入大而全库** | 未来保持可选插件边界 | 当前没有一个跨平台库能无损替代 Agul 的轻量运行契约 |
| launch/config 发现 | 当前目录、祖先、用户级目录的确定性优先级 | **保留自研** | 无需 Figment/config 框架 | 这是很小的产品优先级规则，不是复杂配置合并系统 |
| Agulater Schema 校验 | `package-v2` 使用自包含 Ajv standalone；其余格式暂保留原解析器 | **试点已完成** | Ajv 2020 strict + standalone | Package 结构规则来自正式 Schema；文件、路径落点、依赖与唯一性仍由业务层判断 |
| Agul / AgentKube Schema 校验 | Serde 类型与 Python 手写校验 | **Rust 保留类型；Python 评估后替换** | Rust `jsonschema`（测试/动态文档）、Python `jsonschema` | Rust 类型有价值；Python 可在依赖交付明确后删掉重复结构校验 |
| Agulater SemVer | Bun 1.4 内置 order/satisfies 薄适配器 | **已采用** | `Bun.semver` | 已删除手写 prerelease 排序和 range 数学，无新依赖 |
| Agulater 自身分发 | 各平台单文件可执行程序 | **已采用** | `bun build --compile` | Bun 官方编译器把源码、依赖和运行时打入发布物；普通用户无需 Bun/Node/npm，不自造 JS 启动器 |
| Agulater 下载 | `fetch`、`git`、`gh` | **保留** | 已使用成熟引擎 | 当前代码主要是来源选择和版本验证，换下载库收益很小 |
| Agulater 解压 | 调用系统 `tar` 处理 zip/tar.gz | **评估后替换 tar/tgz** | `Bun.Archive` | 可移除系统 tar 依赖，但 Bun.Archive 不支持 zip，须先统一发布资产 |
| Agulater 目录安装 | 同目录 staging + backup + rename + rollback | **保留自研** | 无明确更优通用库 | 这是包布局和回滚事务；成熟文件写库只能替代单文件，不能替代目录切换 |
| Agulater runtime 激活 | executable + launcher + `current.json` 提交 | **已采用跨进程锁** | `proper-lockfile` 4.1.2 | 下载解包不占锁；最终本地发布串行，提交失败恢复旧 launcher，不自研 stale-lock 状态机 |
| AgentKube `web_open` HTML 抽取 | 自研 `HTMLParser` 收集所有块文本 | **高优先级评估后替换** | Trafilatura | 当前会把导航、页脚等样板文本一起交给模型；正文抽取已有成熟实现 |
| AgentKube Web HTTP | Python `urllib` | **保留；出现需求再换** | HTTPX 仅作后备 | `urllib` 本身是成熟标准库；目前请求量小，换库不会自动改善正文质量 |
| AgentKube coordinator | ThreadPoolExecutor + subprocess + ARI | **保留自研调度** | Python 标准库已足够 | ARI、prepared specialist、usage 汇总是三仓协作语义，通用 agent 框架会重复运行时 |

## 1. Agul TUI 与终端输入

### 当前实现

Agul 已在 [Cargo.toml](../../agul/Cargo.toml#L20-L36) 固定使用
Ratatui 0.30.2、Crossterm 0.29、ratatui-textarea 0.9.2、pulldown-cmark 和
Syntect。浮动输入区使用 Ratatui 的
[`Viewport::Inline` 与 `insert_before`](../../agul/src/commands/chat/workbench/ui.rs#L96-L190)，
编辑器状态、选择、撤销/重做和软换行由
[ratatui-textarea 承担](../../agul/src/commands/chat/workbench/editor.rs#L106-L142)，
自研部分主要处理 `/`、`@`、历史草稿、补全菜单和 grapheme 边界。

这与 Ratatui 官方给 inline CLI 的设计一致：官方文档明确说明 inline viewport 用于“正常
终端输出在上、实时 UI 在下”，`insert_before` 用于把完成输出插到实时区域上方；开启
`scrolling-regions` 时可避免清空重画实时区域（[Ratatui `Terminal`
文档](https://docs.rs/ratatui/latest/ratatui/struct.Terminal.html#inline-viewport)）。
ratatui-textarea 已提供多行编辑、Emacs 风格操作、undo/redo、软换行、文本选择和鼠标滚动
（[官方 crate 文档](https://docs.rs/ratatui-textarea/latest/ratatui_textarea/)）；
Crossterm 已提供键盘、paste、resize 与 poll/read 事件模型
（[官方事件文档](https://docs.rs/crossterm/latest/crossterm/event/index.html)）。

### 结论：保留现有栈，不再换框架

当前 TUI 体验缺陷应在现有栈上修复，不能解释成需要再造一套渲染器或再迁移框架。尤其是
当前模式与 Ratatui 0.30.2 的一个已知上游问题完全重合：持续 draw、inline viewport 和
`insert_before` 在 resize 时可能把实时区重复写入 scrollback
（[Ratatui 官方仓库 issue #2666](https://github.com/ratatui/ratatui/issues/2666)）。
这要求 Agul 把 inline viewport 适配封装在一个小边界内，跟踪上游修复或维护最小 workaround，
而不是抛弃 Ratatui。

具体保留边界：

- 保留 Ratatui 的布局、buffer diff、inline viewport 和 TestBackend。
- 保留 Crossterm 的事件、raw mode、bracketed paste 与 resize。
- 保留 ratatui-textarea 的文本状态；Agul 只维护命令/Skill 补全和产品快捷键。
- grapheme 修正只有在上游提供等价保证且中文、emoji、组合字符测试通过后才能删除。
- Markdown AST 和代码高亮继续使用
  [pulldown-cmark](https://docs.rs/pulldown-cmark/latest/pulldown_cmark/) 与
  [Syntect](https://docs.rs/syntect/latest/syntect/)，不回退到正则解析。

迁移到另一个 TUI 框架会重做已经存在的输入法、paste、Unicode、滚屏和退出恢复测试，维护
收益为负。

## 2. HTTP、SSE 与 provider

### 当前实现

[provider.rs](../../agul/src/runtime/provider.rs#L540-L581) 已用 Reqwest 处理 TLS、HTTP、
超时和响应；provider 自研代码主要负责 OpenAI-compatible、DeepSeek、GLM、本地模型的
请求/响应差异，以及 reasoning、tool call、usage 的统一归属。Reqwest 的 Client 自带连接池
并建议复用（[Reqwest 官方文档](https://docs.rs/reqwest/latest/reqwest/struct.Client.html)），
这里没有必要改用厂商 SDK。

HTTP 测试也按语义分层：普通的固定响应、路径匹配和调用次数验证使用
[`httpmock`](https://docs.rs/httpmock/0.8.3/httpmock/)；只有验证 UTF-8 跨 chunk、截断连接、
响应头等待取消等 wire-level 行为时才保留 raw socket。这样不会为每条命令回归重复维护请求解析器，
也不会让高层 mock 隐藏 SSE framing 的真实故障。

真正重复造轮子的部分是
[EventStreamDecoder](../../agul/src/runtime/provider.rs#L630-L730)：它自行处理 chunk 边界、
CRLF、注释、多行 `data:`、UTF-8 与事件 dispatch。

### 结论

**Reqwest 与 provider 方言层保留。** 不建议引入 `async-openai` 一类单厂商抽象；它无法
同时表达本地 OpenAI-compatible 端点、DeepSeek/GLM 的差异和 Agul 的逐响应 usage ledger。

**SSE framing 评估 `eventsource-stream` 后替换。** 该 crate 的定位正是把
`reqwest.bytes_stream()` 转为 SSE Event stream
（[官方文档与示例](https://docs.rs/eventsource-stream/latest/eventsource_stream/)）。迁移仅删除
标准 framing，不移动以下产品逻辑：

- `[DONE]` 与各 provider JSON payload 解码；
- reasoning/text/tool delta 分类；
- 用户 `/stop` 的取消延迟；
- 传输错误或取消时已经取得的 partial response/usage；
- 流结束但 completion 不完整时的错误语义。

实验必须复用现有 SSE fixtures，并补齐“UTF-8 跨 chunk、CRLF、多行 data、注释、截断 EOF、
取消时 partial usage”契约测试。任何一项行为丢失就保留现有 decoder；不能只因库存在就换。

## 3. JSON-RPC、ARI 与 Codex transport

[ARI serve](../../agul/src/commands/ari_simple.rs#L60-L170) 是换行分隔的 JSON-RPC 2.0：
一个输入循环、有限方法表、通知式 `ari.event`。它符合 JSON-RPC 对 request、response、
notification 和 id 的基本要求（[JSON-RPC 2.0 规范](https://www.jsonrpc.org/specification)）。

`jsonrpsee` 已有 request、notification、subscription、batch、ID 管理和自定义 transport trait
（[官方 client API](https://docs.rs/jsonrpsee-core/latest/jsonrpsee_core/client/)），但当前 ARI
没有网络 transport、batch、subscription 生命周期或并发 in-flight request。`ari_simple.rs`
的大部分体积来自 session、provider、usage 和事件语义，而不是 RPC envelope。因此现在迁移
只会引入 async client/server 框架和适配器，不会显著删代码。

结论是 **ARI 保留小实现**。只有出现以下任一真实需求时再评估 `jsonrpsee`：网络 transport、
批处理、同一连接多并发请求、服务端订阅或第三方需要标准 client SDK。

[Codex app-server transport](../../agul/src/runtime/codex/transport.rs#L357-L432) 更不应硬套
JSON-RPC 库。该对端请求没有 JSON-RPC 2.0 规范必需的 `"jsonrpc":"2.0"` 字段，并包含
Codex 专用 server request/notification。它应继续作为独立 adapter。

AgentKube 的 [AriWorker](../../plugins/coordinator/coordinator.py#L244-L350) 也应保留轻量 client；
后续可把示例和 coordinator 的公共 envelope/fixture 收敛到一个仓内模块，但这属于代码组织，
不是引入外部 RPC 框架的理由。

## 4. 会话、账单与原子文件写入

### 已关闭的问题

[SessionStore::save](../../agul/src/runtime/chat_session.rs#L503-L511) 曾先写 `json.tmp`，目标存在
时先删除旧文件，再把临时文件 rename 到目标。进程在 remove 与 rename 之间终止，或 Windows
rename 失败时，会话文件会直接消失。2026-08-30 已改为共享 `replace_file` 适配器。

[billing sync](../../agul/src/runtime/billing/sync.rs#L380-L391) 曾另有一套临时文件、
`sync_all` 和 rename。现在 `sync.json` 与 session 使用同一适配器；价卡创建仍保持不可覆盖。

### 结论：覆盖写立即使用成熟库；不可覆盖创建保留语义

`atomic-write-file` 保证提交前旧文件保持不变，提交后只会看到旧内容或新内容，并支持 Unix、
Windows 与 WASI（[官方说明](https://docs.rs/atomic-write-file/latest/atomic_write_file/)）。建议建立
Agul 已建立很薄的 `replace_file` 适配器并用于：

- session JSON；
- billing `sync.json`；
- 其他“新状态覆盖旧状态”的单文件 JSON。

不要机械替换账单缓存的 `atomic_create`。`atomic-write-file` 官方明确说明它不提供
`create_new()`，因为从 open 到 commit 无法保证目标始终不存在
（[OpenOptions 限制](https://docs.rs/atomic-write-file/latest/atomic_write_file/struct.OpenOptions.html#notable-differences-between-stdfsopenoptions-and-atomic_write_fileopenoptions)）。
内容寻址、已存在即拒绝覆盖的价卡文件应保留现有创建语义，或另行评估同时支持
allow/disallow overwrite 的库，不能为统一 API 放松账单不变量。

**usage ledger、定点金额和版本化价卡继续自研。** 它们表达 provider 报告值、估算值、
压缩 usage、缓存 token 与 catalog revision 的来源关系，是 Agul/ARI 的产品能力。把它换成
浮点 money 包或通用数据库不会减少协议复杂度。

会话继续使用可读 JSON + NDJSON trace。当前数据量、只读 `/sessions` 和人工排查方式不值得
迁移 SQLite；只有出现多进程并发写、跨数万会话查询或事务化索引时，才值得评估 SQLite 的
[事务与原子提交模型](https://sqlite.org/atomiccommit.html)。

## 5. 插件发现、进程与运行边界

### 插件发现：保留浅层语义

[plugin::discover](../../agul/src/runtime/plugin.rs#L438-L520) 只接受一个直接 `plugin.json`，
或根目录下一层的插件目录。这是显式、可预测的 package 布局，不是任意递归文件搜索。
`walkdir` 之类库不会自动解决“显式配置却零 manifest”或逐项 IO 错误；这些必须由产品层报告。
因此保留当前发现器，并坚持：显式 plugins 路径没有加载到任何 manifest 时必须可见，目录
entry/metadata 错误不能吞掉。

插件 invocation/event 是语言无关的 NDJSON 子进程协议。动态链接式插件框架会改变
AgentKube 可用任意语言提供扩展的边界，不建议采用。

### 进程树：只替换平台层

[ProcessTree](../../agul/src/runtime/process.rs#L66-L120) 自行维护 Unix process group、调用外部
`kill`，并用 Win32 Job Object 控制 Windows 子孙进程；同一文件还承担 stdin/stdout/stderr
线程、head-tail 截断、timeout、取消和插件流式回调。

`command-group` 已为 `std::process::Command` 和 Tokio Command 提供 Unix/Windows process
group，并暴露 group child 与 Unix signal 支持
（[官方 crate 文档](https://docs.rs/command-group/latest/command_group/)）。建议做一个隔离实验，
**只替换 ProcessTree 的平台代码**，保留 Agul 的：

- 有界 head-tail 输出与截断标记；
- 插件 stdout 的流式 event callback；
- turn cancellation 和 timeout 区分；
- 正常退出时保留 descendants、取消时终止整棵树的现有语义。

验收要覆盖 Windows 嵌套 Job Object、Unix 已脱离/未脱离的 descendants、取消与自然退出竞态。
如果库无法表达 `preserve_descendants`，就不迁移；删掉 `unsafe` 不是牺牲行为的理由。

当前不建议给 Agul 核心再引入“大而全跨平台沙箱”库。Agul 的 minimal 运行体验、工作区
工具和可选 AgentKube 扩展是既定边界；未来需要 OS 隔离时应作为可选 plugin/harness 使用
平台成熟机制，而不是让核心进程 runner 同时变成策略引擎。

## 6. 配置与 JSON Schema

仓库已经维护了完整的 Draft 2020-12 Schema：Agul 的
[launch/plugin/session/handoff/trace](../../agul/schemas/)、Agulater 的
[package/catalog/harness/pools/specialists/snapshot](../../agulater/schemas/) 和 AgentKube 的
[web result](../../schemas/agul-web-search-result-v1.schema.json)。Draft 2020-12 是正式发布的
JSON Schema 规范（[官方规范](https://json-schema.org/draft/2020-12)）。

问题不是缺 Schema，而是正式 Schema 曾经没有进入执行路径：

- Agulater 过去在 [agulater.ts](../../agulater/tools/lib/agulater.ts) 为 Package v2
  维护 `strictObject`、字段列表、类型和范围检查；
- AgentKube coordinator 对 pools、specialists 和 handoff 再手写一套校验
  （例如 [handoff 检查](../../plugins/coordinator/coordinator.py#L980-L1025)）；
- Agul 同时依赖 Serde `deny_unknown_fields` 和手工语义检查。

### 分仓结论

**Agulater：Package v2 试点已经完成。** Ajv 官方支持 Draft 2020-12，
strict mode 会把被忽略或歧义的 Schema 写法直接暴露出来
（[Ajv 官方仓库](https://github.com/ajv-validator/ajv)、[strict mode
文档](https://ajv.js.org/strict-mode.html)）。`package-v2` 现在由构建期生成的
[standalone validation code](https://ajv.js.org/standalone.html) 校验；生成结果再经 Bun 打包，
因此生产安装既不动态编译 Schema，也不安装 Ajv。CI 会拒绝与 Schema 不一致的生成物。

Ajv 只替代 Package 的“结构、类型、required、pattern、范围”检查。适配层把 `oneOf` 等内部
错误折叠成一条带完整字段路径的提示，不暴露正则和 Schema 路径。文件存在、依赖环、跨包
唯一性、Git URL、来源解析和路径实际落点等语义检查仍由 Agulater 负责。catalog、sources、
snapshot 等格式不在本次打磨范围内；是否迁移必须单独证明能减少代码且不损害错误体验。

**Agul：保留 Serde 类型作为运行时主路径。** Serde 已提供类型化数据和较小依赖面，没必要
把所有解析改成 `Value -> jsonschema -> struct`。Rust
[`jsonschema`](https://docs.rs/jsonschema/latest/jsonschema/) 支持 Draft 2020-12、可复用 validator、
meta-schema 和编译期 validator；适合用于 Schema/fixture 合规测试，以及真正动态的外部 JSON
文档。若进入 runtime，必须关闭默认 HTTP/file resolver，只使用随二进制嵌入的 Schema，避免
为了本地校验再引入远程解析与第二套网络行为。

**AgentKube Python：依赖交付明确后评估 `python-jsonschema`。** 官方实现支持各版 JSON
Schema 并提供 validator 选择（[官方 GitHub](https://github.com/python-jsonschema/jsonschema)）。
但当前插件宣称仅需 Python 标准库，Agulater package 尚未正式声明/安装 Python dependencies；
在依赖可重复交付前直接 import 会让插件在不同机器表现不一致。短期先让三仓共用同一组
合法/非法 fixture；依赖打包落地后再删除 coordinator 的重复结构校验。

launch 搜索“当前目录 → 祖先 → 用户级目录”的代码
([project.rs](../../agul/src/runtime/project.rs#L170-L210)) 很小且是明确产品规则，保留自研。
引入通用 config merge 框架会添加环境变量、层叠合并等 Agul 并不需要的隐式行为。

## 7. Agulater：下载、解压、SemVer 与原子安装

### SemVer：已使用 Bun 内置实现

Agulater 曾同时维护手写
[compareSemVer](../../agulater/tools/lib/semver.ts#L1-L7) 和
[satisfiesVersion](../../agulater/tools/lib/agulater.ts#L2065-L2072)。范围实现只覆盖精确、
`^`、`~`、`>=` 与 `*`，0.x 和 prerelease 规则已经开始自行复刻标准。

项目已固定 Bun 1.4.0，而 `Bun.semver.satisfies` 与 `Bun.semver.order` 正好覆盖这两个函数，
并声明与 npm 使用的 node-semver 范围兼容
（[Bun 官方 SemVer 文档](https://bun.com/docs/runtime/semver)）。这是**低风险、零新增依赖、
立即替换**项。2026-08-30 已完成迁移，并固定普通版本、build metadata、prerelease、
`^0.0.x`、`^0.x`、`~`、范围边界和非法版本回归；manifest 允许的 range 表面没有扩大。

### 下载：保留 `fetch` / `git` / `gh`

[runtime-manager](../../agulater/tools/lib/runtime-manager.ts#L45-L112) 已使用 GitHub API、
`gh`、`fetch` 和真实 `agul --version` 验证；extension 下载使用 `git`/`gh`，这些本身就是成熟
的传输与认证实现。当前自研部分是 catalog/source 选择和落盘布局，换成另一个 HTTP 下载库
不会减少多少代码。

当前资产整体读入 `arrayBuffer`。Agul 可执行文件体积尚小，不值得只为流式写入增加依赖；
若未来资产明显变大，优先使用 Bun 自带 Response/Blob 与 `Bun.write` 流程，而不是再包一层
下载框架。

### Agulater 分发：使用 Bun standalone

Agulater 源码仍由 Bun 1.4 构建，但普通用户不再安装语言运行时。发布矩阵直接用
[`bun build --compile`](https://bun.sh/docs/bundler/executables) 生成 Windows、Linux 和 macOS
单文件程序；Bun 官方实现负责打包 TypeScript、导入的 npm 包和运行时，并支持这些跨平台
target。仓库只保留薄的归档和安装脚本，不实现 JavaScript loader、bootstrapper 或自更新
运行时。

本机已在移除 Bun/Node/npm 的 `PATH` 后验证 standalone 的 `--version` 和隔离用户初始化。
发布 CI 继续分别在各平台运行生成后的程序，避免“能交叉编译”被误当成“目标平台已验证”。

### 解压：统一 tar.gz 后评估 Bun.Archive

[unpackAsset](../../agulater/tools/lib/runtime-manager.ts#L312-L330) 依赖宿主机 `tar`，并
让同一命令同时处理 zip 与 tar.gz。Bun 1.4 的 `Bun.Archive` 已能原生创建、读取和解压 tar/
tar.gz，并处理 Windows 差异
（[Bun 官方 Archive 文档](https://bun.com/docs/runtime/archive)）。它不支持 zip，因此不能直接
替换当前 Windows `.zip` 资产。

建议先在一个 release 中验证 Windows/macOS/Linux 都能从 tar.gz 安装，再把后续 Agul release
统一为 tar.gz；之后用 `Bun.Archive` 替换 tar/tgz 路径。旧 zip 兼容期仍保留系统 tar，或只在
明确需要时引入一个成熟 zip extractor。不要自己写 zip parser。

### 原子安装：目录事务保留，单文件另行收敛

[installDirectory](../../agulater/tools/lib/agulater.ts#L1760-L1790) 在目标同级建立 staging，
prepare 完成后把旧目录改名为 backup，再切入新目录，失败则恢复。这段逻辑与 Agulater 的
package 布局、source record 和 rollback 绑定；通用“原子写文件”包不能替代目录事务。

因此保留目录安装器并加强现有三平台故障注入测试，不为了使用库而重写。`current.json`、shim
和 registry 等单文件写入可以在后续统一一个小适配器，但只有实测证明 Node/Bun 生态库在
Bun standalone 和 Windows replace 上更可靠时才迁移；当前同目录 temp + rename 已比
`SessionStore::save` 完整，不是最高优先级。

runtime 激活需要同时发布 executable、切换 launcher 与写入 `current.json`，单文件原子写无法
覆盖这个边界。这里已用
[`proper-lockfile`](https://github.com/moxystudio/node-proper-lockfile) 只锁住最终本地提交段：
下载和解包不占锁；`agul --version` 验证有 30 秒硬上限；提交失败恢复旧 launcher；并发激活
直接提示稍后重试。该库使用原子的目录创建与 mtime 处理跨进程锁和崩溃残留，避免 Agulater
再实现一套 stale-lock、心跳和抢占规则。

## 8. AgentKube：Web 与 coordinator

### `web_open`：正文抽取值得用成熟库

[web_search.py 的 `_PageExtractor`](../../plugins/web-search/web_search.py#L73-L137) 只忽略
script/style 等标签，然后把 article、nav、aside、header、footer 等所有块文本一起输出。
这不是正文抽取，会把导航、页脚和推荐内容消耗进模型上下文。

Trafilatura 的 `extract` 会先运行自己的正文算法，结果过短时再回退到 readability 和 jusText；
它支持 plain text、JSON、Markdown、metadata，并提供 precision/recall 取舍
（[Trafilatura 官方 Python 文档](https://trafilatura.readthedocs.io/en/latest/usage-python.html)）。
建议做高优先级评估：

1. 保留当前对 `text/plain`、JSON、XML 的直接读取，以及 2 MB/12k chars 上限。
2. 只把 HTML 的 `_PageExtractor` 换成 Trafilatura。
3. 用新闻、文档、博客、论坛、中文页面和纯 SPA fallback fixture 对比正文完整度、噪声和耗时。
4. 先由 Agulater package 正式声明/安装 Python dependency；不允许“装了库就用、没装就悄悄
   回退”造成不可复现结果。

因此这是**收益高但有依赖交付门槛的评估后替换**，不是立即加一个隐式 pip dependency。

HTTP 层暂时保留 `urllib`。它是 Python 标准库，不是自研 HTTP；当前 web plugin 请求量小、
有显式 timeout 和响应大小上限。只有出现连接池、代理、并发 open、细分 connect/read/write
timeout 等真实需求时，再迁移 HTTPX。HTTPX 确实提供 connect/read/write/pool 四类 timeout
（[官方文档](https://www.python-httpx.org/advanced/timeouts/)），但它不会自动改善正文质量。

`web_open` 本身不依赖搜索引擎配置；需要 SearXNG/Tavily 的只有 `web_search`。搜索 provider
adapter 和结果格式是 AgentKube 产品胶水，应保留。

### coordinator：保留 ARI 调度，不引入第二个 agent runtime

[coordinator.py](../../plugins/coordinator/coordinator.py#L244-L410) 用 subprocess、Queue、Thread
驱动每个 Agul ARI worker，并用
[ThreadPoolExecutor](../../plugins/coordinator/coordinator.py#L1290-L1325) 并发只读任务、串行
写任务。当前上限只有五个 bounded task，阻塞 stdio 与线程模型匹配。

不建议引入通用 multi-agent orchestration 框架。它们会与 Agul 的 session、prepared launch、
ARI events、逐响应 usage 和 master/specialist 职责重复。这里应该保留自研的是“如何调度 Agul”，
而不是重新实现线程池、进程和 Queue；当前已经正确使用 Python 标准库。可维护性改进应集中在：

- 把 ARI client 从大文件提取成仓内共享模块；
- 依赖交付成熟后，用 `python-jsonschema` 删除 pools/specialists/handoff 的结构校验重复；
- 保留 coordinator 的 pool 选择、usage 汇总、handoff 与进度限流。

## 推荐实施顺序

### 第一批：低风险、直接减少自研

1. [x] Agulater 用 `Bun.semver` 替换两套手写 SemVer，并保留边界测试。
2. [x] Agul 为 session JSON 与 billing `sync.json` 引入统一的
   `atomic-write-file` 覆盖写适配器；价卡不可覆盖创建不动。
3. [x] Agulater 以 `package-v2` 为试点接入 Ajv 2020 strict/standalone；已删除该解析路径的
   手写对象、字段和数组结构校验，保留路径、Git 来源、唯一性等业务语义；生产包不携带 Ajv。

### 第二批：隔离实验，达标才迁移

1. 用现有 provider fixtures 对比 `eventsource-stream` 与当前 decoder。
2. 用 Windows/Unix 进程树测试对比 `command-group` 与当前 ProcessTree。
3. [x] 用 Bun standalone 生成 Agulater 全平台候选物并做无 Bun smoke；统一 Agul runtime
   归档后再单独评估 `Bun.Archive`。
4. 给 web plugin 建立可重复 Python dependency 交付，再用页面语料评估 Trafilatura。
5. dependency 交付稳定后，在 coordinator 试点 `python-jsonschema`。

### 明确不做

- 不再迁移或自造 TUI 框架；继续修复 Ratatui inline 适配与真实终端验收。
- 不把 provider 换成单厂商 SDK。
- 不因 ARI 文件较长就引入完整 RPC server 框架。
- 不把可读 session/trace 迁移数据库。
- 不用递归文件遍历库改变插件发现语义。
- 不给 Agul 核心塞入通用 agent orchestration 或大而全 sandbox 框架。

## 每项迁移的统一验收门槛

候选库只有同时满足以下条件才可合入：

1. 删除的自研代码和分支数明显多于新增 adapter；
2. Windows、Linux、macOS 的现有行为测试通过；
3. TUI 不失去滚屏、浮动输入、steer、`/stop`、paste、Unicode 与退出恢复；
4. provider 错误/取消仍记录已经发生的逐响应 usage；
5. price catalog revision、估算来源与 ledger attribution 不变；
6. Agulater 安装失败后旧版本仍可运行，且 package/source record 一致；
7. 记录二进制体积、冷启动、构建时间和运行内存变化，收益不足时停止迁移；
8. 不把新的系统级安装步骤或隐式依赖转嫁给普通用户。

这组门槛的目的不是扩大验证流程，而是确保每次“采用成熟库”确实换来更少代码、更少故障和
更好的现有体验。
