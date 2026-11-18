# Historical maintenance task capsule

本包冻结 **5 个已实际重放的历史维护任务**，来自 **4 个修复提交、3 个相关仓库、3 个必须整体隔离的来源依赖组**。这些任务具有真实的修复前后源码、真实执行入口和可运行的行为 oracle。它们属于同一 Hepta 生态；**不能当成 5 个统计独立样本，也没有独立外部分布证据**。

本包只证明这些历史 bug 的行为可重放，以及对应历史修复通过指定 oracle。它没有训练 MEM/PRED，没有测量训练或推理成本差异，没有让当前 Cell 产生修复，也没有对当前联合候选作 qualification。历史 after 是历史修复的参照版本，绝不能替代新候选的实际执行与独立评价。

## 执行

需要 Linux x86_64、Python 3 和 NumPy。本机初次重放用 Python 3.12.14。runtime 探针只用 Python 标准库；Cell 原始 fixture 用 NumPy；loader 调用本包中两份固定 SHA256 的真实 ELF64 映像。全包入口不需要网络、Git checkout 或完整 Hepta 编译器。

```sh
python3 -I -B /workspace/scratch/8ceb8d0b9456/learning-analysis/history-replay/run_all.py --output /tmp/hepta-history-replay-new
```

输出目录必须尚不存在。入口先验证每个冻结文件的 SHA256、28 个原始文件的 Git blob，以及 original-terminal 探针与原始 Rust raw string 的逐字一致性，再运行 3 个子入口并核查 5 个任务的 RED/GREEN、正常控制和实际返回值。最终结果是输出目录的 VERIFICATION.json。它保留各子进程的 stdout/stderr；Cell 额外保留原始 SQL 快照和损坏后恢复的 SQLite 文件。它不会修改当前联合候选源码。

## 已执行结果

| 任务 | 精确修复前 → 修复后 commit | 实际观察与 oracle |
|---|---|---|
| 原 child 终态 | hepta-runtime 5f558594cc2a69154eb8b34c70559aa80307d0eb → 57453f74c2967246fc961c02fbf0e6e4104103b2 | 同一真实 child 写一次 effect、自然退出 7；在实际 waitpid 收走原终态后，旧 runner 错报 succeeded/0；修复版保持 effect_unknown/125、child_exit_code=null、禁止自动重试。正常 exit7 控制两边均正确，业务 effect 均一次，无 signal。 |
| nonce/witness 终态绑定 | hepta-runtime cd295bd218a685dbc17f5cc86412f54b72777ea6 → 7da3a7ebaded8214bc65e69046b74e6251e21767 | 原 STATUS_FIXTURE 的 27 项：before 4/27，after 27/27。wrong_nonce、wrong_digest、wrong_job、missing_witness、原始 bytes 与重新序列化差异等在旧版实际被报为成功，修复版保持 finalizing。 |
| Qualification 身份 | hepta-private-ci a5bdfb5b7fbe4558fff7d8ad1ea85d3b33e21946 → a194098c99e785d05a90e5e9f5a9de53df23ba96 | 真实 host 回调在已核对身份后改变 evaluation_digest。旧 owner 继续 Adopt 并写 SQL；修复版拒绝，SQL 完全不变。原始正常采用与冷重开控制仍通过。 |
| population 恢复策略身份 | 同上，**同一来源组** | 真实原 owner 数据库复制后 DELETE/DROP 四个 policy 表。旧版静默重开；修复版拒绝，原 SQL/schema 不变。原始测试还覆盖首条 checkpoint 标记丢失但后续标记保留。 |
| native image 身份 | Hepta 0d1d1d414bffae16a5e541e05cdf64174cab7643 → 8ba46fc7a112fc220cdcbbd48dc5d24fda76a738 | 真实装载返回 17 的 HIA 映像，close 后装载返回 23 的另一映像。旧版复用 fd3，第二次实际仍返回 17；修复版保留不同映像的 fd3/fd4，第二次返回 23。两版已 close wrapper 均拒绝调用。 |

Cell 两项使用原始 6 个回归测试：before 5 failures / 0 errors，after 6 个全部通过。RED 来自行为断言，未把缺少 API、无法 import 或编译失败算作修复前失败。

## 文件与原始来源

