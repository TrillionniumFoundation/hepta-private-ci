# P3：本次原始证据审计摘要

完整审计脚本、负例测试、原档案、六个冻结研究源、全量报告与命令日志在同次交付的 `hepta-cell-rsi-20261106.zip` 内。此文件和 `P3-AUDIT-SUMMARY.json` 是原实验之后新增的审阅附录，旧实验报告保持原样。

## 核回范围

原 [CPU job 127369397151](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42062983444/job/127369397151) 成功，其原 24 项 Python 测试通过；同 workflow 的 native sibling 在 fmt 失败，不能称整个 run 通过。本次没有重跑原研究。

原执行 commit `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b`，tree `d922da89a2523bf5d7e8c64ef5c519c7c8aec608`。原 ZIP 为 1,189,696 字节，SHA256 `5249c60f9779b621aa40951dbdb21ccddcc1f6a4ef49eb0b6db90a3e36812bd7`。原六个研究源与当前 #4935 基底逐字节一致，但这不赋予整个当前产品候选运行资格。

本次审计验证原 ZIP 的五个成员、CRC、大小和 SHA256，逐行核对两个场景、五个种子、六臂，以及验证 / 测试 / monitor / 序列化往返的记录和算术。全部 11,520 条 test 请求进入分母，10/10 trials 的原决定都是 HOLD。原输入在审计前后的哈希完全一致。审计只读取既有参数、输出、账本及冻结源，不 import 或执行 learner。

审计工具自身 **16/16 行为与负例测试通过**，与原实验 24 项及本次恢复修复 23 项分开计数。原始 `RUN.json` 保存实际命令、退出码和日志哈希。审计输出有效不等于科学条件通过：`audit_valid=true`，`scientific_decision=HOLD`，`p3_strong_control_satisfied=false`，`authority=DENY_ALL`。

## 已确定的强对照缺口

| helpful 场景 | 留存容量 | 累计梯度更新 | 累计训练呈现 | 选择性更新 |
|---|---:|---:|---:|---|
| 分化候选 | 12 个 FP64 参数 / 96 B | 257 | 49,280 | 只 fit 新专家，旧专家冻结 |
| fixed experts | 12 个 FP64 参数 / 96 B | 384 | 65,536 | 旧、新专家都 fit |
| expanded monolith | 10 个 FP64 参数 / 80 B | 256 | 65,536 | 一个未分裂模型继续 fit |

累计预算包含共同父模型预训练、臂内 fit 和诊断 probe；共同预训练在每个比较账内计一次，不能将比较账相加当作重复物理执行。呈现数为实际 full-batch 行数乘更新次数。上述预算由原记录和固定训练 kernel 核对，不是新训练。

Helpful 的 5/5 个种子中，候选新专家和 fixed 的新专家 FP64 参数位模式相同，全部原始新任务预测也相同。候选旧专家保留父参数，fixed 旧专家被再训练；整体差异落在旧任务部分。因此该实验没有分离结构变化与选择性冻结的收益。未分裂对照连留存容量也不相同。

五种子平均 MSE：候选 `0.0025521075641996892`，fixed `0.0026148982064359292`，平均 gain `0.000062790642236239952`，仍低于原预设 `0.0005`。所有 helpful trial 都有 `insufficient_gain_over:fixed_experts`，redundant 场景也不能补成分化成功样本。

## 结果身份与下一项实质工作

全量 `AUDIT.json` SHA256 为 `123b0c77b77fe8c3cbe56024dafaef8f4eb55971119eb1cbd592ad43d4f781d4`；`audit.py` 为 `8fd98f7203a2e511094083ee0e4c28e50b9d9e87d5d2f97661992bfd20868a2a`；`test_audit.py` 为 `d846afe6fda5e744758f07038b795a236b8345f3da78498062a598b83a29e75e`。

下一份有效证据必须先冻结新的完整比较方案：固定专家采用相同容量、旧专家冻结规则和累计预算，不分裂对照也匹配容量与累计预算；预训练、诊断、路由、试错、选择、失败和未完成样本都入账，再比较未见任务收益和旧能力保持。现有结果不能通过改变门槛、删样本或重命名对照成为通过结果。本次新增训练更新 0、新预测 0，没有给 P4 或 P5 转计资格。
