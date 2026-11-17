# Qwen 研究诊断器 v1

这是在观察到真实 parent03 零基线之后，按已接受的独立研究设计编写的只读诊断器。它没有启动模型、训练、reference 验证或新 C，也不会选择候选、建立 Circuit、授予原生采用或 useful-work 资格。

这份说明是已接受设计的新重述。旧 `RESEARCH_SFT_POSTRUN_ARCHIVE_DESIGN_01.md` 的已知 SHA 为 `a4b86a2d53a6a9ec985ca49a74ffecfea32630b3448269a98f262d1b1a65c0a7`；失联 RAM 中的原 8,882 字节没有在这里恢复。恢复边界原件见 `RECOVERY_BOUNDARY_01.json`。

## 冻结内容

| 项目 | SHA-256 |
| --- | --- |
| 诊断器源码 | c43ff3c5f9bc99c5825a96e0f4b4020d361489d2ffa3ae31bffe49f03ddb6f91 |
| 可执行规则 FREEZE_01 | 93dff768e527af37551a71b3cf89c47b2b8ad83dae461e11d7a8214cfc0e5ddc |
| 行为测试源码 | 996a5ff9eea21f8da8428ad1e4fa6ff5a791319769b37b4ea85863b18c9c9cfe |
| 10 项测试回执 TESTS_02.json | 2b5837110aa5e5b908f7c924a7cba6ca3b9705ad83ce8e08c72d6c8abcd49f0d |

固定槽位依次是 `final_answer`、`trajectory`、`controlled_correction`；`shadow_correction` 单列。槽位必须有完成的 fit、primary evaluation 和同一 manifest 的独立 cold worker 原件。失败槽位不会用其他臂替代；如果 primary 已有完整观测而 cold 失败，保留 primary 子记录，但槽位仍不可用。

`QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.template.json` 是明确不可运行的模板。实际 prepare 应绑定同目录的 `QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json` 与上述 SHA。研究操作 freeze 再独立绑定四个执行模块、helper04、源文件与实际输入，避免环状哈希，也不预填未来 adapter 身份。

## 实际核对的证据

诊断首先验证完整 source02 的 119 文件、实际 helper04 四模块、研究四模块、固定 parent03 RESULT/FREEZE、只读重建的 INPUTS 和 reference admission。source02 排除了历史 sealed-C 成员；没有读取新 C。对保留的 baseline 做完整清单哈希复核，不把其他 panel 的失败概括成“全部解析失败”。

每个 fit 必须对应同一父模型、全部六个 A、实际收集后冻结的四计划 bundle，且 collection 完成早于训练 STARTED。shadow 必须是本次真正生成、execute=False 的原始请求/输出；controlled 必须逐字对应原 parent03 的历史 A 执行，新增调用计数为零。correction cohort 按真实观测重建；学生事件不能变成训练目标。

候选必须有实际 adapter_config、safetensors 与 optimizer 字节，大小和 SHA 均匹配；诊断不会反序列化它们，也不读取公共 base 权重。TRAINING、64 条实际步骤、记录/turn 调度、监督 token、padding 和 reference 原件必须相互绑定。

评价成功逐条来自保留的 request/output/step/RESULT。模型 digest、输入、消息历史、generation、PID、token 预算、实际业务验证、原始 subject 调用与 negative controls 均按冻结解析器核对。摘要中的 success 不足以绕过原始证据。缺失或错误使该臂不可用，不修复输出，不补造 success。

cold 必须能对应实际 launch/job/EXIT/worker RESULT，并绑定 primary RESULT 文件 SHA、同一 manifest 和不同 worker PID。输入、generation、raw answer/token 与业务结果分别比较；冷恢复退化会原样报告。

## 指标解释

首次和末次尝试始终分开。真实 parent03 的 repository A 为 0/6；候选自己的 A 成功率仍可计算，但“以前成功任务的保留比例”分母为零，结果为 null。这不能证明没有遗忘。

