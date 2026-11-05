# Chain／Hepta V10 固定源码对与门禁记录

**九项退出条件均为 HOLD。** 本记录保存本次改动、已观测的分项证据和未关闭边界。产品资格、生产启用、模型安装及整链 PQ 安全声明授权均为 `false`。最终 Runtime 已取得新的源码／owner 控件、Evidence 原生、Automation 默认 features 完整 target 清单及严格 Clippy 收据；各自绑定实际执行的 `d7c32f38…`，不继承其他提交的绿灯。

## 固定源码对

| 仓库 | Commit | Tree |
| --- | --- | --- |
| Chain | `04be5f02c84cf5cb626a53f34bc03a5bd6ff5137` | `d4f4a85c439982d8decec9265c1993408f3577cf` |
| Hepta | `d7c32f38ae1c3890e73ff48ef8ee725ba4e80c58` | `b79a4a4677b672a89cce53c9abe6f6c71810ee88` |

最终 Runtime 的父顺序为 `ce56018cadc83120068de1a63020c60e92b48f42`、`f85289eff7366b60940d72cc611217db1bf1aef9`，保留了并发证据提交；相对 `f85289e…` 只增加 8 条 `evidence/` 路径。各项资格按最终 `d7c32f38…` 的实际收据结算。

执行 profile 为 `hepta-integrated-chain-execution-v10`；manifest SHA256 为 `97e5311a86a0dc6fcd62a29ca9cd8a323c9b34a6991790ae347cfbb57bf796ed`。V10 固定 51 个显式 manifest 文件，并检查所选 Chain 工作树的全部 tracked 原始字节、隐藏索引标志及相关路径中的 untracked／ignored 输入。**这里的 51 是文件数，不是 native 测试数。** 两个 lockfile 的精确 SHA256 见 [gate-status.json](gate-status.json)。历史模型 profile、试验家族 **1/1 已用预算**和原 RSS 失败继续保留，换源码不恢复试验额度。

## 冻结代码、移动分支与证据投递身份

本次读回的 Chain PR **#688** 头为 `fc86ed8e927a8eb4e048b160437126a6c0b96c0d`，领先冻结的 `04be5f02…` **12 个提交**，共有 **142 条路径变化，包含生产源码和 `trillionnium/Cargo.lock`**。该新头不受这里的固定代码对收据资格覆盖。Runtime PR **#4812** 在该次早期读回为 `d7c32f38…`。[分支读回摘要](branch-readback.json)

准备投递证据时，Runtime 又前进到 `fc0c6f7430cc1cce9274d407536e7249f2290ccd`，领先 `d7c32f38…` 一个提交；22 条路径变化包含 Agentd 的 ML-DSA 恢复入口、相关测试和 `codex-rs/Cargo.lock`。本次证据追加在该提交之后，保留并行改动，但 **`fc0c6f7…` 及证据投递 tip 均不继承本轮 `d7c32f38…` 的结果**。[投递父提交读回](publication-parent-readback.json)

本记录继续固定 `04be5f02…`／`d7c32f38…`。包含本目录的 Git commit 标识证据投递身份；它不是已测代码 SHA，也不替换本记录中的两个源码身份。该文件不嵌入自引用 commit hash。

## 最终 Runtime 组件复验

下列三份完成收据均直接绑定 `d7c32f38…`／tree `b79a4a46…`，before／after 同 SHA、clean，command exit 0；其日志 SHA256 已核对。

| 检查 | 实际结果 | 相对收据 |
| --- | --- | --- |
| V10／历代源码控件 | 107 通过、0 失败 | [runtime-published-v10-controls.json](source/runtime-published-v10-controls.json) |
| source／candidate／exec／binary owner 控件 | 60 通过、0 失败 | [runtime-published-owner-controls.json](source/runtime-published-owner-controls.json) |
| 实际源码对绑定 probe | 校验 51 个 manifest 文件；产品／安装授权仍为 false | [runtime-published-pair-binding.json](source/runtime-published-pair-binding.json) |
| Runtime native Evidence | **145 通过、0 失败、1 个既有辅助 fixture skipped**；原 profile | [final-evidence.json](effects/final-evidence.json) |
| Runtime Automation native | **137 通过、0 失败、0 skipped**；12 个默认 target 全部实际收集，10 非空、2 空 | [完整覆盖表](effects/final-automation-coverage.json) |
| Runtime strict | Evidence／Automation 两包只读 `just clippy`（recipe 含 `--tests`），`--locked -- -D warnings`，exit 0 | [严格 Clippy](effects/final-two-package-clippy.json) |


Automation 的两个空目标是 `hepta-taskflow-runtime` 和默认 feature 下的 `taskflow_kernel`：均真实编译／收集到 0 tests，Nextest 原策略 **exit 4**，原收据保持 `command_and_source_guards_passed=false`；没有计作测试通过，没有打开额外 feature。分目标执行覆盖完整清单，原 `--no-capture` 本来就是串行；原全包失败命令仍标为未成功。新增争用测试所在的 `taskflow_step` 为 **7/7 通过**。

上述最终 Runtime 原生执行和 strict 的完整 tracked 清单均为 **11,372 个文件**，before／after 原始字节与该 HEAD 匹配。它不构成外部依赖提供方、任意执行环境或外部 provider 的独立认证。strict 对所选两包通过；日志仍保留 SQLx 依赖的既有 40 条 deprecated warnings，不能解释为全部依赖零警告。Chain `04be5f02…` 另有 **127 项 source／PQ／W1 控件通过**，见[精确源码收据](source/published-source-pq-w1-controls.json)；该计数不是 W1 成本下界或整链 PQ 资格。

