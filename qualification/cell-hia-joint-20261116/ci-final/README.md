# HIA／Cell／runtime 联合执行与学习闭环：最终 CI 证据

执行源码：Cell `f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb`；runtime `73b5c33d5762eefc0554a86750094350f18ae6a0`。本目录所在审计提交只增加证据，不更改经过测试的执行源码。

**共同候选、真实 native HIA—GRU Cell—runtime 调用、持久经验、完整 NoUpdate 和冷恢复已经在同一次候选中连通，专用联合 CI 通过。两处学习均未采用新权重，尚未证明采用后的新任务收益、长期收益或相对普通工具 agent 的优势。**

## 1. 交付入口

| 入口 | 内容 |
| --- | --- |
| [Cell 联合 Draft #6400](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6400) | 冻结、实际 runtime 桥、MEM/PRED 实验、独立复核 |
| [Cell owner Draft #6399](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6399) | 状态所有权、取消／未决处理、版本隔离、有限迁移 |
| [HIA Draft #902](https://github.com/TrillionniumFoundation/Hepta/pull/902) | 编译后的 continuation 桥与 native loader 修复 |
| [runtime Draft #132](https://github.com/TrillionniumFoundation/hepta-runtime/pull/132) | macOS 构建修复及真实生成的 ledger 身份更新 |
| [联合 CI 43802821002](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43802821002) | SUCCESS，测试源码 f8 |
| [独立原始证据复核](RETAINED_REVIEW.json) | PASS；复核期间未重新运行模型、native 或 runtime |
| [原始 CI ZIP](original-artifact.zip) | 444 个文件、3,600,870 字节，原始内容保留 |
| [最终交接记录](FINAL_HANDOFF.json) | 原始 run、candidate、决策、成本、限制与逐文件摘要 |

父目录 README/GATES 的 `pending_at_publication` 是 f8 发布时的历史快照。这里补充该次 CI 的终态。先前失败、旧 Mac 候选和本次 Linux CI 候选分别保留，不拼接为一个实验。

## 2. 冻结身份

外层 runtime-bound candidate SHA256：

`b54097ee0d2dc4af3fbdbe46e4e268adad8b381041ab5e164e15c741553e6fe6`

| 对象 | 固定身份 |
| --- | --- |
| Cell 执行源码 | `f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb` |
| Cell tree | `5d81c485091a73b1d438a15c59c35ec2db27bc8f` |
| HIA compiler 基线 | `f33d8da316de8fdf27b504371f1a5310997ff548` |
| HIA 变更与 loader 来源 | #902，`8ba46fc7a112fc220cdcbbd48dc5d24fda76a738` |
| HIA 程序 SHA256 | `89f18f52e77f19ce596bab12a695cf354e76e5a78ff814996588ffc12fbace6a` |
| native image SHA256 | `c475a22313d401e84d5e0b13c935aabb4615c6da15aba3e6083f842d35f54812` |
| runtime source | `73b5c33d5762eefc0554a86750094350f18ae6a0` |
| runtime binary SHA256 | `8a00d4d6edf6ce5a7c374eccf16605d1e18a043d9fa990215bbc736861de6130` |
| runtime config SHA256 | `3cd6f5979ca0fbf9b94803da50918a18b2175553c9e9024bf537f77a2029ef30` |
| origin local candidate SHA256 | `c4346645d251510924861fba918ee75b9be0c8e0d7778859d099b3ab58fc49ad` |
| 设备与依赖 | Linux x86_64；Python 3.12.16；NumPy 2.3.5；float64；记录 host、Python／NumPy／BLAS 二进制摘要 |

完整身份见 [candidate.json](runtime-joint/candidate.json)。`source_bases.cells` 是研究基线 `bb34e073...`，并不冒充本次执行提交；列出的执行源文件及完整字节摘要、原始 CI checkout 记录共同绑定 f8。生成的模型版本另带外层候选和 runtime pins。数据、模型／优化器状态、编译记录和执行计划均保留在原 ZIP。

本次 OMP／OPENBLAS 线程变量为 1，其余列出的线程环境变量为 null，不能套用旧 Mac 的配置。

### 原配置缺口与精确重建

原 `runtime-config.json` 位于私有目录，未进入 CI 上传。candidate、实际作业及冷读会话均绑定同一配置摘要。后来使用 ZIP 内冻结生成器、原 `canonical()`／`write()` 和保留的 profile、SSH setup、candidate 路径，一次确定性重建得到 1,082 字节，摘要精确匹配。

- [重建配置](config-reconstruction/RECONSTRUCTED_RUNTIME_CONFIG.json)
- [输入映射、来源与摘要证明](config-reconstruction/CONFIG_RECONSTRUCTION_PROOF.json)
- [只读重建脚本](config-reconstruction/reconstruct_runtime_config.py)

分类保持 `RECONSTRUCTED_FROM_FROZEN_GENERATOR_AND_RETAINED_INPUTS`，`original_config_archived=false`。它是摘要相同的重建件，不是原 ZIP 中的文件。未猜值、搜索序列化、执行模型／runtime／sshd 或改写原证据。

原资格器的 `runtime_binary_build_provenance_verified=false` 保持不变。另有 CI 构建成功、构建前后干净源码和二进制摘要记录，但不冒充密码学签名的生产者证明。

## 3. 实际执行与恢复

实际 MCP stdio runtime 初始化、发现工具并调用 process_start，经受配置约束的 operator／SSH 入口启动真实 worker。worker 执行编译后的 HIA continuation，通过 owner 适配器调用 Python／NumPy GRU；结果、模型状态与精确 receipt 先持久化，再恢复 native continuation。

| 实际作业 | job id | 首次启动 | 新 runtime 冷读再次启动 | 冷读结果 |
| --- | --- | ---: | ---: | --- |
| Cell 桥接 | `1a1e297f00d-1bff-1` | 1 | 0 | 完整 terminal 对象及 stdout／stderr 字节一致 |
| MEM/PRED campaign | `1a1e297fa3f-1db4-1` | 1 | 0 | 完整 terminal 对象及 stdout／stderr 字节一致 |

两作业 exit 0、stderr 0 字节。每次冷读用新 runtime 进程，对原 job 执行 status／read／status；没有重新提交工作来伪造恢复。

Campaign 有 **722 次完成的 native continuation**（MEM 265、PRED 457）、**208 次真实 CPython 编译**、**32 次有效 Adam 更新**、**2 次完整 NoUpdate**；该 campaign 未决记录为 0。协议原字节、数据库、模型调用、编译结果与终态 witness 均可复核。

模型计算仍由 Python／NumPy GRU 执行；native HIA 承担控制和 continuation。实际执行利用现有 operator 权限，不构成普通 daemon、Rust FinalUse 边界或 OS 进程沙箱的资格结论。

## 4. 学习结果与能得出的结论

两处均完成 A 经验 → 训练候选 → 留出的 B 评价 → 决策 → 选中版本 C → 冷进程新推理。每处 16 次 Adam 更新，最终均保持原版本。

| 指标 | MEM | PRED |
| --- | ---: | ---: |
| B：冻结模型 | 2/8 | 2/8 |
| B：关闭学习 | 2/8 | 2/8 |
| B：任务内部重置 hidden state | 2/8 | 2/8 |
| B：训练候选 | 6/8 | 2/8 |
| B：确定性基线 | 8/8 | 8/8 |
| A 保留：冻结 → 候选 | 2/8 → 6/8 | 2/8 → 2/8 |
| 最终决策 | 完整 NoUpdate | 完整 NoUpdate |
| C：实际选中版本 | 2/8 | 2/8 |
| 冷恢复新推理 | 与重启前精确一致 | 与重启前精确一致 |

见 [原始 RESULT](runtime-joint/campaign-worker/campaign/RESULT.json) 和 [交叉复核](RETAINED_REVIEW.json)。`ordinary_adopt`／`ordinary_no_update` 均为 0；两次 NoUpdate 属于实验 owner，不给普通 daemon 的更新机制记功。

MEM 候选改善未成为已采用能力；PRED 没有改善。原门槛要求超过确定性基线，而该 fixture 的基线已 8/8 饱和，因此它无法证明严格超过基线的 Adopt 收益。门槛没有放宽，B 没有用于追加调参。

A/B/C 使用同四种语法模板的留出实例，成功标准是 CPython 编译。它们不是独立真实任务分布，也不验证程序语义。`no_memory` 是任务内部 hidden state 重置，不是关闭跨会话经验。长期记忆贡献、普通工具 agent 对照及真实维护收益仍未测量。

## 5. owner、取消、未知效果与迁移

实现与控制验证覆盖持久 owner、版本／分区身份、原 receipt 重读、错误、取消和未知成本保留。取消请求不等于完成；硬退出后的未知效果不自动重放，也不清零原预算预留。

联合 CI 的 48 项控制和 16 项本地 native／GRU 冷启动／故障检查通过。HIA #902 的独立 native 检查为 21 个方法、175 个子检查，失败／错误／跳过均为 0。它们不与实际 campaign 统计混算。

故障控制故意保留两项 pending：硬退出后的原效果／成本未确定，以及无法取得精确原结果。Campaign 的“未决 0”不等于所有故障场景全局无未决。

迁移实现限于同 owner、同 partition、空闲、无待决／外部效果、兼容 recurrent state/config 的 readout 升级。已有原子交接、旧版本新写入隔离、精确旧 receipt 重读和 journal 错误回滚。任意拆分、跨 owner 迁移和在途外部业务效果交接尚未完成。

## 6. 本次候选成本

| 指标 | 本次值 | 范围 |
| --- | ---: | --- |
| runtime 资格器总墙钟 | 10.206825 s | 本次执行／观测／冷读等，不含 Rust 构建和整个 CI |
| campaign runtime 窗口墙钟 | 5.784268 s | 嵌在上项内 |
| 内层 campaign 墙钟 | 3.203572 s | 两 Cell、尝试／对照、IO 与冷子进程，嵌在上项内 |
| campaign 父进程 CPU | 2.263849 s | 不含另列子进程 CPU |
| MEM／PRED 训练墙钟 | 12.651 / 12.733 ms | 候选复制与 fitting；不含调用方数据准备／serving |
| MEM component p95 / p99 | 2.700 / 3.309 ms | 不含 owner admission／settlement 和任务编译 |
| PRED component p95 / p99 | 2.706 / 3.176 ms | 同上 |
| MEM／PRED 冷模型子进程墙钟 | 243.340 / 213.358 ms | 整个子进程，不是内部函数局部计时 |
| MEM／PRED 冷子进程 CPU | 241.012 / 211.673 ms | 子进程自身 |
| 能耗／实际 campaign 峰值 RSS | null / null | 未测量，不以 0 代替 |

嵌套窗口不可相加。组件延迟不代表端到端任务 p95／p99。构建、完整验证、先前失败尝试、切换、迁移、队列及全项目成本仍不能由这些数字推出“完整成本可接受”。独立 local lane 的 RSS／冷启动分位数不移用到实际 campaign。

精确数值与字段路径见 [proof.costs](config-reconstruction/CONFIG_RECONSTRUCTION_PROOF.json) 及原 RESULT／review。各 CI step 原日志见 [successful-job.log](successful-job.log)。

## 7. 修复、CI 及历史记录

本轮修复了 native loader 的 fd 路径复用可能别名到旧镜像、macOS 所需纯 array_index 函数被 Linux cfg 隐藏、一次性 SSH fixture 因 /tmp 路径被 StrictModes 拒绝三个真实问题。分别使用摘要绑定／sealed memfd／存活期引用、移除错误平台 cfg、在真实账号 home 下创建私有目录。认证、host-key 与 StrictModes 检查保留。

cfg 改动改变源码摘要，旧自动生成 ledger 因此正确失败。用原 CLI、原固定 artifact 和 59 个固定上游 Git 文件真实执行 restore → generate → check-mapping → 29 项 ledger 测试 → authenticated check 均成功。完整 JSON 对比只有三个源身份标量变化；229 个工具条目的 OPEN 状态、summary、行为门槛不变，没有手改门槛。

| CI | 结论 |
| --- | --- |
| [HIA 43794923319](https://github.com/TrillionniumFoundation/Hepta/actions/runs/43794923319) | SUCCESS，source 与 native jobs 通过 |
| [联合 43797077251](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43797077251) | 早期 native 测试导入失败，后续跳过，原始记录保留 |
| [联合 43800566412，c277](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43800566412) | native／runtime build／48／16 通过，随后 SSH preflight 失败，尚未实际调用 Cell |
| [联合 43802821002，f8](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43802821002) | SUCCESS，实际 runtime、冷读、campaign 与独立 review 全通过 |
| [runtime 43795217971，5f](https://github.com/TrillionniumFoundation/hepta-runtime/actions/runs/43795217971) | FAILED：旧 ledger mapping；此前 exact-head 2,633 Rust、9 filecap、29 ledger 测试通过 |
| [runtime hygiene 43801996390，73b](https://github.com/TrillionniumFoundation/hepta-runtime/actions/runs/43801996390) | SUCCESS |
| [runtime 完整 43801996435，73b](https://github.com/TrillionniumFoundation/hepta-runtime/actions/runs/43801996435) | 04:48:30 UTC 快照仍 in_progress；两个 job 在 isolated tests；mapping 尚 pending，不能写全绿 |

较新状态见 FINAL_STATUS 和 runtime-status 快照。旧失败不会被后来的成功覆盖。原失败日志及 ledger 生成记录见 [prior-ci-originals.tar.gz](prior-ci-originals.tar.gz)、[逐文件摘要](PRIOR_CI_ARCHIVE.json)。

旧 Mac controller／Linux worker 候选 `2a8e8759c7e1941f184fde2463a13a9d39dfa9edcf00c8a5ae475ad81dd3b469` 仍绑定 Cell `12cd0514...`、runtime `5f7f03a1...` 和不同 binary/config/native image。其三作业／三冷读、321 个原文件在父目录单独保留，与本次两作业／两冷读分开。重复同 fixture 不算新增独立真实任务样本。旧 tmpfs 丢失的实验不获得本次证据信用。

## 8. 六项目标的真实状态

| 目标 | 当前状态 | 尚缺验收 |
| --- | --- | --- |
| P0 共同最小候选 | 冻结与受控实际执行通过 | 原配置缺口已以精确重建披露，不宣称生产者签名证明 |
| P0 真实 Cell—HIA—runtime 桥 | 真实入口／模型／经验、已完成作业冷读通过 | 普通 daemon、FinalUse、OS 隔离、任意在途业务效果恢复 |
| P0 MEM/PRED 学习闭环 | 两个完整 NoUpdate，C 与冷恢复通过 | 实际 Adopt 后新任务收益与跨多轮重启保留 |
| P1 三类更新同 runtime | 参数候选／拒绝完整；有限 readout 迁移有控制验证 | 实际 runtime 中完整成本下降的代码采用、有收益参数采用、更完整迁移实例 |
| P1 长期可塑性／分化比较 | 部分冻结／不学习／任务内 state reset／确定性对照 | 容量、数据、推理、训练、评价配平的 head／拓扑／kernel／controller 长期比较 |
| P1 完整成本与恢复 | 分层计时、冷读、未决、NoUpdate 原因可审查 | 端到端 tails、能耗、峰值内存、队列、构建／切换／迁移／验证完整成本 |

下一轮需要预注册可区分的持续维护任务族，覆盖环境变化和语义／回归验证，保留独立 B 的评价机会；不能在本轮 B 追加调参或降低采用门槛。先得到实证 Adopt → 新 C 收益 → 多轮任务与冷恢复后保留，再按相同总资源比较普通工具 agent、关闭学习、固定拓扑、不保留跨会话经验、确定性监督与完整候选。

本轮形成了继续该实验的共同执行基础，也得到了明确的拒绝更新结果。尚未证明自适应结构优于普通 agent，也不据此宣称新的操作系统或“生命体”成立。

## 9. 原始性与只读复核

原 ZIP SHA256：`c549a22e56c12cdb09f9ea9708557c3f5164c803020c25aa72e47912c3d9cd7a`。[成员索引](MEMBER_INDEX.json) 记录 444 文件。数据库复核从 63 原始 campaign 文件取得逐字节相同的 61 文件快照，仅省略两个已证明 0 字节 WAL，保留 SHM；原文件前后摘要一致。

[只读 reviewer](review_ci_artifact_v2.py) 核对原 JSON、协议、candidate、image、训练／决策、冷推理与文件摘要，不执行 task code。初版因预期状态拼写不一致在出结论前停止；[修正记录](REVIEW_V2_NOTE.json) 保留事实，v2 检查冻结 producer 的实际拼写，未修补原报告。

ZIP、嵌套归档和成功日志的[扫描](SECRET_SCAN.json)显示具体私钥／token 模式命中 0、未解决命中 0。一个宽泛规则命中经 AST [分类](SECRET_SCAN_CLASSIFICATION.json)为编译器静态 image 标识，非凭据。私钥不在上传产物。

所有工程变更仍为隔离 Draft。活动重写／默认分支以及已安装 runtime、配置和既有凭据保持原状态。
