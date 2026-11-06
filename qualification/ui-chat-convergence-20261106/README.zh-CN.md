# Hepta 聊天 UI 收敛：源码、执行证据与产品边界

本轮已经提交代码修复，并按实际来源保存测试、失败和恢复记录。**产品验收结论仍为 HOLD**：尚未执行同源受信普通入口上的“用户发出任务 → 独立效果回读 → 持久终态与审计回执 → 恢复后再次核对”。本文不把 SDK、presenter、浏览器布局或静态截图通过转记为该产品闭环。

## 固定交付

| 阶段 | PR | 当前提交 | 完整源码树 |
| --- | --- | --- | --- |
| 编辑事务与输入门 | [#4952](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4952) | `65f266d07e3606ddeb109ef4683e1aecd201334c` | `99e788f330cac2203d99f64f0c31846d1ab4f05a` |
| 原 Objective 终态跟进与证据保留 | [#4953](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4953) | `518d0021e29a32e07c14d92b4c4e0cab5c4c4e8e` | `20834ab797f13ece7a89ae954b9505fc076e9be9` |

基础为 #4797 的 `67cc5c28`。最终提交保留 `768f94ef` 和 `65f266d0` 两个父提交，没有改写历史。相对 `768f94ef`，最终提交仅将一个测试中的 grouped imports 按原格式配方拆行；旧测试结果仍绑定旧提交。两份 PR 均保留 Draft，没有合并 main 或激活产品。

## 实际改变

本轮只修复 `67cc5c28` 的旧 Objective 候选。已审查的原生 Owner 与 Desktop 配对仅完成源码核对，本轮没有跨仓切换或接通普通受信入口。

1. 选择性移入 `d4a6e26b` 已有的 Makepad 编辑事务与桥接修复，保留旧 Objective 分支的 Send、Cancel、Refresh。IME preedit 不写入草稿/标题；拒绝输入时一并恢复文本、选区和 undo；Firefox 式无文本变化组合提交的协议/SDK 回归与迟到输入经过原 owner/room/epoch 边界。
2. 修正旧 Objective 提交门的 InputLimit 缺口。被拒绝的超限输入不能发送，也不能把编辑后的文本当成原已授权请求；恢复原草稿仍不获得额外发送次数。
3. 原 owner 的单一 worker 自动观察原请求。正常读取在上一轮结束后间隔 1 秒；Unknown 按 2、4、5 秒退避；终态、关闭和到期停止自动观察。定时器不重发 Submit/Cancel。包括“本地取消已提交但 checkpoint ACK 丢失”的路径，均通过原请求读回协调结果。
4. 在原 Memory writer 事务内去重等价观察。仅排除顶层请求关联字段 `request_id`，完整响应中的身份、代次和 payload 仍参与比较；等价状态重新取得独立 ACK，变化的 RunStatus 和终态保留原始响应字节。64 个不同事件的边界保持不变。

Console 保留在原 Robrix 聊天内。没有增加第二套控制中心、签发器、数据库或 owner。实现与未关闭条件见 [TASK_LIFECYCLE.md](../../apps/hepta-control-ui/TASK_LIFECYCLE.md)。

## 已完成执行的来源边界

| 执行范围 | 实际源码 | 已核对结果 | 资格限制 |
| --- | --- | --- | --- |
| 原 Agentd Objective/UI/sender 库选择器 | `768f94ef` | 19 PASS；233 filter-excluded | 真实 ControlServer/SQLite/ChatWorkspace 的协议 fixture；外部效果数为 0 |
| 原 Memory sender 库选择器 | `768f94ef` | 27 PASS；309 filter-excluded | 原 writer/checkpoint/权限与恢复边界 |
| 共享 Rust `--no-default-features --lib` | `768f94ef` | 67 PASS，0 skipped | Rust 状态与 headless UI；与下面测试存在覆盖重叠，不能累加为独立总量 |
| 原 native composition headless/native 两范围 | `768f94ef` | 28/28 与 37/37；全部六项实际 SDK 编辑器回归通过 | AI395 与原 hosted source-head 独立通过；不是物理 IME、辅助技术或设备资格 |
| 旧桥上的新增迟到输入反例 / 修复后的原桥 | 冻结 UI 内容 | 旧桥 24 PASS / 1 FAIL；修复桥 25 PASS | 可复现拒绝文本返回；本地原辅助 Rust runner 为 0.9.103，不冒充原 CI pin |
| 原 strict-CSP WASM 与桥接 | `768f94ef` | 构建 52 assets；资源 5/5；桥接补齐环境后 32/32 | 首次桥接 31 PASS / 1 FAIL 为 stable WASM std 缺失，原件保留 |
| 最终原 hosted native/source-head | `518d0021` | 28/28 headless、37/37 native，0 skipped | job `127834787283` 的前后源码 clean、fresh JUnit、锁哈希均核实；不外推物理输入或执行效果 |
| 最终同源网关与首次原网关选择器 | `518d0021` | 构建通过；四组 9+5+12+2=28 PASS | 原选择器、9/5/11/2 下限、600 秒 watchdog 不变；不产生实际用户任务效果 |

原远端 Rust runner 为 just 1.58.0、Rust 1.95.0、nextest 0.9.146。未发生实际 retry；原 local retry 配置没有改写为零。首轮 Agentd XML 收集路径错误、共享 profile 原本没有 JUnit 的事实，以及后续独立 receipt runs 都保留。receipt followups 不计作新增唯一覆盖。

scoped `just fix` 无源码变化。原 `just fmt --base 67cc5c28` 在显式 Rust 1.95.0 下检查了 16 个 Rust 输入，仅改变上述一个测试的导入格式。旧 Agentd/Memory/shared scopes 在本地 hygiene 后没有复跑；最终网关四组是此前未执行的首次新范围。最终提交随后由原 hosted native/source-head workflow 独立重建并完成上表 28/37 范围，结果单独绑定最终提交。

最终 `518d0021` 的 strict-CSP 构建仍为 52 assets，资源契约 5/5、桥接 32/32。真实 Rust 网关的浏览器范围通过 7/7；它验证的是 unavailable/503 与取消边界，没有取得实际任务效果。原 HTTP/发布 SDK 边界通过 60/60 场景和 36/36 严格反例；其中 WASM 导出为 synthetic，不能外推为真实 owner 执行。

默认布局矩阵为 Chromium 2/2、Firefox 2/2、WebKit 0/2（启动前依赖失败），完整矩阵失败。默认像素门只取得 40/60 张所需截图，执行的 92 项语义检查通过，但所需总数为 138，缺少的 46 项没有执行，完整像素门失败。填充会话矩阵为 Chromium 3/3、Firefox 3/3、WebKit 0/3（相同启动前失败），完整矩阵失败。填充像素门为 52/78 张所需截图、292/292 已执行语义检查通过，但总要求为 438，缺少 146 项没有执行，完整像素门失败。没有跳过 WebKit、降低检查项或修改 Playwright 宿主校验来制造通过。

三张原 Chromium 图像补充检查了宽屏、紧凑 Console 和含 CJK 的 64-message fixture：未发现明显重叠或裁切，Console 与 Chat 保持同一导航。fixture 没有真实聊天连接；这些观察只说明画面，不证明物理输入或执行效果。

最终浏览器完整像素计数、环境准备失败与最新 CI 切点另见本目录 `SUMMARY.json`、`browser-raw.tar.gz` 和 `validation-raw.tar.gz`。源前后身份、实际命令、原日志、过滤项和独立失败保留在归档内。本地与 ai395 的 fresh JUnit 原件一并归档；最终 hosted native 本轮保存完整 job 日志及原 verifier 的 fresh run UUID、XML 哈希与字节数，未另下载 XML，原 artifact 为 `13496020022`。没有用新的版本号给旧结果重新贴标签。

## 跨仓库收敛判断

已审查的 Hepta `d4a6e26b` 原生 Owner 候选使用替代式架构。Desktop 的真实 `NativeChatComposition` / `TextChatAdapter` 借用同一个 DraftBook/ChatWorkspace，并接入 Send、Stop、历史、审批、Notes 和 Console。删除旧 `desktop_objective_ui` 文件不等于退化；新路径本身已有 InputLimit 提交门及只读 reconcile/history 跟进，不能再复制一套旧 worker。

但目前不能只替换伴随 pin：Desktop `af0e75dc` 的 source profile 对 Hepta `14e2d89b` 的 194 个文件全部匹配；对 `d4a6e26b` 为 **147 相同、47 改变、0 缺失**。变化包括真实 Root、lease、Memory writer 和 Cargo.lock。Desktop `af0e75dc` → Hepta `14e2d89b`、Desktop `1c8b37da` → Hepta `bfdf51e1` 两候选的六锁共 12 份原始文件均已读回；其含 Hepta 的三根锁分别固定 14e 与 bfdf。这两对不是已验证的 d4 线性升级或已安装配对。关键生产接口同字节不等于整个包、ABI、安装或运行资格；所审 text_session 子集仍有两份测试文件变化。旧清单也不能证明候选新增源文件已全部纳入新 profile。

完整逐路径 blob/大小/SHA、六锁 pin、固定源码链接及调用链审查见 `source-review.tar.gz` 内的 `ordinary-entry-review.md`、`desktop-af0-vs-hepta-d4-source-contract.json` 与 `desktop-candidates-six-lock-pins.json`。

本轮在 ai395 与 desktop 各执行一次有界、无 sudo 的当前元数据盘点。ai395 的 `/var/lib/trill`、`/opt/trill`、`/run/trill` 三个指定部署目录不存在，未匹配到指定进程名；desktop 的 `/var/lib/trill` 有十个 Root 所属子目录，也未匹配到指定进程名。未进入子目录或读取 profile/env/cmdline。**这只证明该时点和扫描范围内的观察；当前受信 binary/profile 和服务身份仍未核实，不能将历史目录认作当前安装资格。** 两个探测原 job 均自然成功，完整输出和脚本在 source-review 归档中。

## 按用户标准保持开放的项目

| 条件 | 当前界限 |
| --- | --- |
| 普通任务入口与真实效果 | 旧候选默认 Web/desktop 入口没有生产 Objective installer 调用方；新版实际 adapter 需要精确两仓包与受信 installed profile。未执行 provider/tool/device 正向效果闭环。 |
| Objective / TaskFlow / Memory 进度 | 原 owner 的观察与 Memory 证据路径得到修复；旧 UI 仍将部分非终态合并显示，未完成真实上下文/TaskFlow 进度与效果关联验收。 |
| 权限、错误、取消与恢复 | 原边界 fixture 有独立覆盖；没有证明新两仓包在真实撤权、断连、Agentd+AppServer 双进程或主机重启后的完整恢复。 |
| 审计回执 | 原响应字节与独立 ACK 的保留得到加强；没有独立外部效果回执及 UI 中完整的可核验产品收据链。 |
| 平台输入和访问性 | SDK 编辑器和浏览器范围单独记录；物理 IME/CJK、多窗口焦点、AT-SPI/Orca、真实移动触控与设备仍未验收。Linux 结果不外推为 Windows/macOS。 |
| 503 与重连 | 最终原网关边界通过；真实浏览器结果以最终执行记录为准。元数据 503 不授予 owner，不把 queued/admitted 显示为成功。 |
| 资源 | 单 worker、有界队列/日志与退避保持；构建/测试 cgroup 峰值不是产品 idle/active CPU、RSS、写放大或设备功耗测量。 |
| Rust-only | 布局、主题、聊天状态和业务边界在 Rust；Web 仍需要固定 Makepad JS/WASM 启动、渲染、输入桥。现有 JS oracles/build tools 不作为平行业务 UI，也不宣称零 JavaScript。 |

截至 2026-11-06 10:39:15 UTC 的 API 切点，最终 source-head native 与依赖锁生成 job 已成功，UI foundation 与完整 Owner job 仍在运行，Blocking 尚有排队/运行项且 cargo-deny 已失败。base-merge 是独立合成来源，不能记作 source-head 的覆盖；queued/skipped 均不计通过。

此前 a43 的原 owner 格式失败由本轮追加格式修复处理，但新 head 必须单独过门。最终 518 的 cargo-deny job `127843843790` 已失败；仅尝试一次取回日志，仍为 `Transport closed`，完整错误回执已保存，具体原因未知。此前两条 cargo-deny 失败也未作原因推定。原 Intel PTY job 的完整日志已取得：`pty_dropped_output_receiver_keeps_draining_child` deadline elapsed，PTY 30 PASS/1 FAIL；该源码不在本轮修改中，原 required failure 仍保留。

## 原件使用

`EVIDENCE_INDEX.json` 给出三个 gzip/tar 归档及每个成员的字节数和 SHA-256。验证与源码审查归档从原 UTF-8/二进制文件字节生成，封包后逐成员回读比对；浏览器原 tar 逐字节保留并独立校验全包及每个成员。没有截短原日志。额外 Intel 原始 job 日志直接保存于 `ci/`，其 Git blob 也列入索引。源码证据提交独立于产品分支，不影响产品 HEAD 或重启其资格流程。
