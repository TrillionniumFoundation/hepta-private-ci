# learning.operator 第二轮对抗审计与优化收敛

日期：2026-10-01。基线 PR #1305 的源码提交为 `831be9ed2ac480039eb0f229dd423effff3315a7`；本轮最终工程源码为 `84c633367fa5452f241d4ff5254e0c12ee19d939`，其 GitHub tree 与本地源码 tree `5b7f191b91800ecf9e108151eff510edbf7e2c2f` 一致。本轮同时复核 main 的最新提交 `a126987b84737dbc2ee2592442a314117bddb4a2`，以及独立 learning.eval 开发分支 `3714b7e1c2513e0e79ad8560a80fda480aca9471`。未把后者的认证 facade 当作真实测量资格，也未盲目合并整个分支。

本文接续[第一轮报告](learning-operator-adversarial-audit-20261001.md)。第一轮的测试、性能、变异和 CI 结果保留为历史证据；下列第二轮结果仅覆盖对应实际源码与命令，不继承完整候选资格。新源码先完成检查，再进行格式与导航固化；各 at-run source-hash 清单保留其真实字节，不替换成事后提交身份。

## 文档与模块定位

详细技术开发文档确实存在，并非只有 README。核心资料为 `TECHNICAL.md`、`DEVELOPER_GUIDE.md`、`ADMISSION_CONTRACT.md`、兼容/容量/shadow policy、操作 runbook、原生符号映射、STATUS/schema、实现地图及执行 dossier；Holder Bellman 与纵向评估规范定义了更大的算法和验收范围。本轮补齐开发 overlay、完成度矩阵、时间单位、V2 进程信任迁移、实际存储恢复以及 partial integration 的真实边界。

operator 是慢路径候选生成器：ledger 拥有真实冻结源集合；operator 产生有界不可变 fit；eval 的真实估计器、fenced holdout CAS 和 fsync sink 产生资格；独立 selector 产生选择；artifact owner 持久化；Agentd 只读消费。认证、资格、选择、存储、使用及激活是不同边界，任何一个 hash 或签名都不能替代其他边界。

## 新发现与修复