实现边界另见两个固定源码附件：[Growth／PQ 六处融合障碍](growth-pq-boundaries.md)、[实际 W1／fork choice／DAA 与原 Host 边界](w1-host-boundaries.md)。两份均为内部源码复核，未声称完成外部独立审计。

## 本次已实现及已观测的范围

- **Growth：** activation 新增 6 行，在 SQL／owner 审计前观察取消，并在 `BEGIN IMMEDIATE` 后重查 storage epoch。原生产代码的两项新测试实际失败，最终 Chain 上两项均通过；同一最终 ELF 共 51 个不同测试通过，另有 2 个原有大型门禁 ignored。51 为 44 项 Growth（已含两项新 activation）加 2 项 public Growth、5 项 PQ。该证据使用 Node `opt-level=3, debug=0` 诊断构建；原 profile 的 baseline 编译 SIGKILL 与未运行测试单独保留。Growth 与 PQ 仍使用各自配置。[Growth 证据](growth/growth-pq-validation-summary.json)
- **M06：** 精确 namespace 范围扫描和资金聚合优化保留原计算、首错误与账户访问顺序；公开 `capacity_with_progress` 仍走完整状态扫描，保留每 256 行及发布结果前的取消检查。最终 Chain 原 profile 的 lib 为 133 通过／8 ignored，`capacity_progress` 为 7 通过，strict Clippy exit 0。原硬件／原 slice 的 **4 秒、16 攻击者、depth 6** 未重测，原确认活性门禁继续 HOLD。[M06 证据](m06/summary.json)
- **Effects：** Migration 0016 保存独立观察顺序，保留原字节、序号和 allocator 高水位；重复终态观察不能掩盖首个 `Completed`／`Rejected` 边界后的中间 uncertainty。最终 `d7c32f38…` 的 Evidence **145 通过／1 skipped** 已重新执行；14 项核心修复案例另有[逐项提取](effects/final-native-effect-case-results.json)。`cec7a61b…` 与 `f85289e…` 各自的 145 项旧结果仍保留历史来源。真实 provider 状态真实性、外部 frontier CAS 与真实效果原子性、整机恢复及物理 exactly-once 仍有缺口。[cec7 证据](effects/provider-observation-acceptance-summary.json)；[f852 历史收据](effects/integrated-evidence.json)

`f85289e…` 的 Automation 三次尝试均在测试前失败：离线缓存先后缺 `diff 0.1.13`、`pretty_assertions 1.4.1`，随后在磁盘满期间链接器 SIGBUS。三次 **Automation native 执行数均为 0**，不计作原生测试通过或测试断言失败；原始失败保留，最终 `d7c32f38…` 随后按相同默认 features 和原 test profile，实际执行完整 12 个 target；10 个非空目标的 137 项测试通过。原全包命令的失败状态没有改为通过。[第一次](effects/integrated-automation.json)；[第二次](effects/integrated-automation-retry-2.json)；[第三次](effects/integrated-automation-retry-3.json)

## 用户退出条件

| 优先级 | 工作 | 当前状态与未关闭边界 |
| --- | --- | --- |
| P0 | 固定同一组源码、lockfile 和配置 | **HOLD／部分实现。** 源码／owner 控件、绑定 probe 和所列 native 组件复验完成；普通入口完整闭环仍未获资格。移动 Chain 头另有源码／lockfile 变化，不继承本收据。 |
| P0 | Growth 与 PQ 融合 | **HOLD／部分实现。** 分配置测试通过；账户、服务身份、Growth 状态、真实交易、恢复及错配／降级拒绝尚未在一个融合配置成立。 |
| P0 | 关闭确认活性失败 | **HOLD／部分实现。** 原硬件的 4 秒／16 攻击者／depth 6 未重测；组件正确性不能关闭原失败。 |
| P0 | 完成真实效果协议 | **HOLD／部分实现。** 观察顺序与首终态边界已修补并通过最终 native；真实 frontier／provider／整库恢复的一次性权利闭环未完成。 |
| P0 | 独立审计最便宜合法 W1 | **HOLD。** 特殊输入、复用、预计算、硬件差异、量子 oracle 的成本下界及实际 fork choice／DAA 覆盖未完成独立审计。 |
| P1 | 完整模型 release 经 P2P 普通安装 | **HOLD。** 源节点与原缓存不可用时的完整依赖、真实加载推理和当前授权执行，尚无本代码对的闭环证明。 |
| P1 | 持续学习质量门禁 | **HOLD。** 隐藏／未来任务、家族预算、独立评价、负迁移及成本门禁未获新资格；旧 1/1 预算与 RSS 失败保留，合法无更新不包装为升级。 |
| P1 | 长期存储与账本保留 | **HOLD。** 权重续租／repair、全部 retained／fork roots、WAL、effect 观察历史及迁移临时空间尚未证明处于联合总预算内。 |
| 独立发布门禁 | 整链 PQ 六项要求 | **HOLD。** 全部授权根、迁移、量子共识、容量与独立端到端证据尚未齐备；安全声明保持不变。 |

## 证据边界与相对路径

原始收据、命令、完整源码清单、日志和失败记录已存于 [growth/](growth/)、[m06/](m06/)、[effects/](effects/) 和 [source/](source/)。[artifact-index.json](artifact-index.json) 逐文件记录字节数、SHA256 与 Git blob；[gate-status.json](gate-status.json) 保留九项原退出条件、实际证据和未关闭原因。大型原生 ELF 没有复制进仓库，其哈希、构建收据与无损压缩后的验证记录保留。

原 `invalid source_sha` wrapper 启动拒绝发生在测试执行前，继续作为历史记录保留。它与本次已完成的 `d7c32f38…` 源码控件和 native 组件收据分别记录。分项通过不自动关闭上表任何系统退出条件。