- CORPUS.json：实验身份、每个任务的 before/after、期望语义结果、来源组、拟议 split、样本数与声明边界。
- PROVENANCE.json：28 个原始文件的 repo/commit/path/Git blob/URL，以及从 GitHub 实读的直接父提交关系。Cell 的 13 个生产模块中，10 个在 before/after 逐个重新读取并确认 Git blob 相同；另 3 个分别保存 before/after。3 个原始 test/fixture 文件单独作为 oracle。
- SHA256SUMS.json：本包全部有效载荷与初始原始记录的文件 SHA256/长度。CORPUS 的 frozen_data_sha256 还绑定原始源码与 native probe 数据及任务描述。
- terminal-*.rs、witness-*.rs、loader-*.py：完整原始生产文件；没有为探针修改其中代码。
- normal-reap-tests.rs、witness-tests.rs 与 normal_reap_probe.py：原始测试与精确提取的 raw string。
- cells-after 与 cells-before-overrides：最小 Cell 依赖闭包；运行时复制到一次性目录，再按精确 before 源替换 3 个文件。
- loader-images：两个 HIA probe 源、两份真实 ELF64 映像和原始 build receipt；loader-context 只保留实际读取的 continuation 源文件。
- results：第一次 runtime/loader 重放原件，以及第一版 Cell 诊断记录。
- results-v2：修正观察顺序后的 Cell SQL 原件与重放结果。
- run_all.py：统一重放和严格检查入口。replay.py、loader_replay.py、cell_replay.py 是子入口。

原始 witness fixture 的字段 reviewed_jobs_rs_sha256 实际计算的是提取后 STATUS Python 脚本的 SHA256，并不是整个 jobs.rs。统一入口按其真实含义验证；整个原始 jobs.rs 的身份另由 PROVENANCE/SHA256SUMS 绑定。

初版额外 Cell 诊断先记录 SQL，后调用 CellOwner.checkpoint；checkpoint 本身会持久化一行，导致观察者制造了 SQL 差异。原始回归测试在修复版已经通过。cell_replay-v1.py 和原结果完整保留；修正版本先建立 checkpoint 再截取基线 SQL，results-v2 显示修复版拒绝时 SQL 完全不变。这是诊断观察顺序修正，没有改被测历史源码。

## A/B/C 分组建议与隔离

| 阶段 | 整体来源组 | 数量 | 时间与约束 |
|---|---|---:|---|
| A | runtime_terminal：原 child 终态 + nonce/witness | 2 任务、2 历史修复事件 | 2026-10-23/26；同 jobs.rs 依赖闭包，后者基线已包含前者修复，必须在同一 split。 |
| B | cell_policy_identity：Qualification + population 恢复 | 2 任务、1 修复事件 | 2026-11-12；同修复提交、同 owner 依赖与 fixture，不能随机拆开当训练/测试。 |
| C | native_loader | 1 任务、1 修复事件 | 2026-11-16 UTC；另一个源码依赖组，只有一个任务。 |

这是可以冻结的**回顾性开发重放划分**。我们已经读过全部 gold patch 和 oracle，当前上下文不能宣称 B/C 对本助手未知，也没有执行 A 训练后的 B/C 评价。未来真正的学习实验应另外冻结训练器、观察编码、动作集合、超参数与全部预算；只让 A 的实际执行经验进入梯度；B 只作预先声明的评价，不作反复超参搜索；C 与冷重启后的新任务在选择完成后才开放。最终仍需新的、未参与实现的后续 bug 来源组，才能讨论泛化与跨轮保留。

子测试、nonce 改值、故障调度、不同 seed、分支、同一修复的重放次数都不增加来源样本数。当前最多按 3 个依赖组报告，不能据此做长期或外部分布推断。

## 接入 Cell 的可实施边界

现有 Cell 调用/owner/授权执行/经验持久化/冷恢复接口可以承载维护观察与动作。但当前四个语法 repair action 和 13 维特征不足以表达这些代码修复；不能将输入换成真实 bug 后仍声称原模型已具备任意修复能力。

下一版可冻结一个共同工具与候选生成器，让所有对照组获得相同源码、测试工具、补丁提案、上下文和预算；MEM/PRED 学习选择诊断、排序候选修复或估计执行效果。动作仍必须进入真实授权入口，patch 和 oracle 输出都绑定其原始 source/split/receipt。不要把 after diff、commit ID 或测试答案作为预测特征。

成熟确定性对照应保留完整 invariant 检查、常用诊断顺序、回归测试和相同工具/模型访问。若确定性对照仍全对，应比较达到同等正确率的完整成本或接受 NoUpdate；不要删掉它的规则、缩减其机会，或把黄金补丁仅提供给学习组。上述工作尚未实现。

## cursor 候选，尚未计入已验证任务

已实际读取 hepta-runtime a5015236c66854a3e2cb816a8f2faa14a677e2d2（parent c81a938150d2e533843a42af77739cb888812338）的 jobs_inventory_source.rs 与对应 source/cache tests：continuation 要复核原始私有/其他 host bytes，预先 mmap 的写入也须失效 cursor，恢复同样内容不能复活已失效 cursor。该修复引入新的私有 Rust API；本包没有完成等价公共入口的 before/after 行为重放，故没有计作第 6 个已验证任务。下一步需从两版共有公开 pagination/observation 入口建立 oracle，不能把 before 找不到新私有 API 的编译错误充作 RED。

所有源码 URL 和完整身份见 PROVENANCE.json；这里只陈述本次实际读取和执行的证据。