| 问题 | 风险/反例 | 本轮修复与回归 |
|---|---|---|
| 公开 signed V2/V3 可从 caller metrics 直接发资格 | 有效签名不强制真实 estimator、holdout 消费或 durable qualification publication | 原始决策入口 crate-private；消费者必须提供真实 ProductRunner sealed receipt，并在最终使用重新认证精确 bundle/current trust。独立外部 compile-fail 验证私有入口。 |
| Product qualification seal 漏公开决策字段 | Ineligible→Eligible、baseline/failed metrics 变更可能不改变 seal | seal 绑定全部公开决策语义；真实 Ineligible→Eligible 与 Eligible 字段篡改回归。 |
| 纵向签名窗口可与实际评估输入分离 | 旧 observations 重新贴未来窗口、数量、snapshot 或 source cut | 绑定实际 joined decision/outcome 时间、数量、snapshot roles、source commitment 和 cluster；严格一一窗口覆盖，排列不变、重新分组摘要变化，真实重签错窗口仍拒绝。 |
| 真实输入资源检查太晚 | 巨额 actions/targets 在检查前排序、复制或计算 | released entry 先检查 rows/actions/总 cell/窗口上限；request ctor 在 clone 前检查实际签名 shape，并清理 Vec spare capacity；StableId 丢弃多余 String capacity。 |
| root distribution 过期未被 final use 保留 | 行签名仍有效、root 已过期仍 fit/返回 | ActivatedTrust 保留真实 root 签名窗口、activation 与已知撤销；issue/use/terminal/fit 完成和最终校验后都重验实际时间。新增 retained evidence 也纳入共享 memory meter。 |
| selected clock 或 token 可以停止推进 | 冻结 caller now、重新 load 延长 TTL、操作中越界；宿主先前跳再冻结使新适配器暂停 TTL | 共享 host highwater+monotonic anchor，在前跳观测时重新锚定；前后使用和最终释放检查，已观察过期不能回拨或重载复活。 |
| process bootstrap 使用裸 trust、request 时间 | 真实启动与运行消费未强制 root-signed distribution/host clock | 显式 V2 descriptor，校验真实 root signature 后才开 owner stores；runtime 持有真实 host/monotonic clock，旧请求时间不能冻结 TTL。旧 schema 不隐式升级。 |
| 训练与评估只靠不同 freeze ID 分离 | 两个 ID 仍能包含同一 source record | 两个真实 LedgerWriter 分别验证 receipt owner，实际 source set 不相交；每 set 4096 上限，排序/双指针替代 O(N×M) 查重。 |
| 真实 artifact persist/qualified read 缺少适配器 | generic coordinator fixture 不代表真实 owner 接线 | 新真实 owner adapter、readonly publication-status reconciliation、ProductRunner persistence API、qualified V3 read-only loader；保留 exact retry/unknown storage identity 和 postwrite expiry receipt。 |
| CURRENT 读取失败可让缓存继续用 | 损坏 CURRENT 后恢复旧副本可能复活 | test-only raw reader 修复失败锁死；新的真实 owner adapter 每次刷新实际 CURRENT，任何失败永久关闭该 consumer。二者验证范围明确分开。 |
| storage selection/head 窗口只在验证时检查 | 验证后延迟 load/predict，或完成阶段越过 TTL | opaque storage selection 与真实 CURRENT 保留已认证窗口，在实际 load/predict release 重验；持久化在真正 write boundary 采时，耗时验证后的过期不得开始写入。 |
| canonical registry 与 native structs 不一致 | 名字相同被误认 wire parity | 三个真正的 untrusted V1 transport codecs：canonical order、strict unknown/duplicate/noncanonical rejection、bounded nested JSON。缺 Bellman field schema 显式拒绝，不伪造 native bridge。 |
| Serde feature 改变 object/number 语义 | arbitrary_precision/raw_value 内部保留 key 可将对象解释成不同 JSON 类型 | 拒绝 `$serde_json::private::` 成员，限制深度/节点/字节，默认与三 feature 回归一致。 |
| source readiness 未覆盖整个实际构建输入 | dirty tracked files、ignored 新 binary/test/build/config 或不足依赖树可混入 | 完整 checkout 检查、Cargo 自动发现输入检查、七个 owner/type source roots 和 registry/control objects 精确投影；不以 assume-unchanged/skip-worktree 掩盖修改。 |
| exact-source/merge shell stage 未真实记录执行 | 失败 emit 未必终止 verify，stage 命令可与执行不一致 | 真实 shell function 经 stage 执行器、准确 command/tee/exit；失败 23 的反例必须停止并留 failed stage。 |
| STATUS→map / qualification receipt 允许数值替身 | Python `False==0` / `True==1`、版本 `3.0==3` 接受不规范输入，即使重算摘要仍过关 | 值与类型同时匹配；整数/浮点投影及重哈希收据反例，精确版本整数、布尔类型和字段集合。 |
| 宿主 CI 与控制投影漏新版进程路径 | 独立 audit 有测试，但 authoritative source/merge 阶段未跑新进程组；单改 V8 resolver 不触发 audit | source/synthetic merge 真实执行 runtime/bootstrap/process tests，使用现有 checksum-verified V8 resolver，纳入实际 helper/package 控制源。 |
| retained raw logs 被 git whitespace gate 拒绝 | 修改日志会破坏 stdout 哈希，原 CI 阻塞真实 | `.gitattributes` 只对两份审计 raw-log 目录关闭行尾 whitespace 检查；保留日志原字节，属性本身进入 source/control inventory。 |

fixture 的修改保持真实 owner、abstain、fsync、签名及预注册统计门槛。微秒级过期正向夹具改为秒级真实有效期；统计正向夹具采用真实独立 1024 clusters 和实际 policy/weight envelope，未放宽生产 alpha 或 primary gate。

## 完成度评估

| 层次 | 当前状态 | 尚缺什么 |
|---|---|---|
| bounded reference、tabular、discrete world model | 有实现及算术/资源/完整性回归 | 不能宣称覆盖全部 Holder 算法。 |
| owner-bound final-use / selected inference | 有真实 owner/签名、累计预算和实际时间 fencing | 未知后续撤销与 owner/registry/stop 变化仍须 host 每次刷新。 |
| sealed cross-owner qualification | 工程强制链已实现 | provider 测量真实性、独立长期科学接受仍是独立事实。 |
| artifact persistence / readonly qualified load | 真实组件和 named product persistence API 已实现 | 一次完整默认运行中的 fresh-process shadow 与 exact durable rollback 尚未接齐。 |
| generic coordinator | 状态机及恢复语义实现 | remaining owner ports 和 configured default runtime invocation。 |
| registered canonical transport | sensor/regularity/applicability 三个 V1 codec 实现 | Bellman exact field schema、enum/member semantic specification、真实 context-bound native bridges。 |
| 文档、状态与资格工具 | 详细文档、机器状态与 source-bound 证据控制实现 | 最终 PR/head、deterministic merge 和实际 main merge 各自统一成功的 protected qualification。 |
| 科学、target host、deployment | 不自封完成 | 独立 efficacy/applicability/calibration、目标 host 容量、operator acceptance、canary/promotion/activation/release。 |

