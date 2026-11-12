# 首轮完整强制配对的实测结果（source I）

**这批强制 READ 没有形成平均已观测净收益；其中 13 个配对仍获得了超过各自已测额外时间成本的收益。**

本文件只描述 source `0696d242632bd1bad6668267c52b0bd791241504`、`run-v1` 的强制 STOP/READ collection。该轮采集完整、拟合失败，没有进入六策略评估。它不是修复后 source J 的六策略或 2×2 结果；两轮使用相同来源，不能合并增加独立样本数。

## 分母与四层证据

原件为 [COLLECTION_ANALYSIS.json](COLLECTION_ANALYSIS.json)，原始字节 SHA256 为 `8a0fbe934588f5a61ff35fe01705ec68053980214146ec3685fb0e339847fe89`。126 个唯一 pair、42 个来源、每来源 3 个情境；全部 MATCHED，0 UNKNOWN。每 pair 实际执行完整 STOP 与 READ，共 252 个分支。内部划分为 24 个训练来源 / 72 pair、18 个校准来源 / 54 pair，不是 evaluation 或新来源确认集。

| 层次 | 原始观测 |
| --- | ---: |
| 新 OCR 文本 | 100/126 |
| 首次出现后验 reference-matching 候选 | 18/126 |
| READ 内实际选文改变 | 92/126 |
| 配对 STOP/READ 最终选文改变 | 92/126 |
| 真实交付内容改变 | 92/126 |
| 终态质量提高 / 持平 / 下降 | 13 / 91 / 22 |

三个选文／交付变化指标的 92 个 pair，经逐 pair 比对确为同一集合。新增 OCR 文本不等于语义信息增益，选文变化不等于采用新增匹配候选，交付变化也不等于改善。

## 按原 pair 对齐的交叉结果

[ATTRIBUTION_CROSS_TABS.json](ATTRIBUTION_CROSS_TABS.json) 保留了实际交叉计数，没有由边际频数推定对应关系。

| 首次出现 reference-matching 候选 | 质量提高 | 持平 | 下降 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 是 | 12 | 6 | 0 | 18 |
| 否 | 1 | 85 | 22 | 108 |

新增匹配候选的 18 个 pair 中，12 个质量提高、6 个持平；另有 1 个未新增匹配候选的 pair 也改善。该指标使用参考进行后验测量，不能据此声称执行前的公开状态已经能识别有益 READ，或把这些计数当作已证明的因果转化率。

新 OCR 的 100 个 pair 中，13 个提高、73 个持平、14 个下降；没有新 OCR 的 26 个 pair 中，18 个持平、8 个下降。选文／交付改变的 92 个 pair 中，13 个提高、57 个持平、22 个下降；另外 34 个 pair 全部质量持平。

## 已观测时间成本

先在每个来源内对配对情境求均值，再对 42 个来源等权平均：

| READ − STOP | 来源等权均值 |
| --- | ---: |
| 终态质量差 | −0.04365079365079365 |
| 额外已测 latency cost | +0.014432791228395046 |
| 已观测 latency net 差 | **−0.05808358487918869** |

126 个 pair 的额外已测成本逐项严格为正。质量提高的 13 个 pair 与净值为正的 13 个 pair 确为同一集合；另外 113 个 pair 的已测净差为负。

该成本沿用原 collection 的计时范围及 0.01/秒价格。它与后续 evaluation 的 `TERMINAL.row.task_cost` 范围不同，不能混算。provider、energy、训练和其他完整一次性成本仍未知；不把未知成本填 0，也不将本表升级为完整经济净收益。

## 独立复算与决定

[INDEPENDENT_COLLECTION_SUMMARY.json](INDEPENDENT_COLLECTION_SUMMARY.json) 来自只读诊断 job `1a1ced2711d-2564-1870`，exit 0，stdout 完整 11,761 B、stderr 0 B。原件按既定 SHA 校验后，从 126 条原始配对行独立重算来源等权指标，stored metrics 无不一致；传输后的 gzip 解压和 SHA 再校验通过，交叉计数亦由另一审阅者从原始 JSON 复核。

此结果证明 READ 能真正改变内容与终态，也暴露了实际退化及成本。它没有证明任何策略已经在执行前识别并选中了这些有益 READ，不能代替六策略执行结果。维持 **NoUpdate**，无新来源效益确认或 production admission。
