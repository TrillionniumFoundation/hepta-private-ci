# R2：已固定的内容与仍缺的真实条件

本协议是部分冻结，尚未完整封存，也没有执行 R2。固定字段 canonical SHA256 为 `f720cbb1e97087c8be4ffaec5f006589876b1b3e67dba1cc7ea47c93f4bb108b`。完整 JSON 是 [PARTIAL_FREEZE.json](PARTIAL_FREEZE.json)，原始源码引用及字节身份是 [SOURCE_REFERENCES.json](SOURCE_REFERENCES.json)。

## 已固定

固定来源为 `975e1a264c14ed3da02dcee23a64327825387e42`。实际 `dual_runtime.run`、`LocalModels`、模型获取和 `factorial --bundle` 账本入口都存在；当前真实 provider 参数仍被冻结。历史 `v3.study` 只实现小型合成模型训练，不能把它换个标签称为真实 SmolVLM/tiny-sd 的新四臂训练。

四臂维持 `00 固定控制器＋冻结生成器`、`10 只训练控制器`、`01 固定控制器下只训练生成器`、`11 联合训练`。每个独立 fit 从同一组生成器字节开始，10/11 的控制器初始化配对；冻结参数组必须保持字节不变。主预算估计对象是相同总预算；相同分量训练剂量单独报告，不能用相同更新次数混淆两者。

沿用原实验的 `gamma=2` entropic CE：先逐臂计算 `-0.5 log mean exp(-2R)`，再计算差值。七个对比包括原主比较 `CE11−CE01`、控制贡献、生成贡献、联合对 baseline、交互项、两个条件贡献及对验证选定最强参考的差值。不能把 paired return difference 的 CE 当成两个 arm 的 CE 差。

固定 32 个完整 fit 种子、每来源两次评价 draw，以及对 fit/source 的成对 crossed bootstrap；重复 token、frame、图像调用或 draw 不算独立拟合。七个对比采用 familywise 95% Bonferroni 区间，保留失败、超时、取消与全部未选工作。不做可选停止，也不在 test 上选择最强对照。

强基线的含义已经固定：固定策略要在验证集上真实择优；greedy 是一步净信息价值，不能用旧 actor argmax 冒充；planner 的分支、rollout、模型调用及未选生成都收费；retrieval 使用 train-only 冻结索引，记录索引来源、构建成本、查询成本及返回工件。它们的具体已实现代码、数值预算和选中身份仍须封存。

成本单位固定为 CPU/wall 秒、峰值 RSS bytes、磁盘与网络 bytes、实际计量 joules。原始抽象 CPU tariff `0.02`、wall tariff `0.001` 和原机制的 service fee 表均保留来源。真实 provider 的动作体系与旧机制不同，服务费用映射尚未封存，不能悄悄使用未知即零的默认值。setup、training、analysis、publication 先分开列出，随后按原 `1000/10000/100000` 请求视窗报告摊销敏感性。原子物理事件须去重，嵌套 inclusive envelope 不能再与子项相加。

## 六项具体剩余

| 门槛 | 尚缺什么 | 为什么当前材料不能替代 |
| --- | --- | --- |
| `NEW_DATA` | 真实新数据来源、许可、source-cluster train/validation/test manifests、精确与近重复核查 | R1 图片、旧 V2/V3 cohort、历史 matrix 和 fixture 都已经暴露，不是新测试集 |
| `EVALUATOR_CUSTODY` | 独立 owner、固定评价代码/模型/规则和 labels、权限隔离与最终 dispatch 回执 | 同一目录中的第二个脚本、共享文件系统的另一个 agent、生成器自己的 critique 都不是独立 custody |
| `REAL_TRAINER` | 真实控制器与生成器训练入口、可训练参数组、optimizer/hyperparameters、源码 tree 与新进程 checkpoint 装载 | 现有 `LocalModels` 是冻结推理；旧 `v3.study` 是另一种合成小模型 |
| `BUDGET_AND_BASELINES` | 数值总预算与搜索预算、fixed 候选库、planner 深度/beam/call cap、真实 service 映射、失败/弃权效用、验证选择回执 | 仅写“公平预算”或借用旧 greedy 标签不能完成这些条件 |
| `QUALITY_AND_POWER` | 任务效用/质量量表、安全和质量底线、最小有意义收益、新 test 独立来源数量及预先精度/功效依据 | R1 的诊断错误不能产生新的盲评标签或推定统计功效 |
| `CANDIDATE_IDENTITY` | 真实训练与选择产出的 checkpoint、索引及所有未选候选的固定 hashes | 本次没有训练；不存在可诚实填写的新候选模型 SHA |

R1 的结果已经足以确认输入绑定和计划提示效应，差的 baseline 本身不禁止后续训练研究。但它明确否定了当前 self-critique 充当独立 outcome 的做法。上述缺项解决前不得把数据与评价已经封存作为事实；没有正收益及所有验收门通过时继续保留 incumbent，不自动晋级模型。
