# P0 共同候选与本轮实际结果

本轮把原恢复链、普通 Q24 LEARN、原始 Generator 训练回执和已复现的联合消费者修复收敛到同一候选。**P0 尚未完成验收**：缺少完整的原始 StageOwner 产品装配，以及同一冻结运行的 A→学习→独立 B→C 使用→冷恢复证据。这里不把组件测试或源码检查改称完整运行链。

## 已落实的代码

- 继承并保留 `source_sha` 与实际 checkout/tested SHA 的绑定。原修复来自 `dbb3bce393685469bd5587bb591d01099f1df697`，不是待重新修复的缺口。
- 合并 `0c99a30d` 的完整 CURRENT 恢复、`f97f3c90` 的普通 Q24 LEARN 和 `c7633658` 的原生 CI 维护修复。普通执行与只读恢复共享 canonical evaluation key，执行前身份核验保留。
- 新增原始 Generator 回执 owner：只从 typed 原训练 owner 读取完成结果；固定 Dataset、scope、已有角色和信任、签名 journal 与独立 witness。原 receipt、签名及签发时间一次持久化，冷读取不训练、不续签。Candidate、NoUpdate、错误绑定、Pending 和 lost-ACK 路径都有行为测试。
- 新增有界 Training 适配层，实际消费原训练 owner 与原回执 owner。单槽 permit 随 blocking worker 保留，等待者取消不提前释放；逐次验证 Dataset/scope/CURRENT。读回后用新时间检查 enrollment 与请求期限，再允许新 fit/首次 attest；原 Completed receipt 仍只按原签名窗口读取。
- RMCP 3.9 的 source-bearing discovery 错误恢复原分类与明确的有界重定向诊断，同时保留原错误链。
- 修复 unified exec 把有界历史交给可能落后的广播订阅者的问题：原进程先保留历史，再发送实时增量；轮询读取与历史分开。新回归覆盖慢订阅、两次轮询、退出后的 stderr 尾字节、关闭后订阅及精确省略计数。
- 两处现有失败测试保留原始 auth refresh / Matrix reopen 错误；没有放宽超时或验收断言。

