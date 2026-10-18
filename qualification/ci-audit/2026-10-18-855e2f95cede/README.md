# HEPTA 开发接力执行 checkpoint — 2026-10-18

## 本轮已经写入远端的结果

本轮共向两个既有 PR 快进推送 9 个代码/源码映射提交，未强推、未合并、未修改保护规则或校验器。两条修复都保持原分支和实际依赖关系。所有尚未完成的门禁继续计为未闭合。

| 修复线 | 当前 HEAD | 已实施变更 | 本地验证 |
|---|---|---|---|
| [#2599](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2599) | a4728553d2f09242640400719d82257bc9c63c73 | 四份 Rust 测试文件/测试区块改用 typed Result；追加修正两处 Context 编译回归；原严格 CLI 重绑受影响映射 | Rustfmt、diff、derived 通过；锁定依赖的小型编译复现通过；完整 workspace/native 测试未启动 |
| [#2714](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2714) | f191cd081ba16fed8827a18093b5a5b39e9a36cd | Reader/Harness/Stem 显式证据声明、校准等级不可覆盖、拒绝非布尔 authority marker；5 个可审查阶段、9 文件 | 最终 109 项 Python 契约测试通过；独立分阶段复核通过 |

#2599 保留全部断言和平台限制，未引入 #1350 所依赖的 218 个 Intuition 功能提交。四份映射仅更新 sourceBase/sourceObjects，执行、激活与验收声明完全不变。三个旧映射的锚点不在 main 祖先链上，原迁移器正确拒绝；本轮保留其原文和失败证据。全库严格资格结果是 main 29 个失败模块、源码候选 30 个、最终候选 26 个，不能称为全库通过。详细对象与原始日志见 PR2599_MAP_FINAL.md、FINAL_PR2599_MAP_RECEIPT.json 和归档。

#2714 修复了可实际复现的证据完整性问题：缺失声明曾被有利默认值填充；caller 曾能把明确 LOCAL 的 calibration 改为 REAL_SHADOW；Stem 曾接受字符串或未知值；可选 authority marker 曾接受 null、整数 0、浮点 0.0。新行为明确拒绝这些情况。布尔声明本身不证明科学独立性，全部输出仍 DENY_ALL，研究继续 SHADOW_ONLY / NO_GO。

## 真实环境与权限

可访问主机是 2313cba36518。15:30:22 UTC 快照观察到 16 个 worktree 和 11 个可见进程；进程、cwd、dirty 文件、输出位置及遮蔽后的 argv 在 RUNNING_TASKS.md 和 host_snapshot.json。该主机未被独立识别为用户指定的 Dot/Hepta 专用工作机；没有已验证的项目 SSH 路径，因此其他主机状态为 NOT_ACCESSIBLE。

本会话已实际验证 GitHub 读、创建 Git 对象和按 expected SHA 快进更新既有分支的能力。完整 branch protection 读取返回 403，#2714 研究目标分支的完整保护不可访问；main 的规则不能直接转作研究目标分支的保护证明。runner 管理端点不在插件允许范围内；无法据此统计 org 的 online/busy、runner groups、并发配额或利用率。

主机可见 9 CPU、cgroup 配额 8 核、内存上限 8 GiB。overlay 可用空间为 0。Hepta 全库原生构建预检在 Cargo 启动前拒绝，因此没有把“未执行”计为通过。随后针对两处类型错误运行了独立的小型 Cargo 编译复现，范围和锁定版本另有记录。独占 tmpfs 完整 checkout 用于真实提交与源码映射验证；未删除并行 owner 的工作区、模型权重或缓存。该临时目录易失，唯一证据已归档入仓。

## 全量基础清点及其边界

Hepta 在 14:20:04-14:23:41 UTC 的完整分页快照为：

- 2,519 个唯一分支；26 个数据页，随后空页。
- 2,846 个 PR；29 个数据页，随后空页。
- Open 1,553，其中 Draft 1,526、非 Draft 27。
- Closed 1,293，其中 merged 315、closed-unmerged 978。
- 2,519 条分支相对 main 的 git 图关系全部核验：same 2、包含 main 且 ahead 289、only-behind 28、divergent 2,200。
- Open PR base-ref DAG 共 1,250 条边，未发现环；684 个分支未关联 PR，仅记录事实，不判定应删除。

完整 raw 页、页哈希、normalized inventory、git graph 与 DAG 在 inventory-evidence.tar.gz。BRANCH_PR_DAG.md 说明了实际依赖。该结果不等于完成 2,846 个 PR 的逐 diff/review/历史 CI/科学材料语义审查；名称分类只作候选，不能授权淘汰或合并。

PON 对比实际确认 #1504 的 wrapper 通过 4/4 故障注入单元测试，#1501 同组为 2 pass / 2 fail；这证明了该 wrapper 在日志管道错误传播上的改进，未证明完整 Bazel/PoN/平台资格。#1508 对当前 #1468 缺少大量基线提交，#1509 的两份自有提交只改两文件格式。旧 PR 顺序不能替代当前语义与依赖核验。

## CI 与队列

完整两 PR 快照随后推进到 17:36-17:37 UTC：共 52 个 jobs，15 success、1 failure、1 cancelled、7 skipped、27 queued、1 in_progress。#2599 的 19c5 source-head 编译失败促成了末节记录的追加修复。新 a472 HEAD 在 18:00 UTC 读取时生成 6 个 queued jobs，required 汇总均未出现；不能继承旧 HEAD 结果。各时间窗及错误日志见 CI_MATRIX.md、PRE_REPAIR_CI_SNAPSHOT.md 与 POST_REPAIR_CI_CHECKPOINT.json。

14:31:49-14:32:35 UTC 对 441 个非终态 run 的完整 latest-attempt job 分页读取，共 1,587 个 jobs：494 queued、168 in_progress、393 success、137 failure、220 cancelled、175 skipped。队列年龄中位数 24.56 分钟、p95 61.62 分钟、最大 76.99 分钟。成功数包含各 job 的局部结果，绝不是完整 required-CI 通过数。

其中 296 个非终态 run 没有 job 记录；它们不是 runner 占用证明。所有队列数都是有明确时间窗口的观测，不能推出 org 空闲容量。对 exact main 的 51 份 workflow concurrency 源码已校验，当前证据不足以安全改变 org 资源策略；未执行取消、重跑、改 labels 或减平台覆盖率。

## 模型实验和 OS 联动

本轮没有启动本地真实模型推理。推送触发的既有远端 Reader intake 随后在精确 f191cd081… 上完成 64 次新鲜 Laya typed-choice 推理，三份非权重 receipts 已下载并校验；终态观察与复算见下节。历史档案确有 40 calibration + 72 nine-arm 行，但属于 10 月 13-14 日运行，不能替代新 HEAD 的新实验。另一 owner 的 10 月 18 日 fresh attempt 完成 6 个 calibration 答案、0 evaluation，第七次没有返回后 watchdog 终止。历史批次、该未完成批次与新的 64 次四臂诊断都保持独立，不拼接充数。

较早的 64 次 Laya Reader / 四臂指标保留为历史局部证据；本轮新执行的 64 次单独绑定新 HEAD、run 和 artifact。两者均缺完整独立 heldout calibration、设备/概率/FLOPs/内存/能源 join，继续 HOLD_NO_GO。共享 Encoder、NDU/System2 和多模态方向仍需真实受控消融与预算测量，不能用这 109 项契约测试证明能力提升。

OS 仓库在 15:22:56-15:23:29 UTC 完整清点 167 branches、185 PR；open 20（Draft 16、非 Draft 4）、merged 109、closed-unmerged 56。main 为 f9e306f76154590e096a42f70ce9de0a7c859e60。#193 在所观察 HEAD 有 7 checks / 4 runs success；#194 是 0 checks / 0 runs，不能计绿。仍是 Hepta #2815 -> Desktop #193 -> #194 的未合并依赖栈。

该桌面项目具备可继续整合的接口与权限契约基础。当前被审查 native effect dispatcher 只支持 QueryAbi，其他控制操作返回不支持；G1/G2、生产 issuer、持久递交/撤销和 Final-use 资格未完整闭合。因此目前不能将其当作已具生产资格的桌面/移动端控制器。详见 research-os-evidence.tar.gz 中的完整审计与 20 个 open PR 的检查表。

## 下一阶段

BLOCKERS.md/BLOCKERS.json 为未闭合清单，REPRODUCE.md 为固定 SHA 的可执行验证入口。优先在可访问且有独立磁盘的原生 worker 上完成 #2599 的 Cargo/Clippy/三平台验证，同时处理当前精确 HEAD 的真实 CI 失败；继续保持源码映射原身份、科学资格和外部 effect 权限的拒绝边界。

本 checkpoint 的结论是“修复已推送、证据已归档、门禁未闭合”。没有后台本地训练或编译被宣称仍在运行。远端 queued run 仅按实际 run ID 和观测状态记录。

## 归档与完整性索引

| 文件 | 内容 |
|---|---|
| inventory-evidence.tar.gz | Hepta 全部分页、normalized branch/PR、全部分支 git graph 与依赖证据 |
| ci-evidence.tar.gz | 已审查失败日志、独立复核、两个新 HEAD 的两次完整 CI 快照 |
| research-os-evidence.tar.gz | 研究修复、真实测试日志、历史模型 recount、OS 全部分页及 20 个 open PR 检查 |
| runtime-evidence.tar.gz | 遮蔽后的完整主机/dirty 文件快照、全 active-run/job 快照、源码映射原始失败归档、报告生成器 |
| final-ci-addendum.tar.gz | 16:24-16:25 UTC 完整两 PR CI 快照与已完成 job 日志 |
| laya-terminal-evidence.tar.gz | 新 HEAD 上实际 64 次 Laya 调用的原始 artifact、receipts、API、源码与执行日志证据 |
| final-ci-pre-repair-evidence.tar.gz | 17:37 UTC 两 PR 完整 CI、19c5 编译回归和原始源码/日志 |
| pr2599-context-repair-evidence.tar.gz | 锁定版本编译复现、两行修复、严格映射、Git 对象导入及 a472 新 CI 原始快照 |

大体积 JSON 保留在对应归档内，包含 host_snapshot.json、SCHEDULER_SOURCE_AUDIT.json 和 PR2714_PUBLISHED_CHECKPOINT.json。ARCHIVES.json / FILES.json 给出 SHA-256 与 Git blob；每包成员有独立清单。观察窗口内的其他 worktree 可能正在被其 owner 创建或写入，dirty 快照不构成允许覆盖、删除或终止任务的依据。

## 后续 HEAD 与分片归档

15:57:09 UTC 再次读取发现 #2688 和 #2695 的并行分支已经前进；完整新 HEAD 与检查记录见 [LATEST_HEADS.md](LATEST_HEADS.md) / [LATEST_HEADS.jsonl](LATEST_HEADS.jsonl)。以上较早快照仍保留原始观测时间，不能转作新 HEAD 的通过证明。

四个归档以有序二进制分片保存，避免未获确认的大请求被误报成功。`ARCHIVES.json` 列出每片实际 Git blob、字节数、SHA-256，以及完整归档的身份。先运行 `python3 reassemble_archives.py --verify-only` 校验全部片与串联结果，再运行 `python3 reassemble_archives.py` 在本目录恢复原始 `.tar.gz`。脚本不解包、不执行归档内容，已有不同内容的目标文件会被拒绝覆盖。`runtime-evidence.tar.gz` 已作为完整文件保存。

## 末次执行进展（16:24-16:37 UTC）

[FINAL_CI_ADDENDUM.md](FINAL_CI_ADDENDUM.md) / [final-ci-checkpoint.json](final-ci-checkpoint.json) 保留随后一次完整分页快照：两个已推送 HEAD 未变，17 个 jobs 中 2 success、14 queued、1 in_progress，0 failure、0 skipped。#2714 的 Stem/Reader bridge 在精确 `f191cd08…` 上实际完成 27 + 109 项 Python 契约测试；#2599 只完成 Actions 语言 CodeQL，其他四种语言仍 queued，额外 CodeQL 汇总为 neutral。两个工作流汇总均未生成，不能计作完整 required CI 通过。新增完整 raw JSON 与两份执行日志在 `final-ci-addendum.tar.gz`。

16:37:01 UTC 对同一主机再次只读采样，观察到 12 个可见进程，工作区磁盘可用字节仍为 0；见 [FINAL_EXECUTOR_STATE.json](FINAL_EXECUTOR_STATE.json)。16 个 worktree 和完整 dirty-path 清单仍明确标注为 15:30:22 UTC 的较早快照，没有用新的进程时间覆盖它们。三个协作审查任务已完成，未遗留本审计启动的原生构建或本地模型任务。

## 随后确认的新鲜 Reader 执行（16:46-16:55 UTC）

[LAYA_TERMINAL_CHECKPOINT.json](LAYA_TERMINAL_CHECKPOINT.json) 与 [ROOT_LAYA_VERIFICATION.json](ROOT_LAYA_VERIFICATION.json) 记录对单个 Reader run 的终态读取和两次独立计数/计分复算；这不是完整 CI 矩阵的再次刷新。[run 39140341757](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39140341757) 的两个 jobs 均 success，Reader job 117713314446 在 16:24:39-16:27:02 UTC 实际执行，exact source 为 f191cd081ba16fed8827a18093b5a5b39e9a36cd。日志为 `reader_status=evaluated`，没有走允许标记 INCOMPLETE 的 exit-2 fallback。58,507 字节 artifact 12143240868 的 SHA-256 与 API 和上传日志三方一致。

本次为 16 个任务 × none/distractor/withheld/full 四臂 = 64 次冻结模型 `predict`，seed 17。模型为 convaiinnovations/laya，固定 revision c5d78730f3493e4fe16d61507ef4b78eef7318cf；snapshot SHA-256 为 ac8e18d65b026edf4d2c856ba7e3aa72df28fc8ec0f6a771f3b7ff1f372da036。报告输入 token 合计 12,422；逐次预测 wall 合计 63.78450276 秒，evaluator 总计 63.7905 秒。未报告的 FLOPs、峰值内存、能源和金钱成本保持未知。

| 臂 | 样本数 | 按证据条件回答/弃答正确率 | top1 命中仓库 gold 比例 |
|---|---:|---:|---:|
| none | 16 | 0.125 | 0.4375 |
| distractor | 16 | 0.375 | 0.3125 |
| withheld | 16 | 0.125 | 0.5625 |
| full | 16 | 1.0 | 1.0 |

前一指标在证据不足的三臂要求 UNKNOWN；后一指标只比较 gold，不能混称。复核确认了 artifact 完整性及 64 行的唯一性、算术和计分一致性，尚未完成独立事实 gold/引用链与科学置信资格审查。运行警告具体涉及 `choice:11+` 温度夹取至 0.5，不能直接断言本次选项头必然受其影响；独立校准 receipts 仍缺失。本批没有 40 次独立校准或 72 次九臂实验，也不证明参数学习、NDU/System2 或生产选择资格。研究继续 SHADOW_ONLY / DENY_ALL / NO_GO。

## 追加的 CI 回归修复与当前门禁（17:37-18:00 UTC）

最终复核没有停在排队状态：[19c5 source-head job 117713683668](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39140469435/job/117713683668) 实际编译后发现本轮 e214 测试改动的两个 E0599。ProviderEffectBindingError 只有 Debug、没有 StdError；String 也没有 StdError，二者都不能直接使用 anyhow::Context。此前静态审查漏掉了这两处约束；此前本地原生预检停止，未完成 workspace 编译。

新增 [e6945558](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e69455587d2709c34b6b1832ed1aa4fca9025aeb) 仅添加两行显式错误转换，保留原 context、Wiremock `.expect(1)` 和生产前缀字节；新增 [a4728553](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a4728553d2f09242640400719d82257bc9c63c73) 由原严格 CLI 更新 runtime.agentd sourceBase/sourceObjects。其他非祖先 anchor 继续拒绝，最终严格资格仍是相同的 26 个失败模块。

独立审查溯源了全部 43 处新增 Context。随后对仓库锁定的 anyhow 1.0.103 核对 crate checksum 和全部 54 个缓存源码文件，使用离线、locked 的小项目复现“修复前两处 E0599，修复后编译通过”。这仍是小型类型约束复现，不能替代完整 Hepta/native/platform 测试。完整证据见 [PR2599_CONTEXT_REPAIR.json](PR2599_CONTEXT_REPAIR.json)。

#2599 当前 HEAD 为 a4728553d2f09242640400719d82257bc9c63c73，已按 expected 19c5、force=false 快进并回读确认。新 [blocking-ci 39151714945](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39151714945) 与 [Architecture 39151714876](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39151714876) 仍需真正完成；18:00 UTC 采样的 6 jobs 均 queued。新结果只计入新 HEAD。未合并任何 PR，研究继续 SHADOW_ONLY / DENY_ALL / NO_GO。
