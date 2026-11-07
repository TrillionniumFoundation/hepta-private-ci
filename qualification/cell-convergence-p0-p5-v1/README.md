# Cell / Memory / HCSN / resident / 权限与恢复统一候选

本目录固定一个可审验的组合及其资格标准。当前不是成功声明：P0 等待新候选
原始 CI；P2 的普通入口仍有实现与原生验证缺口；P1、P2、P3、P4、P5 均为 HOLD。
机器可读状态与五个完整 donor commit 位于 `COMPOSITION.json`。

## 固定组合与实际测试身份

| 组成 | 固定来源 |
| --- | --- |
| Cell / RSI 完整候选 | #5089 `9bbf4bb4d1b5466f62d75d6b70dad4d26ec75d55` |
| Cell、Memory、resident owner population | #4938 `f09dea504916d551e13fe36752dd1e833bcaa51b` |
| 普通 Cell 入口与 neuron V13 | #4963 `3b31842504121e8ae40909db1edc17e7790cf688` |
| HCSN、权限与恢复 | #5067 `a20ea6a862e501d8a4993195c7da1ac52ca9a7be` |
| Core / 产品入口 / final-use | #4855 `a86267a0525448870c47a641fb54cd510543ba7a` |

已记录的合并 commit 为 `a35f5162e084ad78f3ac8c29c4185879d093bfa0`、
`0f60efaf8bed433cf26131f36f7648b83b385015`、
`3ad3eb953b065134cf1c0d2b0b730940b0c28e48`、
`ab89bfceec021437eebd1e37f331f441076c76ac`；Memory 账本修复 commit 为
`dea4acd6f5d6892380972ce7fcf7e7cf1f88404c`。这些完整身份应在最终候选
祖先链中核对；集成记录本身不是原生或科学资格。

本文件不能预先写入一个包含自身的最终 commit 哈希。CI 必须针对真实 checkout
生成单独的绑定回执，记录 candidate head、`git rev-parse HEAD`、实际 tree、
base/merge SHA、checkout lane、workflow 源码身份，以及本目录 JSON、Cargo/Bazel
锁文件和 Rust toolchain 的 SHA-256。PR 的 head 与实际 prospective merge 可能
不同，必须分别保存，不能只抄 run 的 head 字段。新的 source/tree 不继承旧结果。

## P0：完整保留原始必需 CI

以最终 tree 中原 workflow 和 scope 逻辑为准。此次 workflow 修改会要求
`full_repo=true`；原 blocking fan-in 的 11 个依赖不能被一个新 optional
workflow 的绿色替代。保留 Architecture、Rust 与 Windows Bazel 的原 fan-in，
所有原平台、matrix shard、命令、测试分母、超时和失败判断。

收集同一 head 的所有事件与 run；逐 run 收齐每次 attempt 的每一页 jobs，并
保留 job/step 的失败、取消、跳过和未知结果。只有原条件证明不适用的 skip 才能
作为不适用项。缺失检测输出、`abandoned`、取消和未知不能改写为 success。
后台 branch protection 的 required-context 设置尚未被此连接独立读取，不能
将工作流名称冒充为已经验证的后台设置。

Cell 保留 #4963 的 helper 构建、V13 回归/example clippy、两个 cohort 和
composition 后的未过滤 workspace 测试，并绑定 fresh JUnit。HCSN 保留
source-and-owner、agentd-registration，以及 value_kernel、population_grid、
population_age 各自的 bridge、cancel、PQ-host wrapper；默认 ignored 测试
不能算成已执行。原 CPU fixture 不等于 GPU 研究 campaign。

CI 结果完整与大 artifact 全量下载是两个不同状态。必须保存原结果及足以判断
必要执行与源码身份的证据；大型日志包可保留 artifact ID/digest 与明确的本地
归档状态。一个返回的下载引用不能冒充已核对 ZIP 和成员。下载所有大包不是
额外新增的 P0 门；必要证据缺失必须明确保留，不能减少原门分母。

## P1–P5 的决定性标准

| 优先级 | 完成条件 | 当前缺口 |
| --- | --- | --- |
| P1 Memory 采用 | 新真实任务有预先规定的收益；旧能力满足预设保持条件；完整成本可比；正式采用后冷启动并用于下一真实任务 | 当前候选上的正向采用、保持条件、完整成本及冷启动/下一任务回执未闭合 |
| P2 Cell 运行体系 | 多种表示 profile、真实 worker、有界反馈 Circuit、取消、跨 owner 恢复在普通入口共同运行 | 普通 CLI 仅接 Joint；V13 与 Q24 Circuit 普通启动尚有实现缺口，之后还需完整普通入口 native |
| P3 分化价值 | 同初态、同可见信息、同容量、同累计训练预算、同选择性更新，胜过固定专家与未分裂两个强对照 | 历史 10 计划 / 6 有效 / 4 失败；未建立正向优势，失败 payload 与完整成本缺口保留 |
| P4 递归改进 | 后代实际接手改进，在同初始系统、隐藏任务和总预算下胜过前代改进器 | 缺真实后代改进器的匹配对照；lineage/rollback 协议测试不够 |
| P5 长期服务 | 同一候选、同一服务窗口同时衡量质量、尾延迟、有效吞吐、资源、故障恢复、状态增长与总成本 | 缺联合长期服务证据；局部 latency/history 探针不够 |

Joint OneShot 与 Resident 是同一表示契约的两个执行模式，不能据此计为多种
表示 profile。V13 的 typed bootstrap/example 以及 Q24 Circuit 的 explicit
owner 仍未连接普通启动。HCSN 的独立 TaskFlow/effect 也不是
`CellGenerationWorkerV2`。P2 必须先补齐这些入口组合，再由同一候选的真实
原生执行验证完整闭环；当前不能把缺口缩减为等待一次测试。

P3 原记录在 `qualification/cell-differentiation/strong-control-evidence/`。
其 readback 保留 3456 / 5760 个有效/计划测试预测与全部失败分母，缺失数据不补
零、不重建成原始 payload。归档审核成功只表示旧记录完整可读，科学决定仍是
HOLD。没有把协议/fixture 测试数量当作模型实验，也不将历史记录移交为新 head
的正向资格。

## 推进与关闭记录

每项关闭记录应同时给出候选身份、执行命令/profile、环境、原始回执、测量窗口、
预设门槛、完整分母、失败/重试成本与最终决定。任何新源码改动都应重新绑定
候选身份与适用原 CI；只更新一项证据不能自动关闭其他优先级。

本组合说明不授予生产权限。受保护的 desktop campaign
`hcsn-cuda-170run-20261105-r1`（job `1a1acdd69f2-fc05-5757`）没有因本工作
启动、重试或变更。

## 发布身份与源码等价

远端工作区未配置 Git 推送凭据，因此使用已连接的 GitHub Git Database API
发布。API 重新生成 author/committer 元数据，提交 SHA 随之改变；25 个阶段的
源码 tree 均逐项核对为完全相同，提交父链按同一映射保留。上列集成历史使用
GitHub 上可检查的提交身份；本地原始身份与发布身份的对应关系见
`PUBLICATION.json`。

发布身份记录作为额外元数据提交加入，不预编自身最终 SHA。正式 CI 仍必须
绑定实际 checkout；发布前运行过的诊断，包括已经失败的权限扫描，不直接
转移成新 head 的通过结果。