固定候选源码为 `30a697c50e10abd56e61b6b84f28ac9ae9f32f5d`，tree 为 `b2a21d98380340b1c091006f4130aafdbeabca50`，集成 PR 为 [#5865](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5865)。代码身份、组件证据和未完成门槛见 [INTEGRATION.json](INTEGRATION.json)。后续证据保存于单独的证据分支，保持受测源码身份不变。

普通 LEARN 合并版的完整调用边界检查通过，覆盖 6,298 个 Rust 文件、213 个边界和 215 个受保护条目。新增训练回执的 138 项来源/变异检查与 217 边界、216 个受保护条目的静态检查另行保存，不把重叠测试相加，也不转称最终共同源的原生测试通过。

上一候选 `4073268e…` 的原生 CI 在 helper 构建阶段实际失败：旧 generation-use readback 未显式覆盖新增 `TrainingNoUpdateV2`，普通与 Root 测试均未执行。当前候选增加了明确拒绝分支及普通 actor 的回归用例；[原始失败记录](NATIVE_FAILURE_4073268.json)和完整 helper 输出已保留，新的 source-head CI 才能确认修复。

此外，同一旧候选的 Windows 原日志确认了另一项错误：恢复测试引用不存在的 `pending`。合并还残留同一 intent 的第二次 claim；仅改变量名会继续触发失败。当前源码恢复原 `claimed` 快照并复用原 coordinator，保留 backpressure、owner loss、readback-only 与不再训练的全部断言。两项修复已在后继 `6ecfa504…` 的实际 daemon/Windows 门禁中通过；新增 Training 适配层后的 `cb0598a…` 在下一轮编译阶段暴露宏歧义，现由 `30a697c…` 修复后重新验收。

### 本轮新增的九文件修复与验收

[完整补丁、来源、独立复核和边界](engineering/ci-fixes/REVIEW_AND_SCOPE.json)覆盖以下变更：

- `cb0598a…` 的 daemon 与 shared 均在六个新训练测试编译时产生 22 条 `E0659`。显式导入父测试原本使用的 `pretty_assertions::assert_eq`；删除这唯一新增行即可逐字还原旧测试文件，全部测试和断言保留。
- 旧 blocking 的三个 Prettier 失败已按固定 3.5.3 修复；watcher 测试的 guard 改为词法 block。旧代码已有显式 drop，故这里只认定 Clippy 作用域修复，没有声称观察到运行时死锁。
- Matrix 初始化错误保留失败阶段与原始底层错误；恢复失败后仍仅尝试一次 fresh login，双失败保留 restore 与 fallback。原有 5 秒期限、passphrase、KDF 强度、存储和成功校验未改变。
- 仅对 Bazel `crates` 中的 `matrix-sdk-store-encryption 0.19.1` 增加 `-Copt-level=3`，与已有 Cargo package 设置一致。旧实际 Bazel action 使用 opt-level=0 已读回；配置差异不能证明旧重开失败由 KDF 引起，也不能证明运行修复已经通过。

**兼容性：** `MatrixSdkError::Initialization` 改为带 stage/source 的结构体变体，新增 `RestoreFallback`，并移除 Clone/Copy/Eq/PartialEq。仓内现有消费者及六条精确错误分类断言已检查。`Error::source` 的双失败链只沿 fallback；restore 保留在字段和 Debug 中，没有宣称单条 source 链包含两个分支。跨 crate/目标平台的编译资格仍需新 CI。

当前已实际完成的本地检查绑定 local `03f4bfea…`，与发布源 `30a697c…` 的 tree **完全相同**：

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| `just fmt --base cb0598a…` | exit 0，源码 clean | 修改的 Rust/Bazel 格式 |
| Prettier 3.5.3 `--check` | exit 0 | 三个修改的 Markdown/YAML 文件 |
| `git diff --check` | exit 0 | 九文件源码补丁 |
| 标准 `just bazel-lock-check` | exit 0，105.212 秒 | `mod deps --lockfile_mode=error`；锁文件未改 |
| 四项独立源码复核 | 未发现复核范围内阻塞项 | 不是 native 执行或科研独立性证明 |
| `30a697c…` 完整 caller scan | 本次实际 exit 0 / PASS | 6,302 Rust、223 边界、218 protected records；不授予权限 |
| `30a697c…` Windows 选定原生范围 | 34 个唯一原测试 PASS | Python 与重复/变异探针单列；未选六个 Training stage 测试 |
| `30a697c…` daemon / shared / 全仓库 CI | daemon 首次下载失败；单次重试及其它关键 lane 待终态 | 不移植旧源码的通过数 |

[新候选的完整 caller 原始记录](caller-30a/RESULTS.md)已由 root 逐项复核：唯一一次完整 verifier 调用，707.986497 秒 wall、692.379395 秒 child CPU；9 个变更文件、CALLERS、verifier、HEAD/tree 与 clean 前后相同。218 个 protected records 对应 173 个去重路径，另有 223 个 privileged inventory records。原 stdout 与旧 cb 恰好字节相同，但新 before/after/执行记录绑定实际 30a 调用，未移植旧结果。CALLERS 的 codex-rs 范围完整包含 6,302 个 tracked/worktree Rust 文件；原 sparse 文档元数据预检失败发生在 verifier 启动前，已独立留档。

[标准锁检查原记录](engineering/bazel-lock/RESULTS.json)保留更早的资源保护中止和 PKIX 失败。后一次通过采用 Bazel 支持的显式 JVM startup 参数，使用系统受信 CA；TLS 和继承代理保持启用。检查未修改依赖声明，没有运行 native build/test。原 direct-dependency/annotation 警告保留，Bazel server CPU 和峰值内存未知；客户端开销不冒充完整服务器成本。

前一 `cb0598a…` 的 [daemon 完整失败归档](daemon-cb-failure/SUMMARY.json)与 [shared 完整失败归档](shared-cb-failure/RESULTS.json)分别确认 **0 个 native testcase**，不是 22 个测试失败。daemon helper 构建实际成功，随后编译失败；Root、维护及 post-test helper 验证没有到达。shared 的 15 项 Python execution-gate 测试通过，fresh JUnit 缺失是编译失败的后果。两份完整原日志和原始成员均保留；daemon 仅三个大源码 inventory 从交付压缩包中省略，但已完整解压逐字比较并记录哈希，未截断原日志。

[旧 blocking 原日志](blocking-6ec/RESULTS.json)还记录 Windows bindgen 下载 transport failure，不能归为 Rust 源码错误；Matrix migration 测试实际 1 项失败、2 项 ignored，重开报告 17.460891417 秒和泛化 Initialization，原因尚未判定。run head `6ecfa504…` 与实际测试 checkout `3fc1acb…` 不混用；二者 tree 相同的 API 证据另存。

### 30a 的新增实际读回与仍可推进的代码

[当前 Windows 原始归档](windows-30a/SUMMARY.json)包含本次 34 个唯一原始 native PASS（15+2+3+2+12）、6 个独立列出的 Python harness 检查、原始两例正向复跑和两个变异负控共 4 次执行。原 artifact 全 9 成员和完整 259,732 字节 job log 均保留；root 对源码、原日志行、哈希与恢复状态逐项复核。派生摘要中一处旧源码标签已更正并保存前后哈希，原 CI 证据未改。这里没有执行六个 Training stage 用例。

[当前 daemon attempt 1](daemon-30a-attempt1/SUMMARY.json)在 `cargo fetch --locked` 时因 thiserror-impl 的 crates.io index 连接出现 curl55/TLS unexpected EOF 而失败；helper 构建、ordinary、Root 和维护均未开始，native testcase 为 0。仅有原 checkout 快照，不能声明六阶段源码一致。原始失败归档后，[只对该失败 job 发起一次重试](current-30a/DAEMON_RETRY_REQUEST.json)，同一 source 的 attempt 2 为 job `130304826142`，与 attempt 1 独立记录。没有修改依赖版本、TLS 或断言。

[固定 30a 的接线核查](current-30a/wiring-handoff/HANDOFF.json)把源码缺口与真实材料依赖分开：生产 StageOwner composition、Dataset→Q24 来源/回执桥、Q24 训练结果的 governed Model 提案协议都是实际源码缺口。Model 作为基线已被允许；问题在于原 SGD 结果不满足 Parameter V3 的完整确定性重生成协议，不能强行转换。

一个更小且已有规则足以定义的源码动作已单独启动：将完整 CURRENT snapshot 适配到原 Training owner 的 exact Dataset prefix，读取并比较原签名回执。它不在冻结 30a 中，也不代替完整 StageOwner。真实 Dataset 特征/目标转换仍需要原持有人预先冻结的规则和源记录；这里不选择默认目标或从所需结果反推标签。原 key、journal/CURRENT、独立 anchors、B qualification 和 C use 仍必须由真实持有人交付并认证。本审查没有断言这些材料在所有外部系统中不存在。

### 历史源码的实际原生通过

[原始 CI 读回报告](ci-readback/RESULTS.md)保存 5 个 artifact 的成员索引、77 个原始文件及 6 份完整 job log。仅维护集成版本 `8c9c51e…` 实际通过 daemon ordinary 1,104 项、独立 Root parent 7 项和 shared 1,134 项；对应 nextest 排除/忽略数为 72、908、71。三个执行集合不能相加为独立测试或研究样本。daemon 的 fmt、fix、bins 均返回 0，六份源码 inventory 完整字节相同。

后继 `0b13…` 与 `407…` 的 Linux helper 失败由各自原 stderr 独立确认，不能用上述通过记录替代。前一候选 `6ecfa504…` 的 daemon 与 Windows 已有下述实际通过记录；新增适配层的 `cb0598a…` 随后的 daemon/shared 编译失败；当前 `30a697c…` 必须完成自己的 native、维护和全仓库门禁。

前一共同源 `6ecfa504…` 的 [Windows 原生门禁已通过](windows-6ec/RESULTS.md)：五次筛选执行分别通过 15、2、3、2、12 项，另验证原始攻击样例能被正向源码拒绝、两个有缺陷的原生变体按预期失败，四包格式检查与恢复后 tracked clean 均通过。这是私有状态、durable owner 与选定 Prompt Runtime 的资格，尚不代表完整 P0、全仓库 CI 或后续训练适配器通过。

[前一共同源的 daemon 原始归档](daemon-6ec/RESULTS.md)逐项核实了 ordinary 1,146 个 JUnit testcase、Root 7 个 testcase，均为零失败；另有 nextest 排除/忽略 72 与 948 项。原日志实际记录 Root UID=0，旧 ordinary XML 只作 Root 排除证据。六阶段均为 exact `6ecfa504…`/tree `9184583…`，14,399 文件的完整清单逐字节相同。该 lane 的 fmt/fix/bins 返回码均为 0、维护补丁为空；其 fix/bins 只覆盖 agentd、learning-artifacts、intelligence-eval。

适配层原组件的 9 项聚焦来源检查、223 边界/218 个受保护条目的静态 inventory 与独立源码审查通过；6 个原生行为测试已写入源码；`cb0598a…` 未编译成功，实际执行为 0，需以 `30a697c…` 新 CI 的日志/JUnit 确认。固定 `cb0598a…` 的[完整 caller scan 已实际通过](caller-cb/RESULTS.md)：6,302 个 Rust 文件、223 个边界、223 个 privileged inventory 条目，以及 218 个 protected-file 记录（173 个去重路径）。原 stdout 完整保留，前后源码、CALLERS 与 verifier 身份相同且 clean；该扫描不授予权限。详情见 [适配层检查与边界](engineering/training-stage/REVIEW_AND_SCOPE.json)。这些检查与历史测试重叠，不累计为新增独立样本。

一次独立的 exact `6ecfa504…`、单 job、本地三包 Clippy 命令在共享空闲磁盘降至 683,872,256 字节时受控中止（exit 130）；源码未改，运行测试为 0。完整记录保存在 [维护尝试归档](p0-maintenance-6ecfa504-attempt1.zip)。这次停止原因已知，但不能据此解释更早的 SIGKILL；最终 child CPU/RSS 和精确单调时钟耗时未捕获，仍为未知。

训练回执重开测试的范围是有效凭证/签名窗口内的文件对象重开，尚不是完整 daemon/Root 进程冷启动。过期签名拒绝续签，genesis witness 写入未确认时保持阻塞；两项限制均有新增回归代码。自 `cb0598a…` 起，原 native fit 与回执 attest/readback 已由 Training 适配层实际调用；回执 create/recover、适配层四个 public host 接口和完整生产 StageOwner 装配仍未接通。本目录不授予模型采用或生产权限。

前一 `6ecfa504…` 的 [shared owner 原生执行](shared-6ec/SUMMARY.json)也已逐项核实：实际 JUnit 1,184 项通过、nextest 排除/忽略 71 项，另有 15 项 Python 执行门禁。该 lane 与同源 daemon 有 884 个完全相同的 Agentd testcase，不能相加为独立测试或任务样本。旧 blocking 中 auth-refresh 所属目标只有缓存 PASS，可确认被选入，却未观测到精确用例重执行或内层诊断，详见[读回边界](engineering/AUTH_REFRESH_READBACK_6ec.json)。

前一 `cb0598a…` 的 [Windows 选定范围已通过](windows-cb/SUMMARY.json)：五次原生调用各通过 15、2、3、2、12 项，34 个唯一原始测试。两个原始攻击样例复跑与两个变异控制单列；另 6 项 Python acquisition harness 测试也单列，不能与待执行的 6 个 Training stage 原生测试混淆。完整日志、原 artifact 的全部 9 成员和精确 source/tree 记录均保留；该 artifact 没有 JUnit，计数来自实际 nextest PASS 与 summary。四包格式检查与恢复后 tracked clean 均通过。

## CTRL：本轮真正执行并读回的冻结诊断

[完整结果与原始文件](ctrl-gap/RESULTS.md)绑定既定源码、9,496,351 字节原训练记录、前后基线和原生回执。160 个状态来自 40 个既有训练来源；原覆盖 86，冻结的当前文本探针后为 87，即描述性增加 0.625 个百分点。

74 个原缺口中，1 个由固定数字格式投影补回，73 个只在同来源、同字段的其他历史状态中存在 scorer match。后者尚未证明普通 READ 可达、信息获取因果作用或最终选择成功。13 个状态受到本次探针预算截尾；历史生成器截尾仍全部未知。字段级统计保留 40 来源完整分母，缺少来源时保持 null。

原生文件回执记录 child exit 0，所有输入/源码前后哈希一致；远程 API 的两次同 key 请求仍是 transport timeout，durable job ID/权威进程终态未读回。二者分开保存。新模型调用、OCR、训练和新独立任务均为 0，采用仍为 NoUpdate。

## P1 的现有证据已更新

[RESEARCH_STATUS.json](RESEARCH_STATUS.json)分别引用各实验原发布身份，不能把它们当成共同候选的验收结果。

| Cell | 当前可用观察 | 尚未成立的结论 |
| --- | --- | --- |
| MEM6 | retention 30/84 对 28/84；selector 21/54 对 13/54；来源分别为 20 和 14 组 | retention 的单侧 95% 下界为 0；没有独立封存的新来源确认 |
| CTRL | 当前候选覆盖 86/160→87/160，40 个既有训练来源 | 73 个历史状态差异尚未转为可达的信息获取与任务收益 |
| PERC | 30 个合成任务×3 seeds；rules 90/90，global 49/90，dense 63/90 | 已有真实在线编码与普通文件 CLI，但未证明真实来源净收益或生产 daemon 接入 |
| ACT3 | 16 次拟合，640 个受控文件系统 episode；各 arm 均 96/128，1,600 primitive calls | 重复 16 个已暴露 probe 与 8 seeds 不增加独立任务数；未超过固定技能 |
| VERIFY4 | 226 项工程测试，72 条受控 confirmation row | 新独立真实任务仍为 0，不能替代独立终态裁定 |
| PRED | 159 项测试；12 train/6 dev 合成工程样本 | 原 owner 实际数据与独立 effect observer 未接通；189 fits 仍是开发执行量 |

P2、P3、P4 的实验顺序与准入条件保留，尚不开放机制优胜、拓扑收益或 RSI 主张。训练、搜索、失败、验证、恢复与通信成本只报告已测部分，未知项保持未知。