三槽首次成功集合的 union/best 只是机会诊断。任一槽不可用时，完整 union/best 保持未知，只列可用槽小计。union <= best 时停止能力组合推断；union > best 也不能证明真实路由能够取得这个并集。本工具没有路由执行或连接训练，没有逐边/Cell 消融，也未匹配全系统成本。

source_growth_metrics 使用六个实际 A 的原 source/task/lineage 和 prepared-input SHA，明确传 readiness=None。64 updates_per_source 仅是规划参数；1/4/16/64 设置不代表执行过的增长试验，不制造用户、教师或独立样本。可用来源组数也不等于统计有效样本数。

旧 B 已暴露，A 保留集重复既有任务。这里没有独立 B 选择、新 C 使用、原生采用闭环或 PoUW 资格。same-base 的几个 adapter 也不是新的多教师证据。

## 成本口径

原始调用账本直接复用确切冻结的 `run_research_sft_v1.raw_ledger`，先显式 configure(helper04)。这是对原始文件的只读成本投影，不运行 worker。每条 reference 独立回执只计一次，REFERENCE_RECHECKS 汇总不重复相加；历史 controlled 重放不增加调用。

panel 成本只取实际 MEASUREMENT 或保留的 FAILED 测量。仅有 STARTED 时，结束成本未知。panel 包含当段推理、验证与已完成 verifier 子进程 CPU，明确不含 model load/close。training、worker、coordinator 与 reference 的嵌套成本各自保留，不相加。没有从 panel 外推完整系统成本；GPU active time、能耗等未测量量保持 null。

损坏 JSON、半行 JSONL、已写 request 但没有完整 output、未刷盘 optimizer 尾部，都保留原件身份、可读小计与未知总数。真正的零和缺失测量是不同状态。等 64 步或等 padding 并不等于监督 token 或实际训练成本相同。

## 使用与输出

Desktop 固定目录：

- source：`/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-diagnostic-v1-source`
- research run：同 workspace 下 `research-sft-01`
- diagnostic output：同 workspace 下 `research-diagnostic-01`

使用已恢复的 HOME venv Python，必须加 `-I -B`。完整 argv 由 root 的 owned launcher 冻结；参数是：

```text
qwen_research_diagnostic_v1.py
--freeze WORKSPACE/research-sft-01/FREEZE.json
--freeze-sha256 <真实 operation FREEZE 文件 SHA>
--diagnostic-freeze WORKSPACE/research-diagnostic-v1-source/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json
--diagnostic-freeze-sha256 93dff768e527af37551a71b3cf89c47b2b8ad83dae461e11d7a8214cfc0e5ddc
--output WORKSPACE/research-diagnostic-01
```

WORKSPACE 和尖括号是说明占位符，须替换为真实固定路径与实际已生成 SHA。源码与规则 JSON 必须在同一目录。输出目录 create-only；不会覆盖前一次结果。

正常输出为 `DIAGNOSTIC.json` 和 `INPUT_BINDINGS.json`。绑定失败保存 `FAILED.json`。所有读取过的选定成员在结束前重新哈希；这不构成原子文件系统快照，也不认证 writer 已停止。writer 的真实终态、子进程回收与最终归档仍由 root 的独立 owned launcher/archive 流程负责。

## 已完成的工程验证

10 项无模型测试全部通过，实际退出码 0，源码前后 SHA 相同。覆盖路径越界/符号链接/文件漂移、重封错误模型身份、缺失业务观测、缺失或修改 adapter 字节、零基线分母、失败槽不替换、union 停止条件、冷恢复身份、部分成本未知与 reference 去重、不可运行模板和规则源 SHA。

这些是明确标注的 synthetic 机械 fixture；其中业务 callback 只提供失败或未知，不用它证明真实任务成功。成本集成确实调用研究协调器的只读 raw_ledger。测试没有模型、reference 或 C 执行。研究模块自身的实际 tiny CPU tensor/LoRA 测试属于另一份工程回执，不计入本工具的 10 项，也不计为四个真实研究 fit。
