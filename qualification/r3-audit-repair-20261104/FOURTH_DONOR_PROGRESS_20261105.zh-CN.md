# 新分支增量：固定 donor、实际资格与当前产品边界

本增量基于 2026-11-05 03:16–03:24 UTC 完整库存，三条重点 donor 的主源与 CI 读取始于 03:25，最后一次固定提交比较完成于 03:45:29 UTC。当前已发布产品仍是 Draft PR [#4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)，head `cabcb40d36e116beaa65750e1f674c52035da785`、tree `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`。以下 donor 没有合入这棵树，也不等于其后的未发布 native 工作树。

完整库存增加 15 个 Draft PR（#4809–#4823）和 30 个分支；旧 PR 中只有 #4729 的 head 改变。所有原 23 项退出条件与状态逐字段保留：8 项范围内闭合、14 项开放、B18 科学 HOLD。完整原件分为已冻结的库存归档与本次 86 件补充主源，未改写旧快照。

## 1. #4810：Windows OpenSSH 与 private-state

| 核查项 | 固定事实和边界 |
|---|---|
| 源身份 | [PR #4810](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4810)，head `c2243df72c7648414313519b9dbea16464f2c258`，tree `c295e85e9ac99301a487ef1599145c9e1e8e8910`，base `fbf786803f07e402bcaddbb8fbe3dd387f6b7688`。相对 base ahead 3/behind 0；相对当前 cabc ahead 496/behind 330。 |
| 实际改动 | 完整分页 20 路径、936 增/117 删。新 OpenSSH 文件通过系统 API 取得固定系统目录，保留输入/执行文件对象；未知子进程终态保留 pins 并拒绝无依据重试。另有 private-state/恢复文件接口和依赖/测试变化。本次将其中 6 个选定生产文件从原 preimage 用原 API patch 重建，postimage 全部逐字一致。 |
| 实际 CI | 当前 head 的 9 个 Actions 已终态：3 success、4 failure、2 skipped。Windows 原回归、private-state、blocking、UI 均失败。另一 head `44a466ce6592865b7bb2eab6ceb7465edcbfb3ab` 的 [lock run 41928528672](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41928528672) API 显示成功；本审计没有独立下载其工件或复核完整日志。 |
| 对当前 B11/B12 的意义 | 是待审 donor，不是当前原 3 个严格 Windows 失败的修复资格。当前窄 ACL、四格 DELETE/父 DELETE_CHILD 控制须在真实 Windows 同源运行。B12 原 2 正向+2 反事实的已闭合范围继续保留；新 private-state 改动不得覆盖这个范围或借用其资格。 |

本次未读取 #4810 新失败的完整 attempt，因此只记录实际失败状态，不把原正文中的“native pending”当最新结论，也不猜具体失败原因。新 branch-only 的 token/delete 观察及 broker 终态组件也已固定元数据；其声明仍要求原 Windows 验收。

## 2. #4812：普通 PQ 入口与 FinalUse

| 核查项 | 固定事实和边界 |
|---|---|
| 源身份 | [PR #4812](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4812)，head `3a8e50ddd79ec3e52ca58157323726c37069202c`，tree `eb83a32c16f3708ec852fd5b6b1f84299213bda4`，base `4c93a641945044f904a656cbf1d23e358a074d52`。相对 base ahead 8/behind 0；相对 cabc ahead 771/behind 470。 |
| 实际改动 | 完整分页 43 路径、2795 增/237 删。普通 `UnixFinalUseAuthorizer::open` 要求显式 `ml_dsa65_v2`；显式 classical `from_config` 仍可授权 effect。FinalUse 在 state lock 内重新读取完整外部 frontier，漂移或错误触发 fence；这不是跨 owner effect 原子性。7 个选定生产文件已由原 preimage/patch 精确重建。改动集合不含 Memory/state/SQLx 路径。 |
| 资格来源 | 当前 head 的 Actions 查询为 0。固定 qualification 明确 `HOLD`、`production_activation=false`。其中作者保存的原 native 330/333、诊断链接 3/6 均绑定 `1993db5510afb9764a4a4a60e5bd0f48862411ab`；default link SIGBUS 未执行测试，fix 遇 ENOSPC。完整交付代码 `7335636b2cbde4077e354dcb3156a04b9ee6e8a9` 还含后来 endpoint guard，记录明确 `NOT_RUN`。本次读取固定 qualification，未重新核其大 native 原日志。 |
| 对 B16/B19 的意义 | 可作为独立 PQ/FinalUse 组件迁移输入；仍缺动态 selector/Current、正常 Root/Session/联合 UI caller、真实资源 custody、跨 owner admission 和 WAN 接受。不能替代当前 SQLx native token、两个 pool caller、private recovery checkpoint 的独立工作。 |

后继 [#4821](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4821) 报告 SQLite operation/lease/FinalUse 的本地事务闭环，作者称 277 PASS/1 个既有 ignored，绑定代码 `771c221231df80b4cc29fce4b5ec46dc9edebf20`、tree `11a0d4147f2358d6f96ae7a0601f5b7314591402`。本增量只核其完整 PR 正文和固定 head；尚未独立核原日志。它自己的 public governed topology 仍以 `CellLifecycleAdmissionUnavailable` 拒绝，真实 Cell lifecycle 为 DENY_ALL，不能把组件进展写成 B16 全闭合。#4729 当前变为 `a53e6e2a7aacf4784e48c680a5980960a17d8a35`；正文未宣称新 continuation 已建立 native RED/GREEN，历史 198+198 不能移到这个新头。

另已读取 Chain 固定 [continuation README](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/963f2119cfa4f81d3fab225f3cf69c8e8d62b178/evidence/pq-workflow-continuation-20261104/frozen-d9954903/README.md)，blob `1f877b542159b75ff8c66a03c0cc9fcef9a84223`。它报告分别属于 47 源码/记录器、63 clock、57 PQ、4 native cache 范围的结果；464 pins/6 upstream 结构检查仍为 HOLD_NO_GO，且明确没有执行那些依赖测试。runtime endpoint 原生、真实 WAN/独立接受仍缺。本次只独读该固定报告，未下载全部 Chain 原件；这些不同分母也不替代此前历史 27/6/9/12 的范围。

## 3. #4817：Memory V15 协议参考与已执行的 53 例

| 核查项 | 固定事实和边界 |
|---|---|
| 源身份 | [PR #4817](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4817)，head `379c21c2e625c3a3dfbb514e11b9e8fe2213cda8`，tree `e8a254968ea75743b86dbba43e448e882b5f45a8`，base `6d2551388ed42355f02afbf528472ee2b4d8488b`。相对 base ahead 11/behind 0；相对 cabc ahead 449/behind 471。 |
| 实际改动 | 全部 33 路径为 32 个 qualification 内 Python/文档/收据及 1 个专用工作流；没有 Rust/native 产品改动。API 对一个 2358 行 receipts 文件未返回 patch，本次没有冒称逐字核完该大原件。 |
| 可独立确认的执行 | [run 41950367467](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41950367467)/job 126992613476 绑定 `386f7a4453b5e59e83db12d8bf958cfb5e4847d0`。完整原 job log 的 53 个不同 `ok` 名字与固定 checks.json 按顺序精确一致，0 skip。日志显示 2.792 秒；结构化检查进程 wall 为 2.846255476 秒，两者口径分别保留。两个已读生产 Python 文件的 SHA256 也与收据相等。386→379 的固定比较仅 README+4 个 CI 收据，没有 Python 或 workflow 变化。 |
| 不能扩大之处 | 同 host 的合成模型/控制平面含真实进程和 kill；CI 另做历史 Mac→pocket4 收据离线验证，没有重复跨设备动作或语言训练。当前 379 的通用 Actions 为 2 success/1 blocking failure。原 artifact ZIP 本次未下载，不能继承作者的 ZIP/CRC 核验。没有原生 Memory caller、独立多节点共识、硬件证明、整库回滚或完整科学成本收益资格。 |

这条参考实现对签名、来源、迁移、撤权和损失后的重试控制有研究价值，但不能将中央 SQLite authority 当成当前产品的可信 Root/Current owner，也不能将固定 408 字节有限整数夹具当模型质量或资源经济性证明。

## 4. 科学分支与下一步选择

#4798 仍是 `77b24407b9898aa44769502fbb22c24fb7193a58`，本次没有出现新原始训练结果。原 32 fits、4 个收益区间均跨 0、0/256 同时过全部八门的 HOLD 保留；本次 Actions 是 2 success/1 failure，与“四个科学比较”不是同一计数。

新 [#4823](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4823) 不能简单归成“只有工程控制”：其完整 PR 正文报告 5 个既有 fits、160 新 validation/320 新 TEST 世界与四个冻结主比较，有限 Bellman 的 J−C 在 IID/OOD 分别过自己的收益线；direct D−C 两组为 0。这里尚只核固定正文，未独立审核实验原件、统计脚本与完整成本。比较定义与任务不同，不能写为原 B18 的 D−B 成立。对已经曝光 TEST 世界的 Rust/MCP 重放是迁移一致性，不增加独立科学样本。

后续保持一个产品候选。先完成当前 A 的原平台验收与 B11 实物控制；B16 继续按已核 custody/native token/caller/checkpoint→完整 Current/normal producer/consumer 的依赖顺序推进。PQ/operation 两条 donor 先建立完整语义迁移表和同源资格；Memory V15 作为协议参考。在当前全量审计授权下继续独立核验#4823已存在的冻结实验原件、统计脚本与成本；若新增实验，先冻结协议和完整成本，不为获得正结果重定义原门。

逐 PR/head/tree/工作流、选定 pre/postimages、53 个精确用例、23 项原退出条件及证据层级都在机器索引中；本增量没有任何状态提升、native 执行或 ref 修改。
