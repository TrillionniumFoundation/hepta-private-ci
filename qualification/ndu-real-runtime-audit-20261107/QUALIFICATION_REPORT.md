# NDU 真实运行交付：源码、材料边界和计量验证

## 当前结论

**原始源码已补齐，材料元数据核验已真实执行，新计量实现已通过真实模型运行验证。完整研究准入仍为 HOLD。**

本轮在原 HeptaRuntime 通道执行，GitHub 发布继续使用原 Mac 的 `ProfHepta` 身份。工作进入独立草稿 [PR #5326](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5326)，基于原结果 [PR #5321](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5321) 的 `e2144ff750bd15b89cd5f1b8306f84298e0899fa`。未合并到 main。原协议、pilot 材料、模型、selection lock、统计阈值与已有结果保留。

本报告区分三种结论：材料元数据一致；计量实现及其集成路径通过限定验证；科学收益、完整 retention 和 native owner 最终使用仍未通过。这些结论不能互相替代。

## 1. 精确源码已经可以审查和复现

原 pilot 的 23 个实现文件已从原运行主机读取，并对照原计划和既有成本取证 pin 逐字节核验。原样导入提交是 `e77e575ff7eaa96fd8e61abb4c362ffe9fbfaed2`，包含 236,992 字节源码；另有原始 manifest 和 README。所有新增路径在父提交中原先均不存在。

原样导入覆盖材料获取、来源分组、注册、OS 隔离、评价器，及真实 OCR、神经模型、控制器、训练、搜索、episode、矩阵调度和 native worker。之后的改进采用独立提交；原 pilot 的实际运行文件未被原地替换。

原始文件身份见 `ORIGINAL_SOURCE_MANIFEST.json` 与 `original-source-readback.json`。后续两个实际运行版本分别绑定 `FIRST_ATTEMPT_CODE_MANIFEST.json` 和 `FINAL_CODE_MANIFEST.json`，失败版本作为独立历史版本保留。

## 2. 材料注册已经实际核验，覆盖边界也已明确

真实来源是 `jsdnrs/ICDAR2019-SROIE`，固定 revision 为 `bffe40c26759f3376ec2b3ae9031dbba54cd587c`。987 张原始票据中 896 张合格，91 张排除。注册包含 286 个 merchant/duplicate groups，以及 3,548 个 case。286 包括没有合格 case 的组，因此不等于下表 active groups 之和。

| 注册角色 | 有合格 case 的来源组 | Cases | 任务族覆盖 |
| --- | ---: | ---: | --- |
| train | 97 | 1,630 | 五类，每类 326 |
| development | 54 | 525 | 五类，每类 105 |
| confirmation | 68 | 1,160 | 五类，每类 232 |
| retention_validation | 27 | 44 | 仅 complementary 标签 |
| retention_test | 27 | 189 | 仅 complementary 标签 |

新增 `scripts/ndu_real_materials/coverage.py` 已在原 ai395 主机实际执行。它以确切 SHA256 读取 registry、完整 case catalog、exposure、registration 和 selected sources；核对来源／episode 身份、角色隔离、材料别名、case 全清单和实际选样。该命令不打开元数据所指向的答案、参考文件、图片或模型。

原生 job `1a1b84b3a86-12894-e12` 成功退出，完整 stdout SHA256 为 `6283bdfd875545b11277c05ccbc2e40edebdf941c0bac1aca4046eb8117688b0`。机器结论为 `METADATA_CONSISTENT_SCOPE_INCOMPLETE`：零元数据一致性问题，八项 retention 覆盖缺口。

已核实实际选择的 40 个训练来源组、8 个调优来源组、20 个 pilot_new 来源组、20 个 pilot_retention 来源组互相分离，并排除了此前公开预览暴露的一个 development group 和一个 confirmation group。剩余 67 个 confirmation groups 和 27 个 retention-test groups 是材料容量，不是已完成的确认样本。

**五类是同一真实票据领域中的五种工作流。** 配对变体保留原 source/episode group，不生成新的独立来源信用。两个 retention 角色各缺 text_sufficient、selective_refinement、preparation_required、continuation_not_worthwhile，共八项缺口。完整数字与限制见 `material-coverage.json` 和 `MATERIAL_EVALUATOR_AUDIT.md`。

## 3. 评价隔离是真实 OS 边界，主体认证仍有缺口

重新取回并核验了原 isolation-probe-v3 结果，实际环境为 Linux、Landlock ABI 8、seccomp、干净环境和关闭继承 FD。13 项对抗访问均被拒绝，覆盖 private 路径、其他 episode、来源 archive、父进程信息、链接、网络、进程内存及子进程继承。Torch/Pillow 在同一隔离边界内实际成功执行。

原 `isolate.py` SHA256 为 `3e9d5c07a72257c3411d5ceff0f7d923f9f85bd2e9cd112ed9b496eb77d44ace`，与原攻击回执绑定一致。原证据在 `isolation-report-v3.json`；它支持实际软件隔离，不是仅 API projection。

评价器在 actor 退出后由独立进程执行。其固定源码 SHA256 为 `6c79c906eb021069f8e3df36dc2029909d2dd152a47dbc30ad64b1391ba59cfd`；rubric SHA256 为 `fee667c32ec08286bbaf4e9f70b6489aff55bc7d790dca37fc657e5350084300`。scorer 在读取对应参考前拒绝 confirmation 与 retention_test，并且不把未来分数反馈给 live actor。

原范围声明同时明确：同一研究者设计／实现 rubric，不等于独立任命并独立控制的原生 evaluator principal。源码身份、OS 隔离、独立治理身份是不同条件。目前尚无真实 evaluator/owner 认证闭环。

## 4. 真实控制器与模型的范围

原研究实际执行 frozen 与 joint 两种 regime，保留 A/B/C/D：A=Ordinary+Light，B=Ordinary+NDU，C=Hepta+Light，D=Hepta+NDU。固定策略、VOI、MPC 和 initial 基线均在 Ordinary/Hepta 两种 core 上保留，合计 12 个 arm。

原模型是票据专用神经适配器，15,132 个存储参数，其中 content 8,093、auxiliary 7,039。它运行真实像素 OCR、文本候选选择和区域调整，图像交付为实际来源像素的 PNG 裁剪。其 Hepta 路径逐候选创建新状态并执行一次 `core.step(..., 0.5)`；不承载跨动作递归状态，不证明所有 Hepta 再生／循环机制，更不等于通用自由文本和图像生成模型。原声明全文见 `ORIGINAL_EXECUTION_SCOPE.md`。

本轮计量验证沿用已经锁定的实际 checkpoint 和策略，不重新训练或调参，不从当前结果重选 strongest，不消耗 confirmation。

## 5. 新计量已接入实际执行

旧 Meter 把包络中没有显式阶段的时间差全部加到 sync。原 11,680 行部署聚合中，sync 为 24,454.796655 秒，约占 84.4%；因此不能把这个数字直接解释为实际同步开销。

新 `span_meter.py`、`interval_costs.py` 及运行路径接线提供：

- 实际 monotonic/process CPU 纳秒端点、进程／线程／operation 身份、父子 span 和哈希链；
- create-only JSONL，逐事件 fsync，并同步 journal 的目录项；
- 原始事件回放和精确区间排重，拒绝越界、重叠、重复 operation、缺失／截断／被替换的日志；
- host 与 actor 进程 CPU 的显式范围，子进程启动和 OCR 子进程 CPU 不伪装成本进程计量；
- 启动、等待和未标注工作保持 UNKNOWN，失败／被终止进程保留开放前缀；
- journal 回放和对账的实际 observer tail 计入部署 wall、UNKNOWN 与自身 CPU，净延迟效用支付这部分成本；
- compact matrix 行保留 schema、计量范围、未知时长、raw digest、actor digest、observer-tail digest 和未闭合状态。

完整 raw journal 留在 actor 允许写入的输出目录；回复通道仅发送摘要和 raw digest。host 稳定读取完整日志，核验闭合、摘要、operation 和哈希后才计入成本。原 4 MiB 输出上限保持不变。

最终序列化和输出持久化在 observer-tail 端点之后，仍属于外层 original-attempt 计量。energy、provider charges 和未观测部分继续为 null／UNKNOWN；没有以 TDP 或假定功率换算能耗。

## 6. 两次真实验证，全部 240 次尝试保留

两轮均取第一份已训练 fit、全部 24 个 arm/regime profiles，以及一个已使用 development source group 的五类工作流。每轮 120 次是执行覆盖，只有一个来源组和一份既有 fit；不提供新增独立任务或训练重复信用。

| 实际轮次 | Completed | BudgetStop | Failed | 原始区间对账 | 资格状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| 第一轮 a05f… | 101 | 11 | 8 | 120/120 | FAILED |
| 修复轮 b038… | 109 | 11 | 0 | 120/120 | PASSED，限计量集成 |
| 保留分母 | 210 | 22 | 8 | 240/240 | 不把首轮失败删除 |

第一轮 native job 为 `1a1b852687c-12894-e4f`，实际 exit 1。8 次失败全部是 preparation_required 上的 B、D、MPC、MPC_Hepta，两种 regime 各一次。详细计量事件进入回复流，产生 4,206,496–4,248,974 字节 stdout，触及原 output_limit；隔离器 SIGKILL 进程，已持久化的 5–6 个 journal 仍保留。实际原因见 `first-attempt-failure-inspection.json`。

修复轮 native job 为 `1a1b85a7c49-12894-e9e`，实际 succeeded、exit 0，日志完整、持久化确认且 stderr 为零。40 项 native 测试先通过，然后 120 次真实模型执行全部进入终态。8 个 failed retry 链与 112 个 revalidation 前驱链均在新运行前绑定旧结果文件 SHA256；原输出、身份和成本均保留。

修复轮 phase elapsed 为 56.057259 秒；各部署包络相加为 418.851210 秒，其中 249.133091 秒明确为 UNKNOWN。外层任务 wall 之和为 428.691046 秒，任务进程及已回收子进程 CPU 之和为 305.158203 秒。并行任务之和不等于 elapsed，外层与内层计量也不能相加。

`failure`／`retry` 专门分类中的零仅表示没有单独记录该分类的 span。失败和重试运行中的 encoder、critic、planning 等工作仍须计费，不能把这些分类的零解释成没有失败／重试成本。逐尝试与前驱类型成本见最终实际文件清单审计。

随后，独立文件核验 job `1a1b86230ab-12894-ef0` 实际检查了 4,053 个普通文件、411,211,392 个唯一文件字节，回放 1,142 个 meter 身份，并核对 23 个原源码 pin 和两个版本合计 60 个源码 pin。240 个 operation 唯一，所有请求都有一次派发和终态；232 份 scorer 回执均存在且一致，只有第一轮 8 个 actor 失败按执行顺序没有后续 scorer。没有发现不一致。

| 保留的实际尝试组 | 次数 | 部署 wall 之和 | 外层任务 wall 之和 | 外层进程及已回收子进程 CPU |
| --- | ---: | ---: | ---: | ---: |
| 第一轮失败 | 8 | 72.909679 s | 75.420423 s | 23.987887 s |
| 第二轮显式修复重试 | 8 | 88.715409 s | 89.426383 s | 32.352376 s |
| 第二轮其余重新验证 | 112 | 330.135801 s | 339.264663 s | 272.805827 s |

8 个显式重试的终态是 6 Completed、2 BudgetStop。完整两轮 240 次的外层任务 wall 为 831.665030 秒、外层 CPU 为 576.520116 秒；这些包括第一轮成功尝试，而上表只突出失败、重试和第二轮重新验证。部署与外层时间不能相加；第一轮尚未在部署包络内计入 observer tail，其外层时间包含这部分工作。

核验源码、完整 240 行清单及机器报告随本目录交付。文件哈希和回放可以核对实际 artifact 连续性，不赋予 Cell journal、FinalUse、可信 host owner 或下一任务消费的认证信用。

原始与修复轮摘要见 `first-attempt-summary.json`、`final-attempt-summary.json`，权威进程回执见 `NATIVE_EXECUTION_EVIDENCE.json`。40 项测试覆盖真实子进程、杀进程后的开放前缀、篡改／重放拒绝、compact transport 和 observer tail。审查范围和作者关系见 `FINAL_CODE_REVIEW.json`；该软件审查不是研究任务的独立评价者认证。

本地 source-only 环境没有 `just` 或完整 Rust 工作树；尝试 `just fmt` 返回 command-not-found，没有把它记为通过。未修改 Rust，也未执行或声称通过全仓库测试。

## 7. 原科学结论保持不变

原最终分析包含 11,520 个 primary episodes 和 160 个 incumbent retention episodes，共 11,680 行，其中 10,360 Completed、1,320 BudgetStop。完整研究库存另含采集、调优等阶段：22,320 个 episodes（19,891 Completed、2,429 BudgetStop）与 154 个 training jobs。后者包含 8 个 content、144 个 fit 网格任务以及两项 collector 初始化；独立训练重复仍然只有四份。

原完整库存审计 job `1a1b6b25d0c-12894-5f7` 成功退出、integrity problems 为空。其任务 CPU 总和为 65,676.214072 秒、任务 wall 总和为 66,172.632504 秒，均不应误称并发总 elapsed。详见 `original-research-inventory-control.json`。

原 [24 项结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e2144ff750bd15b89cd5f1b8306f84298e0899fa/qualification/ndu-real-results-20261107/all-24-contrasts.json) 保持原值：

| 原 net 对照 | frozen | joint |
| --- | ---: | ---: |
| B − A | 0.020429 | 0.023278 |
| D − C | 0.030098 | 0.028837 |
| D − B | 0.017449 | 0.002921 |
| (D − C) − (B − A) | 0.009669 | 0.005559 |
| D − strongest | 0.010515 | 0.005837 |

原最小有用差异为 0.05；全部 16 项 net 对照区间下界未达到该门槛。八项 retention 区间下界均未超过 −0.02。四份 fit ×20 来源组是 80 个交叉配对单元，不是 80 次独立训练；20,000 次 bootstrap 仍是描述性区间，没有据此产生有限样本确认保证。`admissible_power_plan` 均为 false。

本轮没有重跑原统计分析、重设门槛、改写数据分母或把计量诊断收益转移到原 pilot。原科学结论继续 `Inconclusive / HOLD`。

## 8. 仍需闭合的真实条件

| 交付方向 | 已有真实证据 | 仍缺的条件 |
| --- | --- | --- |
| 材料 | 完整注册／分组／曝光／选样核验 | 另外四类 retention 旧能力的前瞻面板；更广多模态主张所需真实领域来源及其治理身份 |
| 评价 | 固定 rubric、实际独立 scorer 进程、OS 信息隔离 | 独立控制并认证的 evaluator principal，与实际评价回执接线 |
| 控制器 | 票据适配器上的双 regime、A/B/C/D 和全部注册对照；本轮 120 次修复验证 | 更广泛真实模型／图文生成范围；不以本适配器替代所有 Hepta 机制 |
| Pilot／成本 | 原真实 pilot、完整研究分母、新计量和失败保留 | 可准入的样本量／精度依据，真实能耗与收费，完整 setup／子进程范围和统一换算 |
| Native owner | 原生运行 job、持久化文件、实际 artifact hash 与尝试前驱 | 实际受信 issuer／evaluator／owner 部署；Cell journal、认证周期提交和下一任务消费 |

当前 read-only authority investigation 的结果仍是 `AUTHORITY_ENDPOINT_UNRESOLVED`。已有 native operator job 与 GitHub 身份不等于 learning owner 的 FinalUse grant。没有创建自签 issuer、替换信任根、借用 HCSN 的授权，或把 shadow admission 当最终使用授权。

因此 `confirmation_access_authorized=false`、`adoption_authorized=false`、`native_owner_authentication=SEPARATE_REQUIRED`、`full_physical_cost_complete=false` 继续保留。下一步应在这些具体接口与材料条件成立后冻结新的确认性研究，不能凭本轮软件验证追认历史或下一任务的最终使用。
