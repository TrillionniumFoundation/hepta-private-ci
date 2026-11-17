# Round03：E1–E6 开发实验运行手册

本轮已完成代码集成和限定范围的工程验证；新的 GPU 训练、正式 Circuit 运行及采用闭环尚未执行。
**本文件和 `OPERATIONS_STATUS.json` 是交付状态快照，不是实际运行 freeze。只有成功的 `prepare` 才创建 `COMPARISON.json`。**
本轮继续使用 Run02 已曝光的 A6／B3；新增独立 N、教师、用户、未来 C 和采用增量均为 0。
下文的来源、测试回执和源码 SHA 见同目录 [OPERATIONS_STATUS.json](OPERATIONS_STATUS.json)。

## 1. 已验证与尚未执行

- 集成 CPU 行为测试 **37/37 通过、0 skip，测试器用时 16.512 秒**；覆盖协议、真实业务 verifier、生命周期和成本汇总，provider／optimizer 使用明确的 fixture。
- 其后修复 report 读取 `OSError` 的分支，**1 项针对性回归通过，0.002 秒**；原 37 项未因该小补丁重复执行。最终 27 个源码文件由两份测试回执共同说明范围。
- 早先真实 tiny Qwen2 + PEFT 的 CPU adapter warm-start 数值测试 **1 项通过**；它不是新任务收益证据，也不能替代当前版本的 prepare 数值门禁。
- source04 的 **11 项生命周期／缓存顺序测试通过独立复核**；未测量实际 GPU 显存释放。37 项集成集合未纳入两个数值测试模块。
- `core64_unchanged=true`；原 core64、旧数据、旧结果和失败原件保持原身份。
- **NOT_RUN：** 共享池 A/B/A 数值检查、默认 backend smoke、正式 prepare、本轮 GPU 训练、primary/cold 模型评估及正式 Circuit。
- H 当前持续返回 HTTP 404 `tunnel_client_not_seen`；已保留观测也包含 `tunnel_client_not_connected`。这是连接故障，**不是 approval 拒绝**。
- `just fmt` 已以唯一 key `round03-final-fmt-20261117-01` 向 Mac 提交，返回 404，未得到 session 或执行回执，**不能宣称通过**；Draft 发布待 root。

## 2. 六组实验的当前状态

| 实验 | 本轮已交付 | 仍不能宣称 |
| --- | --- | --- |
| E1 轨迹价值 | 保留旧冻结／检索／答案／轨迹对照身份与来源限制 | 没有新增未见来源或未来任务的轨迹收益证据 |
| E2 学生自身经验 | 三模式共同初始化、更新后学生采集、修正及 warm-start 链路；CPU 行为验证通过 | 本轮真实两轮 GPU 对照尚未运行；恢复收益未建立 |
| E3 多教师互补 | 区分 authored reference、已有学生模型与外部教师 | 新教师未确认；三个旧 adapter 不是三个外部教师 |
| E4 Circuit 必要性 | 六候选图、A-only 路由、四臂及逐边／逐 Cell 的真实调用协议；CPU fixture 验证通过 | 正式模型图运行、活动参数证据及成本匹配收益尚未建立 |
| E5 用户增长 | 保持来源、lineage 与有效样本计数边界 | 没有新增合格用户／来源，不能画用户增长收益曲线 |
| E6 完整采用闭环 | primary/cold 独立进程入口、候选和请求／答案比较 | 旧 A/B 重用不是新 C；没有 native 采用或冷恢复能力收益证据 |

## 3. E2 的固定对照

teacher、shadow、controlled 均从**同一个旧 Run02 `final_answer` adapter** 开始，共同固定 context、A digest、source inventory。
每臂两轮，每轮 64 optimizer steps；adapter 权重从上一候选 warm-start，**每轮新建 AdamW，optimizer 状态不续训**。
每次 fit 只用当前轮监督（`latest_round_only`），但保留全部旧轮原始回执；下一轮必须加载刚更新的候选。
`teacher` 是重新执行验收的 authored A reference 对照，不调用新的外部教师；shadow 预测不执行，controlled 使用真实 verifier 与规范化反馈。
学生动作保持非监督目标；每轮训练／修正都可能发生参考答案重验，必须单独保留成本。最终 post-update A 仍是已曝光开发任务。

## 4. E4 的固定图与输出规则

F／T／C 分别绑定旧 `final_answer`／`trajectory`／`controlled_correction` adapter，共享固定底座；不替换为本轮 E2 新候选。
六图为 `ff_both`、`tf_both`、`cf_both`、`tf_answer`、`tf_feedback`、`tf_none`；仅 old_A 执行图搜索并拟合 prompt 条件路由。
四臂为同一 F 的两槽位调用、固定 T→F、固定种子随机稀疏图、学习稀疏图；old_B 不参与拟合。
每个任务另做 answer／feedback 逐边移除和 F／T／C 逐 Cell 移除；保持事前路线，不补替代 Cell，不重新训练。无效于该路线的干预明确标为 no-op。
规则是 `earliest_business_success_else_last_surviving`：保留最早业务成功输出，否则取最后存活输出；两槽位的实际调用仍分别付费。
共同 cap：每图最多 2 次调用，每次输入 4096 tokens、输出 384 tokens，relay 2048 bytes；超限保留原件并失败，不截断或临时放宽预算。
同 cap **不等于实际成本相等**；活动参数需 `CELLS.json` 及参数证据绑定。池初始化、A 搜索、四臂和全部干预分别记账。

