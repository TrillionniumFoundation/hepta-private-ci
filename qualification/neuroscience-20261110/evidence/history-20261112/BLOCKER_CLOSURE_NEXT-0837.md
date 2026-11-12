# Blocker 闭合清单与执行边界（2026-11-12）

**整体仍为 RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL；科学与普通采用门保持 HOLD。**
T/R/V/L、来源与时钟认证、原 owner 链、持续 cadence、独立 B/C、完整成本和冷恢复均保留在原 scope；下列局部闭合不移除这些目标。
前门缺项是 HOLD／未决。只有原 owner 完整评估后签发、可核验的 `NoUpdate` 才计为该结局；超时、缺件、未启动与 UNKNOWN 均不能改写为 `NoUpdate`。未取得决定时 `owner_decision=null`，不推定采用。

## 1. 精确代码与运行证据

| 证据 | 已核实的绑定与范围 |
| --- | --- |
| [native PR #6192](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6192) | head `1ac802f4b1196fe15c5d3ae730207ff585d41250`；tree `f004cd0cf481be6a47a3f1698d6a4820b7bca30d`。 |
| [hosted run 43173410889](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43173410889) | 完整 checkout 的 merge ref `62fc7fbefa56172ca35d33059c49303392880c90`，tree 与上述 head 相同；这是 CI checkout 身份，不据此声称 PR 已合并。 |
| [Rust job 131031841067](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43173410889/job/131031841067) | success；106 passed、0 failed、0 ignored、0 filtered out。 |
| [Python job 131031840903](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43173410889/job/131031840903) | success；119 tests，全部通过；它不是 V 新入口的 129 项套件。 |
| [V PR #6198](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6198) | 此表测试所绑定 head `52f936df6e7d3f55e65c133dd7d9c9d16ca699a2`，tree `a04bf46d1fd4aaeeeaa353a47c850a11c7088509`；后续文档／证据提交不能自动继承任意新增实现的测试资格。本地 129/129、0 跳过，含 10 新测试。 |
| [V hosted run 43174070320](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43174070320) | completed/success；checkout `a2efb7bc7b01c4d979001f008e2c1fd6e7c9c086` 与上述 head 同 tree。[Rust job 131033956660](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43174070320/job/131033956660)：106 passed、0 failed/ignored/filtered；[Python job 131033956955](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43174070320/job/131033956955)：129 tests、0 skip、OK。 |
| 本地原件 | `NATIVE_TIME_EVIDENCE.json`、`NATIVE_PERCEPTION_EVIDENCE.json` 位于本目录；压缩载荷须解码并校验 bytes/SHA256。hosted 原始 job/log 读回在 `/workspace/scratch/862531d11598/{native-hosted-ci-readback,perception-hosted-ci-readback}.json`。 |

V 的入口机械及表列相同源码 hosted checks 已闭合，wrapper actor 仍为 0。表外检查须按各自精确 checkout 与原日志判定；不能由两个专项 job 推定全部 CI 或科学门通过。后续 #6213、#6221 与上游真实 campaign 分别登记，不与这些计数相加。

局部构建曾因三 crate 子集 lock 需规范化而在执行测试前拒绝；原 dependency pins 未改，随后本地通过。#6192 的完整 checkout hosted 结果闭合了该发布源码的构建／运行验证缺口；本地 subset 不再充当 full-checkout 证明。详见 [NATIVE_TIME_VALIDATION.md](NATIVE_TIME_VALIDATION.md)。

## 2. 已关闭的子 blocker

| 子项 | 已关闭内容 | 仍不证明 |
| --- | --- | --- |
| Q24 实际时间数值 | `codex-rs/hepta-neuron/src/plasticity/real_time_credit.rs` 的 decay/reward/state/update 接口及测试实际运行；回报、状态、更新、eligibility 分列。11 个 native 输出边界向量经 Decimal90 重算，Q24 整数最大差 0，登记容差 1；覆盖大 dt/tau、tau=1us、终点奖励、单位同比缩放。 | 全域训练数值等价、真实等待来源或科学收益。采样结果不冒充全域穷尽证明。 |
| 冻结前缀与路由机制 | 同模块先验证 clock/boot 再按 available 时间过滤；绑定 action/model/source/checkpoint/group map；未来非时间 payload 不进入 view。正确／打乱路由保留相同向量，scalar 另列，复用 `temporal_credit.rs` 原投影／乘法／clip 顺序。 | 自报身份的真实性、原 owner 签名、参数实际更新或持久 cadence 消耗。 |
| V 原 API 机械接通 | `replay_perception_native.py` 对 [#6159 exact 397632651912513e24030476d98a5b101a0a0e0e](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6159) 的 92 个原文件逐项验 Git blob；真实执行原 freeze/thaw、独立子进程 cold-load、wrapper freeze/load、B/C validate_plan/check_inputs，无 mock 替代原 API。 | 输入来自上游构造 fixture；真实 actor=0、B/C START=0、独立来源=0。该机械 checkpoint 不能充当真实 fit 或普通 C 冷恢复。 |
| V 拒绝与恢复边界 | 源码／analysis pin 篡改、sealed role、context/plan drift、cold-load freshness、等长 roster 替换被拒；exclusive-create 的 START 防重复派发经构造子进程中断检验。 | 模型执行成功、目录掉电持久性、敌对并发文件系统认证或原 StageOwner 决定。 |
| 原真实 frozen fit／独立 cold-load | 上游 run-v2 的真实 frozen fit 已 exit 0；FIT/COLD-LOAD 的 START/COMPLETED 原件、CHECKPOINT_PIN/COLD_LOAD 与实际 11,489 B 文件 SHA256 一致，见第 8 节。 | calibration.complete=false、full_cost_observed=false；不等于 wrapper B/C、普通不同 C／Root 冷恢复、独立效益或 owner 采用决定。 |

## 3. 原 scope 内仍 OPEN 的闭合条件

所有行均需具体原件与精确版本；声明字段、自建 HMAC、内容 hash、Python reference 或另一分支存在同名实现不能替代认证。
下表原 owner 文件均在 `codex-rs/hepta-agentd/src/`；journal/CURRENT 审计基准为 [#6006@3c8dabe46598599e91b2b8b80081e09069ff9426](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6006)，并非宣称本研究 head 已包含该整条链。

| Blocker | 已做尝试与剩余原因 | 关闭必须取得的证据 |
| --- | --- | --- |
| 来源／暴露认证 | `source_contrast.py` 与 V wrapper 校验 source ID、字节及 split 一致性；历史独立性、随机化与 source owner 尚未认证。 | 原来源 owner 的 acquisition/receipt/exposure 链，绑定不可变原输入与来源簇；训练／校准／确认互斥、quarantine 生效；不能把 seeds、切片或重放计为新来源。 |
| 真实时钟 | Q24 与 `real_time.py` 已分离四个时间量；clock/boot/time 仍由调用者声明。 | 原 owner 记录动作、真实 outcome、information available、decision/update 时间；同域单调性与 boot 绑定，跨恢复锚点／误差界。异域时间不得先用于判定“未来”再过滤。 |
| 持久 cadence／CAS | `update_time_due` 为无状态判定；`study.py::cadence_gate` 为参考 gate。审计定位 #6006 原 `hepta-agentd/src/learning_owner_journal.rs`、`neuron_generation_current_store.rs`，尚未证明本研究已接入。 | 复用 `LearningOwnerJournalV1::{create,recover,commit_once,read}` 及原 CURRENT `compare_and_set` 权限／root version；真实跨进程重开、并发、崩溃前后证明 lineage/model/generation/time opportunity 只消费一次，旧版本不可回滚重用，pending 不重派发。 |
| 原 owner bridge | [#6213](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6213) 已发布 evaluated-retention Selection read 增量及真实 retained CURRENT 的 fresh/readback 正例代码；训练未更新与经过独立评估的保留分支隔离。源契约／格式检查与原生执行资格分开，见下节。 | 同一精确 tree 经原 StageOwner → evidence verifier → Selection read/decision → FinalUse → Root CURRENT；保留原 authority、独立 evaluator 和拒绝路径。read-only Selection 不开放 Selector／不同 C；当前增量不关闭整体 bridge 或 G4。 |
| T 时间教学效益 | 数值／冻结接口已运行，实际 owner-attested 对齐训练未运行；旧 HPCA 逐 seed 差 0、B2 AUC<0.5 仍保留。 | 同逐次完整向量／释放时间的正确与打乱路由、对齐与打乱 eligibility；scalar 单列；真实稀疏／密集反馈、强普通训练基线、同容量／调参／更新成本，独立来源效益及旧能力门通过。 |
| R 独立情景／技能回放 | [R_V_EXECUTION.md](R_V_EXECUTION.md) 已审计 MEM/ACT 入口；MEM 真实尝试 UNKNOWN、ACT 为受控 probe，尚无同一真实任务上的两路适配器。 | 原 owner 上 E/S 2×2 与另一个等总预算 B 面板；E-only、S-only、E+S、统一池及普通基线的真实效果／资源；MEM 禁用后 ACT 路径独立、版本／撤销／过期约束和协调交互可复核。 |
| V 感知／检查效益 | wrapper 原 API 机械集成已通，wrapper actor=0；上游 run-v2 的真实 frozen fit 已 exit 0，后续完整 campaign 尚无终局。原宏仅 STOP／真实 READ，同信息循环和独立 checker 仍缺真实等预算接口。 | 原训练产物绑定及真实付费 READ/ROI/checker 原始输出、前后选择与独立最终效果；同字节／释放时刻面板与付费面板分开，保留强普通策略、顺序平衡、完整成本与净收益门；上游开发训练不替代 wrapper B/C 或独立来源。 |
| L 长期可塑性／保留 | `learning_progress` 与 retention 测试只验证统计语义；没有长期真实模型运行矩阵。 | 阶段×任务 `P[k,j]`，漂移／旧情境重现／延迟反馈；新任务样本、时间、成本与学习曲线，未达标保留删失；旧保留非劣效及新学习效率同时过门，累计资源／容量／回放／特征更新对照匹配。 |
| 独立 B／不同 C | V 只登记 development_B/C，`fresh_source_confirmation=false`；描述性 B 选择不是原 Selector，C 双臂也不是已选候选的普通使用。 | 训练之后、历史未暴露的原来源 B，由独立 evaluator 评估；原 owner 真实签发 Selection 或 NoUpdate；不同 C／worker 按该真实决定使用，绑定候选、证据、回执与版本。 |
| Power／完整分母 | [FOUR_TRACK_PROTOCOL.md](FOUR_TRACK_PROTOCOL.md) 已冻结原则，实际方差、缺失率、效应门槛与样本量登记未完成；不输出确认 p。 | 独立开发来源估计簇方差／相关／缺失率，冻结实用阈值、90% power、四线 Holm alpha=0.05／同时区间及停止规则；失败／UNKNOWN 留在 planned denominator，不能用 toy n 或显著性最小可达值代替 power。 |
| 全生命周期成本 | native 测试耗时仅验证成本；V 计 actor 延迟与外层 wall/parent CPU，`full_cost_observed=false`。 | 数据获取、训练／调参、推理／回放／checker、进程树、provider/energy、存储、失败与摊销的原始成本；嵌套计时不双加，未知成本须有冻结保守界，否则净收益 HOLD。 |
| 普通真实冷恢复 | 原 run-v2 frozen 模型 fit 与独立子进程 cold-load 已实际完成，checkpoint pin／context／实际文件 hash 均读回核验。#6213 的 readback 正例代码仅涉及相同物理 owner 上的 Readback-origin。 | 这些子项不是已选择模型在普通不同 C／worker／boot 的使用，也不是 Root／daemon 重启。完整 G4 仍须原 CURRENT/root version、journal/witness、实际 C 效果与 rollback 原件；无重训、重签或重复效果，旧版本／pending／损坏按原契约处理。 |

### 原 owner 分支验证登记

[#6213](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6213) head=`60606b89dd30f78de94b583524131446d45ca49a`，tree=`177df716b8578216efd502aed91e5672ac979ee0`，唯一 parent=`8b4d162cff8fa7c4d53c520370217ceda99ee0aa`；17 个文件、513 additions／19 deletions。代码正例复用真实 PublicationFixture 的原 Trainer／Evaluator 与 retained publication，不把已发布候选 C 重标为 baseline。
本地 source-closure 检查 355/355 与格式化 exit 0 是已执行观察；完整原始 stdout/stderr 当前尚未归档且执行环境无法读取，不能以统计或早期 eabfb／347 项日志替代。原 [hosted run 43179184471](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43179184471) 在最近登记的 08:32:02 UTC 仍 native/caller-proof queued、无 steps/logs；当前不宣称 Rust 正例或全套原生检查通过。
Selection read 仅接受原 4-cut evaluated proof，保持 TrainingNoUpdate 隔离与每次真实 CURRENT 回读；fresh／readback origin 绑定不可换用。该增量不增加公开签名／grant 构造入口，不把 readback proof 换成 NewWork，也不闭合 Selector、普通不同 C 或 Root 重启。实际 CI、拒绝路径及产物身份须继续登记；科学资格 HOLD，`owner_decision=null`。

## 4. 当前可执行边界

`just test --locked --offline -p codex-hepta-neuron --lib --success-output final`（`codex-rs`）与 `python3 -m unittest discover -v -s qualification/neuroscience-20261110 -p 'test_*.py'` 可复核机制；测试成功不启动研究 actor、不构成训练或 owner 结局。
V 的真实调用前仍须取得并绑定原 `FROZEN.json/COLLECTION_PLAN.json/CHECKPOINT.json/CHECKPOINT_PIN.json/COLD_LOAD.json`、完整 source pins＋driver/analysis、真实 weights/control/material 与 Python 环境。旧 run-v1 的路径及 83 项 pins 已从原 freeze 校验；新 run-v2 产物须按它自己的清单逐项核验，不能套用旧 82/83 数目或把存在路径当训练资格。
实际入口与 freeze→B→C→reconcile 命令见 [R_V_EXECUTION.md](R_V_EXECUTION.md)。run-v2 原请求／key 已对账为 reused=true；后续读取原 session 和 run-v2 产物，不另派 28-episode probe 或新同源 campaign。既有 START／UNKNOWN 先 reconcile，不更换 key／目录重试；development 连通也不关闭 R/T/L、独立确认或 power 门。

## 5. 历史 ai395 读回与旧未知 probe

异步 `read_multiple_files` 成功返回既有 config/design 与 exposure ledger；同步 `host_health`、fresh registry page 在 MCP 层超时。该组合证明已知路径可读，不能推出主机缺能力，也不能推出模型执行可用。这些读回未启动或重启研究进程；随后独立 metadata locator 的授权与结果另列于下节。
实际路径：`/home/qq/ndu-real-runtime-20261107-bc2efaf10cd0/{pilot-config-v1.json,PILOT_DESIGN.v2.json}`；material root 为 `/home/qq/ndu-real-materials-20261107-audit-bffe40c2`；旧 repository 为 runtime 下 `code-v3`。两 config 未明示 weights/model/profile 路径。
材料根下 `pilot-catalog.json` 实在，1,410,133 bytes，SHA256 `8433d0c026b0818f8e60ee2f0ae7e7b57c57ae35cbb72cf212b89895b97d0904`；只读 metadata/hash，未整读可能含案例标签的目录。
早期 runtime/material 两次四名称搜索均在 10,000 entry 上限停止，`coverage_complete=false`；随后排除 code/deps/OCR 的 search_start 超时且无 search_id。当时没有取得 FROZEN/CHECKPOINT/COLD_LOAD，不能判定不存在。下节 locator 及第 7 节后续原件已补齐两种 schema、真实 freeze 路径与源码／资源绑定；旧搜索限制仅描述其发生时的观察。
既有 2026-11-07 design 记录 confirmation release=DENIED；既有 exposure ledger 记录 scientific_admission=HOLD、confirmation actor/model reads=0、evaluations=0、两个 quarantine source group。它们是历史记录，不是本轮新完成的 confirmation 审核，也不是当前训练／采用结果。
ledger 文件 `public-source-exposure-20261107-v3.json` 的 SHA256 `6722edfc88e1089bcaf0fba9727c233416830fdc6682b461422d26bdfd4cb6af` 与 config 完全匹配；内容一致性不认证 owner。

| 会话原始 SDK 字节（目录 `/workspace/scratch/862531d11598/`） | bytes | SHA256 |
| --- | ---: | --- |
| `h-asset-readback.json` | 13,224 | `e9bd6c787dab15a4811606d9f3851199f7e861ff642b4e754b2c6f2319cda3d3` |
| `h-exposure-readback.json` | 4,414 | `7549dffeb04183d4ee8374efd98097f9c8886abd906e061e962322e1d346faff` |
| `h-catalog-info-readback.json` | 579 | `6caef8150bb30c22139283508d6d133572646bc18d84356c254fd03ca85a6110` |

完整调用状态在同目录 `native-time-read-diagnostic.json` 与 `native-time-read-diagnostic-followup.json`。原两次同 key probe `neuro4-next-assets-862531d11598-v1` 仍 **UNKNOWN／无 job_id**；不将它计为失败、成功或 NoUpdate，不重派发。

## 6. 历史独立文件定位器（随后已补原件）

新 key `neuro4-checkpoint-locator-862531d-v1` 通过 `h_pty_start` 执行 `/usr/bin/python3 -c`，只在 `/home/qq` 下 ctrl/macro/ndu/perc 目录读取名称与 stat，跳过代码／依赖／OCR／隐藏目录／symlink。它不是旧 probe 重启、训练、actor 或同源 campaign。
session `dpty-85dd0fb4f587da852991bb5073183e0143886b7bb3baeacaf903a8e91f3f9220` 实际 exited/0、output_complete=true；0.160702 s，3,000 目录／60,983 entries／3 matches／0 errors；28,023 待遍历目录，`coverage_complete=false`、directory_limit。未读取文件内容或标签。

| 实际命中的文件 | stat size | 尚未证明 |
| --- | ---: | --- |
| `/home/qq/ctrl-answer-repair-20261110-e323-v1/FROZEN.json` | 737 | 定位时未读 schema；后续确认为 dispatch 对象，见第 7 节 |
| `/home/qq/ctrl-prospective-20261112-736c/run-v1/FROZEN.json` | 146,518 | 定位时未读 schema；后续确认为 native freeze，见第 7 节 |
| `/home/qq/ctrl-real-study-20261112-1333/run-v1/frozen/FROZEN.json` | 189,780 | 定位时未读 schema；后续确认为 native freeze，见第 7 节 |

CHECKPOINT/COLD_LOAD 未命中不代表不存在。原请求与 tool 读回保存在会话目录 `h-checkpoint-locator.json`；其中 `bytes_hex` 可无损还原 2,705 bytes 终端原字节，SHA256 `218ab0880f95fe9560aab35bff758cef2cfc8040f818eb8964d7170dc0e50bf0`。新 locator 完成后停止查询；旧 UNKNOWN probe 状态不变。

## 7. 后续冻结格式与部署闭包核验

原 metadata 只读输出 [OUTPUT.jsonl](evidence/frozen-metadata-20261112/OUTPUT.jsonl) 为 7,782 bytes，SHA256 `9c458177b0ead30ec735854a82cbac8c0b7d995e88a8608d27295cdfe6f33cf1`；保留的 PTY 读回以重新序列化的同目录 `READBACK.json` 留存，终端原字节由 `bytes_hex` 与 `OUTPUT.jsonl` 校验。它覆盖下表的实际字段；hash 一致性不认证 owner 或历史来源独立性。

| 原文件 | 已知 schema／pin／内容边界 |
| --- | --- |
| 737 B answer-repair FROZEN | `ndu.ctrl.answer-repair-dispatch.v1`；SHA256 `2cdad8ce005d9196704ad71e7e441efddc107593c151840e6980d7434125d0c8`；pair_count=0、source_pins=0，是 dispatch 对象，不是真实模型 checkpoint。 |
| 146,518 B prospective FROZEN | `ctrl.fresh-experiment-freeze.v1`；SHA256 `75e33bfb3b2f6fdf7d749d3f3cd5e1b116a05322e2905106b56366e791db0df0`；82 项 source pins。 |
| 189,780 B real-study run-v1 FROZEN | `ctrl.fresh-experiment-freeze.v1`；SHA256 `5ec574f35366cbffb12555832dc611a722e92d72ea3c709feaa838f6d619cf27`；83 项 source pins，train 72 rows／24 sources、calibration 54 rows／18 sources、48 evaluation contexts。 |

独立只读 predeployment probe key=`neuro-rv-predeploy-20261112-5ec574-v1`，session=`dpty-2562874b70f3217fa3334c02734259a51455ebffbcb4b0a4e607b82e117130fc`，2026-11-12 07:56:08 UTC 启动，exit 0；fit/collect/prepare/actor 均为 0。83 项原 source pins、driver/analysis 及原资源 hash 逐项匹配，共 89 个 matched 检查，原始 19,542 bytes 输出 SHA256 `2e7929150be41f96e2c5813d0868008b13a289547fe8a875a196114a0757bbf5`。
旧 repository=`/home/qq/ctrl-real-policy-20261112-1333-v2`；源码闭包为 runtime 72＋materials 9＋core 1，再加 study/analysis/prepare，共 85 文件；额外第 83 项原 pin 是 receipt。真实 repo 有 13,849 regular files＋1 symlink file，不把全部环境文件误当部署源码。完整路径／hash 见 [rv-deployment-source-closure.json](evidence/rv-predeploy-20261112/rv-deployment-source-closure.json)。
原 W=60 s、action budget=40 s、READ bound=30 s、finalizer reserve=5 s、alpha=0.1、ridge=0.001、latency weight=0.01。weights/control/exposure 的原 pin 已匹配；原 Python symlink 可执行，但 FROZEN 没有 Python binary expected pin，其观测 SHA 只作环境记录。prepare 单独与发布源码对齐，不冒充 FROZEN 自带字段。

## 8. 原失败运行、新版本归一化回归与既有 run-v2

旧 run-v1 仍为 collection 126/126 pairs、UNKNOWN 0、EXPORT 完整、FIT_FAILED。只读诊断确认 72×47 训练公开状态中第 46 列 `log1p(40)` 为常量，正权重平均低于 observed minimum 7 ULP，严格加载器拒绝 `Invalid normalization or observed envelope`。它与更早 prior-attempt 的 125/126 是不同运行；两个失败阶段、计划分母、原成本及 pins 全部保留。
生产修复已由上游 [3c94ea8](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd) 发布并进入 ded3：producer 将均值约束到同一原 observed envelope，strict parser 未放宽。新 converter/fitter pin 必须来自新 freeze／新 collect；本轮没有旧 EXPORT 跨版本 admission，禁止换目录、改 pin 或直接喂制造 rows 代替原流程。
[#6221](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6221) head=`2d1f610f0f2abf6dc5d7d903243621376697b407`，tree=`93ada9e27db2eb991e21e97f4554d3963de1ccc6`；只增加原公开输入回归／fixture／证据，没有重复修改 producer。policy 19＋parser 7＝26/26 是本地已执行观察；[VALIDATION.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2d1f610f0f2abf6dc5d7d903243621376697b407/qualification/ctrl-normalization-input-20261112/VALIDATION.json) 明示 transcription 与 `original_local_logs_archived=false`，完整本地原日志当前 unavailable。同进程 serializer/strict-loader 机械用例不冒充真实 driver 的独立进程 cold-load。

### 原派发身份已闭合，真实结果仍需原件

原请求为 [campaign-bootstrap-pty-request-v2.json](evidence/rv-predeploy-20261112/campaign-bootstrap-pty-request-v2.json)，Git blob=`491c1db322a562a4b03cf300f6ae26ce786b0161`，5,845 bytes，SHA256 `46edd3850db6d9ceb78463f92df5aa30eeddecefa0b221745cba083f16ad0f9d`。host=`ai395`，key=`ctrl-1333-real-campaign-pty-v2`，source=`3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd`，code=`/home/qq/ctrl-real-policy-20261112-1333-v3`，output=`/home/qq/ctrl-real-study-20261112-1333/run-v2`。
以完全原 typed request 对账返回 `reused=true`，原 session=`dpty-40ff97e76f70d0a5e1c37280afeab264b349cee40962d4e6b77d543fdb391c65`、running、2,041 bytes。此前 08:00:01 UTC 的独立只读 snapshot 观察 run-v2 路径不存在，仅是当时状态；不能推出尚未派发或允许重复。原 session 读取 timeout 亦不等于失败。
后续 SDK 原载荷 5,074 bytes，SHA256 `d9176525b905e65da048881201a7498ba206e17c42d4a0f60d75800999475a37`；`bootstrap-v2/campaign.log` 原 1,745 bytes，SHA256 `3bd67452e5fcfe1f5610b3f00acba05d3591e12fa8a97fe8258269931239ee23`。它记录 prepare／frozen_freeze／frozen_collect（exit 0，522.9858 s）／frozen_export（exit 0，13.8849 s）／frozen_fit（exit 0，0.31469 s）／content_adapt（exit 0，13.3356 s）／adapted_freeze（exit 0）；最后观察 adapted_collect STARTED。
随后读取的 [campaign-progress-2.log](evidence/campaign-v2-20261112/campaign-progress-2.log) 为 2,732 bytes，SHA256 `5a0d74501b13f0850c76740230041359efb541d6b3d7b6b3d6fc8467f45a674b`：adapted_collect exit 0（535.3885 s）、adapted_export exit 0（14.5875 s）、adapted_fit exit 0（0.31480 s）、factorial_freeze exit 0；末条为 factorial_evaluate STARTED。它更新了上一快照的阶段进度，尚不是完整 factorial 终态。
原 source 的 [ctrl_macro_study.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ctrl_macro_study.py) 在 fit 返回前用 `subprocess.run(...cold-load..., check=True)` 强制独立进程校验。后续原 SDK 6,542 bytes、SHA256 `06d39b968afb62b11c4dadeea8856a741ab09d2228c6829963a0e805f82f86d0`，已读取 FIT_START／FIT_COMPLETED、COLD-LOAD_START／COLD-LOAD_COMPLETED、FIT_STAGE、CHECKPOINT_PIN 与 COLD_LOAD；另以 file_info 核对真实文件。原件见 [frozen-fit](evidence/campaign-v2-20261112/frozen-fit/)；[CHECKPOINT_INFO_ORIGINAL_SDK.json](evidence/campaign-v2-20261112/CHECKPOINT_INFO_ORIGINAL_SDK.json) 另保留实际文件信息。

| 新真实训练产物 | 已核验值及限制 |
| --- | --- |
| frozen freeze | SHA256 `7679b083343d6de9d7b3e1f1acc4f3252b044de36deafadb289ff532c7de7497`；source 3c94，driver SHA256 `12f118fc1be4f904119e224466124b7599bea6bc8a3496b2bdf8c0da289be5b0`。 |
| checkpoint | 实际文件 11,489 B；SHA256 `c4ee4a0219117edeec6381b0bb01b896f9a182862298eba22d3c69a828c17096`，与 CHECKPOINT_PIN 和 COLD_LOAD 一致。 |
| cold-load context | `2c5f3ca8bd208680ea54ffba80f0ab5d1d7c19c906f54779015c4588fe2b9058`；原独立子进程 START/COMPLETED 已回读。 |
| 分母／校准 | export126/126、UNKNOWN0；FIT_STAGE fit72／cal54。两个 conditional 组各9来源，unconditional18；`calibration.complete=false`，`full_cost_observed=false`。 |

这些原件关闭真实原 driver 的 frozen 模型 fit＋独立子进程 cold-load 子项。校准不完整仍保留，不能改 alpha、放宽原门或强迫 READ；完整 campaign、后续 evaluation、普通不同 C／Root 恢复、wrapper actor 与科学门尚未完成。

后续 [adapted-fit 原件](evidence/campaign-v2-20261112/adapted-fit/) 亦已读取：adapted freeze=`247b1e67b276d27476ad58b0c3c7dedb27b2a74877d6728be52d04875c8ab413`，CHECKPOINT_PIN 与 COLD_LOAD 均为 `11e9e251d06ab46f12b0b16a8622a7a2c8d059943bdce763e1aa901df9471858`，context=`3d17b06cfd5df77ed383e7045048a4cd068102d662aadce1e7bb969be61d973b`；独立 FIT／COLD-LOAD 的 START／COMPLETED 绑定一致。adapted fit72／cal54，`calibration.complete=false`、`full_cost_observed=false`，其 export 仍为126/126、UNKNOWN0。当前已核验 pin／回执原件，尚未在本读回中取得 adapted checkpoint 完整字节。factorial pin=`f75c44d6092aa1a91af1db859823a7d1e20d9219016d00ce69b843ac5d462325`，原 freeze 输出登记 576 次执行；EVALUATE_START 已存在，完整终态与全分母结果仍待原件。

上游 bootstrap 原 `native-report.json` 为 997 bytes，SHA256 `fab2591d58b31426b57167c190fd19258b5b57a7615d78f7fd89c1bee6d70474`，`test_content_identity_native`＋`test_macro_native` 共 5/5、0 skip；它不是 #6213 的 Rust owner 正例或 #6198 的 B/C wrapper 调用。wrapper actor 仍为 0，不合并来源数、模型运行数或效益。
同一原 source 的 [ctrl_macro_factorial.py::reconcile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd/scripts/ctrl_macro_factorial.py) 将 `REPORT.json.decision` 硬编码为 `"NoUpdate"`，没有原 owner 签发。保留原报告的研究标签，但统一台账仍为 `owner_decision=null`；它不能变成正式 NoUpdate 或关闭 G4。已冻结源码／已受理请求保持不变，未来源代码语义修正另立版本。
原 bootstrap 收尾误读 `run-v1/COMPLETED.json`，真实 campaign output 是 run-v2。保持原已接收请求不变，先 reconcile run-v2 原阶段／产物；尾部报错不能触发重派。未来启动器可令执行参数与 completion 路径共用一个 `campaign_output`，本证据整理未修改旧请求或启动新任务。

## 9. 证据保存边界与下一读取顺序

[NEXT_STEP_EVIDENCE.json](NEXT_STEP_EVIDENCE.json) 区分精确 GitHub commit/tree/blob、已有四个 hosted 原 job/log、h SDK 原载荷、原 PTY 字节和执行摘要。#6213 的 355/fmt 与 #6221 的 26/fmt 原本地日志未归档；保留 reported/observed 状态，不合成“原日志”。当前 exec-server 不可用；未用额外测试替代缺失原日志，也未为对账另建 campaign。
[rv-predeploy 的 7 件证据](evidence/rv-predeploy-20261112/MANIFEST.json) 已保存在 immutable tree `3f4f555f2f6477f71f432c125b1f63ca149d52c1`；`.jsonl` 是含 CRLF 的原字节，两个 `.json` 是从原输出解析后的重建，不冒充旧本地 pretty-file 字节。该旧 manifest 的 v2 session=null 是身份定位当时的记录，由第 8 节与新统一索引补上 reused 的原 session，不重写历史原件。
下一步按原 session／原目录读取剩余阶段与完整终态／分母，并将已取得的真实 checkpoint/cold-load 与全部新 source pins、exposure 隔离和 wrapper native compatibility 绑定；另按精确 #6213/#6221 hosted checkout 收集原 logs。只有这些门通过后才登记 wrapper B/C；一个成功 stage 不自动关闭其他门。
全部研究结局仍为 HOLD／未完成；`adoption=NOT_REQUESTED`、`owner_decision=null`。只有原 owner 完整评估并真实签发的决定可改变该字段；缺件、UNKNOWN、失败或部分成功都不推定 NoUpdate 或采用。
