# 测试日程重叠勘误：本轮 64 / 320 日程曾用于另一 fit

这是结果产生后的独立只读审计。它修正本轮测试日程的独立性描述，不修改协议、driver、原始结果、门控、分母或任何置信区间。本次审计没有运行模型、生成随机数、重新生成世界、删除样本或选择替代 seed。

**本轮的 320 个评估世界不能全部称为此前研究从未使用的日程。** 已确认 fit11 的 32 个 IID 和 32 个 OOD 日程，与原 continuation-head 研究中 fit23 的日程完全相同。它们在本轮接受的是 fit11 的 A/C/P/CP 评估，不是旧 fit23 输出的复制。

## 1. 加法 seed 碰撞及内容证明

四项研究沿用同一固定 `joint/run_head_edit.py::make_worlds`：

`world_seed = base_seed + fit * 10000 + (1000000 if domain == "ood" else 0)`。

| 研究 | base seed |
|---|---:|
| 原 continuation-head | 870040000 |
| Belief 权重 follow-up | 870140000 |
| NDU value-grid | 870150000 |
| 本轮解析 Belief 旁路 | 870160000 |

因此 IID 中：

`870160000 + 11 * 10000 == 870040000 + 23 * 10000 == 870270000`。

OOD 两边同加 `1000000`，得到 `871270000`。更换 base seed 和 world ID 没有保证日程不同。

证明不依赖再次调用生成器。审计只读取本轮已保存的两个 fit11 `WORLDS` 文件，在内存将管理性 `id` 恢复成旧 fit23 的格式，再使用原记录的 `json.dumps(..., sort_keys=True)` 序列化。所得 SHA-256 与原冻结 `results_strict.json.gz` 的 `public_worlds_sha256` 精确一致：

| 域 | 与旧 fit23 完全一致的 32-world 记录 SHA-256 |
|---|---|
| IID | `85777af0a0e60ac97b3864ef7f101add2951673f27ba6917d6ab2170afcc2093` |
| OOD | `b971f69307dd671dcc699440af9f411173c4918cb849750fa5f3f8b0b6964b40` |

审计绑定当前和三项旧研究的协议、结果、执行脚本及共同生成器 SHA。当前 10 个完整 block 与三项旧研究的 30 个 block 作了 **300 次**比较，只有上述两块完全匹配。对具备逐世界内容的 NDU value-grid 还作了单世界规范化日程比较，没有匹配；当前 320 个日程内部也没有重复。

这些检查**不能证明剩余 256 个日程在所有历史来源中均未出现**。旧 head / Belief 交付中可直接比对的是完整 block 的内容哈希，而本次没有重建它们的逐世界内容；也没有加载全部历史 TRAIN/VAL/正式确认世界。机器收据将“确认全球未见数量”记为 `null`。

## 2. 其他 RNG 与原 TRAIN/VAL 的范围

`behavior_rows` 使用另外的加法式：

`base_seed + fit * 10000 + 5000000 + (100000 if domain == "ood" else 0)`。

本轮 fit11 IID/OOD 的 behavior RNG seed 分别与原 fit23 对应域相同；本轮 fit11 OOD 还与 Belief follow-up 的 fit23 IID 同为 `875370000`。**相同 RNG seed 不等于相同 probe 行**：世界、域和 fit 特定 decoder confusion 会影响条件观测和访问状态。没有对旧 probe 行作内容一致性断言。NDU 网格研究没有调用新的 `behavior_rows`。

原 `joint_data.py::cohort` 是另一种生成器，它在日程之间还抽取 latent trajectory、packet、失败等随机量。其已存协议为：

- TRAIN/VAL：`data_seed_base = 202611110000`。
- 原正式 IID/OOD 确认：`confirmation_seed_base = 202611130000`。
- cohort seed：对应 base `+ fit * 1000000 + split_id * 100000`，其中 TRAIN/VAL/IID/OOD 的 split ID 为 0/1/2/3。
- 原 TRAIN/VAL 行为 seed：`data_seed_base + fit * 1000000 + (700000 if train else 800000)`。

五 fit、四 split 的全部 20 个 cohort seed 已列入收据，它们与本轮 world seed 没有整数相等。这里只确认源代码定义；不同 seed 或不同生成器并不证明实现出的日程内容不重叠。本审计没有重新生成原 TRAIN/VAL、packet 或确认数据。

## 3. 对当前结论的影响

“全部五 fit 的门在本轮 TEST 执行前冻结”仍由原 hash 链与事件记录支持，但它不能推出“本轮测试日程在全球历史上从未被使用”。原 VAL 集还曾用于旧 C 的选择。这两项限制应分别披露。

原始 P−A 的 IID/OOD 正均值、全部五 fit 的方向、描述性区间和概率误差下降均保持原值；门控后 P/CP 收益区间跨零的结论也保持不变。本次没有将其余四个 fit 另行挑出作为新主结果，也没有删除已复用的 fit11。原完整五 fit 的结果仍是主结果，但应描述为含已知跨研究日程复用的探索性结构消融，不能升级为全部日程独立的新确认、门控部署收益资格或纯 WSP 证明。

原 `verify_analytic_belief.py` 及其执行收据保持不变；其中 `fresh_world_records_verified` 核实的是当前记录的计数、ID、算术和 hash，不是跨历史内容的全局新颖性。新增审计是对此范围的明确补充。

## 4. 独立复核

从发布后的本目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python verify_seed_overlap.py --study-root ../joint
```

该脚本仅用 Python 标准库读取已存证据，不导入模型或 NumPy，不调用 RNG。它重建种子组合、恢复旧 ID 作历史哈希比较、核对规范化日程内容，再与 [seed_overlap_audit.json](seed_overlap_audit.json) 完整比较。此次已实际通过，状态为 `passed_with_disclosed_cross_study_reuse`。`--emit` 可将同一审计重建结果输出到 stdout；不会由脚本修改现有记录。

规范化日程包含所有本有限任务的 policy/evaluator 外生字段，去除管理性 `id` 及此处未读取的占位 `packets` / `packet_sha256`。这一规则仅用于当前解析合成任务，不能直接替代真实 FullHX 内容任务的身份规则。

## 5. 后续设计建议，当前未实施

未来协议可对冻结设计摘要、生成器 SHA、fit、domain、用途（world/probe）和重复编号作带字段标签的 SHA-256 域分隔，使用完整摘要作为 RNG entropy，避免加法命名空间相撞。设计摘要必须在生成和评估前固定，并排除派生 seed、结果和运行时间，避免循环定义。

域分隔仍不保证有限日程空间不会重复。应在任何评分前，对实际世界的规范化内容与可访问的所有旧 TRAIN/VAL/TEST 做去重，并保留重复清单。发现重复或历史覆盖不完整时，按事先冻结的有界策略停止；不得在看到收益后换 seed、补抽有利样本或删样本。上述方案是后续研究的设计建议，本轮未执行，也没有据此重做当前实验。