## 5. 正式入口与执行顺序

以下是命令结构，当前未执行。替换成真实绝对路径和一个从未使用的 run 名称；artifact root 须保留 `candidate-qwen-03`、`research-sft-02`、`research-sft-v1-source`、`e1e2-operation-helpers-04`。
`--module-root` 指向**包含 `online_v4` 的目录**，不是 `online_v4` 本身；Python 使用保留的实际模型环境。

```bash
set -e
ROUND03_ARTIFACT_ROOT='/absolute/retained-artifacts'
ROUND03_MODULE_ROOT='/absolute/reviewed-checkout/scripts/cell_experiments'
ROUND03_PY='/absolute/retained-artifacts/venv/bin/python'
ROUND03_RUN='research-round03-NEW-ID'
round03() {
  "$ROUND03_PY" -I -B "$ROUND03_MODULE_ROOT/online_v4/round03_cli.py" \
    --artifact-root "$ROUND03_ARTIFACT_ROOT" --module-root "$ROUND03_MODULE_ROOT" \
    --run-name "$ROUND03_RUN" "$1"
}
round03 prepare
round03 e2-teacher
round03 eval-teacher-primary
round03 eval-teacher-cold
round03 e2-shadow
round03 eval-shadow-primary
round03 eval-shadow-cold
round03 e2-controlled
round03 eval-controlled-primary
round03 eval-controlled-cold
round03 circuit
round03 report
```

`prepare` 先执行两个实际 tiny CPU 数值测试模块，要求至少 2 项、成功且零 skip；再用真实旧材料做 reference／backend smoke，成功后才写 `ENGINEERING_GATE.json` 与 `COMPARISON.json`。
每条 CLI 都是独立进程；cold 要求观察到不同 PID，并核对同一候选、comparison、panel、source 以及实际请求／答案。它只是已曝光面板的推理重载，不是 optimizer 恢复。
`report` 是纯文件读取汇总，可在工作不完整时使用；stdout JSON 保存到新文件，不覆盖原回执。源码、模型、数据或预算变化后不能复用旧 comparison。

## 6. 失败、锁与资源边界

保留 `PREPARATION_INTENT.json`／`PREPARATION_FAILED.json` 及 `worker-receipts/<job>/INTENT|FAILED|COMPLETE.json`；同一 job 身份拒绝自动重跑。
先调和失败／中断的实际已付工作，再决定新的 run；不要删除原目录以伪造首次执行。e2/eval 的当前 worker 时限为 3600 秒，circuit 为 7200 秒。
`flock` **只串行同一个 run 目录内的 worker**，不是跨 run／跨用户的全局 GPU 锁；资源观测也不等于预约。
保留原 4 GiB 空闲显存门槛；source04 的缓存释放和清理失败路径未授权绕过它，也未证明跨进程资源隔离。

## 7. 结果与成本的解释

`reporting_v4` 的主范围是 E2 loop 采集／post-update A 加 Circuit 搜索／四臂／干预；`round03_report` 将额外 primary/cold A/B 评估费用另列，不重复并入主合计。
E2 `student_verifier_calls` 不是全部 verifier 调用；corrections 和 model/references 的重验总数仍 unknown。训练 token positions 与推理 tokens 分列，嵌套 wall/CPU 时间不相加。
缺失或失败回执产生 `null`／`INCOMPLETE`；known measured subtotal 只代表已验证部分，不能把未记录成本当 0。整体成本状态仍不完整。
已实际执行空目录 readout：25 个缺失 artifact 被列出，合计保持 `null`／`INCOMPLETE`；这验证读取行为，不是一次真实实验或零成本结果。
Graph 与模型候选重放、随机种子、子代理分支、冷重载和新导出时间均不增加独立 N；统计有效 N 仍 unknown。
新检索 [Chain #150](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/150) 仅为 2026-09-13 的历史需求元数据：未补原始轨迹、未分配 A/B/C、未纳入训练，仍同账户／同项目。
本轮未建立 HIA/native Cell 执行、去中心化训练、foundation model 综合能力、Proof-of-Useful-Work 或真实采用资格；相关资格字段保持 false。

## 8. 交付依据

集成验证来自 `integration-01/evidence/INTEGRATED_TESTS_01.json`，新增回归来自 `REPORT_READER_TEST_01.json`；入口审阅来自 `circuit/review02/ROUND03_REVIEW.json`。
tiny CPU 与 source04 lifecycle 的原始回执、源码与 SHA 在 `OPERATIONS_STATUS.json` 中逐项绑定；早期导入失败和更正记录均保留。
恢复 H 后调和原格式化操作并核对真实运行材料；由 `prepare` 执行缺失门禁，成功后产生运行冻结。发布操作及其最终链接由 root 单独记录。