确切算法缺口：reference 仍接受 supplied reward/continuation，未实现 local-model integration、monotone interpolation 或 antithetic paths；sensor 是有限集合覆盖，未建立 continuous-domain hull/OOD/anisotropic reconstruction；neural branch/state/action trunks、residual amplification/support 和 optimizer 训练控制未实现；实际世界模型 one/multi-step calibration、change point、future retention 与 prediction-error modulation 测量链仍缺。规范允许 qualified simpler reference，但它必须获得相应独立 bounds，不能因使用 tabular 就自动获得完整资格。

不把符号数或测试数换算成完成百分比。`defaultLoopWired=false`、完整 native `canonicalWireAdaptersImplemented=false`，所有独立接受、production implementation、activation/release 仍为 false；新增五个字段只记录实际工程组件。

旧 CURRENT 已被合法扩展时，旧 ack 的精确重试返回 `PersistedButNotCurrent`；只读 reconciliation 仍保留其存储事实。这个兼容变化避免把历史成功写入当成当前可用授权。

## 验证证据与限制

最终验证清单见 [validation.json](learning-operator-audit-20261001-round2/validation.json)。清单保留成功、真实失败、资源阻塞和修正后的重验，并记录 exact command、exit、raw bytes/hash 及 source file commitments。

| 实际范围 | 结果 | 限制 |
|---|---|---|
| types/contracts/ledger/artifacts/operator/eval/intelligence/shadow-qualification 八库联合 | 811 passed，4 skipped | 本地 scoped unit suites，非完整宿主或科学接受；范围有交叉，不将各行简单相加。 |
| operator 兼容 feature | 125 passed，2 skipped | 显式测试兼容配置，无默认 raw bypass。 |
| 真实 owner V3 ignored profile | 1 passed | 有界 owner qualification path，非目标 host 容量。 |
| contracts 三个 Serde feature | 12 passed | 保留不同 JSON feature 的类型/规范化反例。 |
| 独立外部 API consumer | 19/19 | 3 正向、16 compile-fail，私有入口与 seal 不能逃逸。 |
| 最终格式化 Agentd 组件源码 harness | 35 passed，0 skipped | 230 项 at-run 输入哈希前后不变；真实 path dependencies，不能替代完整 Agentd class/build。 |
| evidence / Lane E / V8 Python 回归 | 27 / 15 / 6 全通过 | 包括重哈希类型篡改、真实 stage 执行及 merged-lock V8 校验。 |
| operator default/compat all-target strict Clippy | 均通过 | `-D warnings` 仅用于 operator；八库 fix 的其他既有 warnings 保留原始日志。 |
| scoped fix、just fmt、改动文件格式与语法 | 通过 | 46 个无关 Python 自动格式差异已回退；不宣称整个仓库 Python lint 无警告。 |

机器清单保留已纠正的编译/fixture 失败和 broad Python lint 尝试，不用它们冒充成功运行。

完整 Agentd/app-server/V8 宿主编译在本地受容量阻塞，不能用 source harness 或六个 dependency crates 测试替代。已把真实 Agentd all-target compilation、owner/consumer tests 和 V2 daemon process fixture 加到 CI；V8 使用现有 checksum-verified archive+binding resolver。未取得结果的 CI 必须标为 pending/blocked。

全仓库文档/实现地图 gate 还受基线中的历史分支锚点阻塞：`41b2...`、`22cd...`、`1133...` 与当前源码实际为 diverged，不能作为祖先凭据。本轮刷新12 个合法导航（含当前模块），并单独纠正 ledger/artifacts 的 path-only 当前导航；旧 map 字节、hash 和 DIVERGED 事实保留，无历史 execution/science 证据转移。其他模块的 immutable integration provenance 与严格 verifier 保持原义，全仓库 gate 仍不能宣称通过。

全 workspace 与真实 Bazel 本轮未通过，不用删测试、模拟库、放宽 gate、合并其他模块或改 authority 状态来补数字。原第一轮七规模 debug 性能观测与 9/9 true mutation kill 仍仅是历史有界回归，未冒充本轮最终 source receipt，也未冒充 target-host/longitudinal science 接受。

## 收敛条件

每个可复现工程 finding 都经过修复与反例回归，再由独立只读 reviewer 检查；最后只读轮在已实现的有界范围内没有新增可操作反例。generic coordinator 仍委托 trusted owner ports 提供独立当前宿主时间和同步任务 deadline；本轮真实适配器的时钟保证不被泛化为尚未接齐的 ports 已获证明。这个结论不是“全模块已完成”或“未来不会有问题”。上述默认完整链、算法/协议设计及独立验收缺口保留为真实剩余工作，不以仓库自身签发的 receipt 将其清空。
