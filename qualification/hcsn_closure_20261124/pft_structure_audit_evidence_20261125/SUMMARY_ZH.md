# HCSN 结构、通信与成本：保存原件的独立复算

日期：2026-11-25。范围是新 `closure-v1` 的 **63 个主候选**，加 `baselines-v1` 27 个、`joint-training-v1` 9 个、`communication-training-v1` 21 个，共 **120 个**。本报告不合并历史 `formal-v1` 的 72 个实验，也没有重跑这些封存训练。

## 已实际执行的核验

纯 Python 标准库脚本在 desktop 实际执行，读取已保存的 `PROTOCOL/SEAL/TEST_CLAIM`、逐候选训练/测试终态、checkpoint 字节与压缩原始预测。独立重算 selected、initial、cpu_prefix 三组 accuracy、交叉熵、Brier、逐来源表现、晚到信息前表现与停时指标。120/120 个候选的字节绑定和指标一致性通过；最大指标差为 `2.220446049250313e-16`。该结果证明保存证据自洽；本审计没有反序列化 checkpoint、重放物理核或证明原始执行环境不受篡改。

所有 120 个训练实际完成 512 updates。学习门要求最终准确率至少 0.8、相对 initial 至少增加 0.1、相对同一候选 pre-late 至少增加 0.1。main 为 63/63，baselines 为 25/27，joint 为 3/9，communication 为 12/21。

以下表格报告开发集选择后的 **selected** checkpoint，不一定是第 512 次更新。每行保留全部三个种子；“±SD”为种子间样本标准差，以百分点计，不是置信区间。测试来源对同组模型共用，因此三种子也不是三个独立用户。完整逐种子 CE、Brier、initial/pre-late、最差来源、选中步数、CPU-prefix 步数及 41 组配对差值见 [summary.json](summary.json)。

## 1. 新 closure63 主表

混合精度中的 value/risk 与 tanh 使用相同 physical-state 分配、读出维度、signed 消息通道、数据和更新政策；这里的 tanh 是 HCSN 内部特征对照。learned boundary 比 fixed/QVI 多 N 个可训练标量，不能据此声称完全相同的可编辑参数域。

种子顺序固定为 `17011 / 27011 / 37011`。准确率与 pre-late 列以百分比表示。

| N | boundary / features / precision | 活跃参数 | 三种子准确率 | 均值 ± SD | pre-late均值 | 门 |
|---:|---|---:|---|---|---:|---:|
| 8 | fixed / value_risk / mixed | 154 | 90.918/90.430/89.746 | 90.365 ± 0.589 | 75.521 | 3/3 |
| 8 | fixed / tanh / mixed | 154 | 90.527/90.234/90.137 | 90.299 ± 0.203 | 75.423 | 3/3 |
| 8 | learned / value_risk / mixed | 162 | 91.797/91.309/90.723 | 91.276 ± 0.538 | 75.521 | 3/3 |
| 8 | learned / tanh / mixed | 162 | 91.504/90.820/90.430 | 90.918 ± 0.544 | 75.358 | 3/3 |
| 8 | qvi / value_risk / mixed | 154 | 90.625/90.234/90.039 | 90.299 ± 0.298 | 75.586 | 3/3 |
| 8 | qvi / tanh / mixed | 154 | 90.430/90.527/90.723 | 90.560 ± 0.149 | 75.163 | 3/3 |
| 8 | qvi / value_risk / native32 | 154 | 90.625/90.234/90.039 | 90.299 ± 0.298 | 75.586 | 3/3 |
| 32 | fixed / value_risk / mixed | 1186 | 91.699/90.918/91.895 | 91.504 ± 0.517 | 75.781 | 3/3 |
| 32 | fixed / tanh / mixed | 1186 | 91.211/90.430/90.625 | 90.755 ± 0.407 | 75.260 | 3/3 |
| 32 | learned / value_risk / mixed | 1218 | 92.480/91.699/91.992 | 92.057 ± 0.395 | 75.651 | 3/3 |
| 32 | learned / tanh / mixed | 1218 | 91.699/90.625/91.309 | 91.211 ± 0.544 | 75.553 | 3/3 |
| 32 | qvi / value_risk / mixed | 1186 | 91.992/91.602/92.285 | 91.960 ± 0.343 | 75.846 | 3/3 |
| 32 | qvi / tanh / mixed | 1186 | 91.699/90.625/90.527 | 90.951 ± 0.650 | 75.391 | 3/3 |
| 32 | qvi / value_risk / native32 | 1186 | 91.797/91.602/92.285 | 91.895 ± 0.352 | 75.944 | 3/3 |
| 64 | fixed / value_risk / mixed | 3906 | 91.211/91.895/92.383 | 91.829 ± 0.589 | 76.009 | 3/3 |
| 64 | fixed / tanh / mixed | 3906 | 91.797/90.723/91.113 | 91.211 ± 0.544 | 75.977 | 3/3 |
| 64 | learned / value_risk / mixed | 3970 | 91.602/89.844/91.992 | 91.146 ± 1.144 | 75.586 | 3/3 |
| 64 | learned / tanh / mixed | 3970 | 92.285/90.820/91.309 | 91.471 ± 0.746 | 75.846 | 3/3 |
| 64 | qvi / value_risk / mixed | 3906 | 91.992/91.113/91.504 | 91.536 ± 0.440 | 74.805 | 3/3 |
| 64 | qvi / tanh / mixed | 3906 | 91.992/90.918/91.016 | 91.309 ± 0.594 | 75.814 | 3/3 |
| 64 | qvi / value_risk / native32 | 3906 | 91.992/89.258/88.477 | 89.909 ± 1.846 | 74.740 | 3/3 |

在 N32，value/risk 相对 tanh 在三种 boundary 的三个配对种子均为正：均值增益分别为 fixed **0.749**、learned **0.846**、QVI **1.009** 个百分点。效果并不普遍：N8 QVI 的均值差为 −0.260 个百分点，N64 learned 为 −0.326 个百分点。不能从全部 63 个过门推出 value/risk 普遍优于 tanh。

N64 native32 相对 mixed 的配对准确率差为 `0.000 / −1.855 / −3.027` 个百分点；均值 −1.628。单凭三个种子和工程容差不能作统计非劣性结论。

## 2. 传统基线

main 与 baseline 的 train/dev/test 数据 SHA 集合逐项相同；训练政策相同；联合 test seal 正确绑定本次主 63 的 seal。参数以 HCSN 的 active count 近似匹配。GRU 与目标数精确匹配，但其他架构有小幅差异。baseline 使用零初态而 HCSN 使用随机 physical initial margin，状态、运算、dtype 和 Transformer 的 KV 增长亦不同。这些是有信息量的基线，不是同等函数容量证明。

| HCSN参照 N | 架构 / width | 活跃参数 | 三种子准确率 | 均值 ± SD | 门 | 平均完整fit启动到退出秒 |
|---:|---|---:|---|---|---:|---:|
| 8 | GRU / 4 | 154 | 96.875/97.754/94.336 | 96.322 ± 1.775 | 3/3 | 7.582 |
| 32 | GRU / 16 | 1186 | 96.777/96.191/95.215 | 96.061 ± 0.789 | 3/3 | 7.335 |
| 64 | GRU / 32 | 3906 | 96.680/96.680/96.387 | 96.582 ± 0.169 | 3/3 | 7.703 |
| 8 | surrogate_LIF / 9 | 155 | 97.656/95.215/95.996 | 96.289 ± 1.247 | 3/3 | 8.404 |
| 32 | surrogate_LIF / 30 | 1142 | 96.387/95.898/94.434 | 95.573 ± 1.016 | 3/3 | 9.086 |
| 64 | surrogate_LIF / 58 | 3830 | 93.945/95.117/95.215 | 94.759 ± 0.706 | 3/3 | 9.220 |
| 8 | causal_Transformer / 3 | 134 | 80.762/83.008/87.207 | 83.659 ± 3.272 | 3/3 | 8.290 |
| 32 | causal_Transformer / 11 | 1190 | 82.520/96.777/96.973 | 92.090 ± 8.289 | 2/3 | 7.435 |
| 64 | causal_Transformer / 21 | 3950 | 98.145/98.145/75.586 | 90.625 ± 13.024 | 2/3 | 7.467 |

预定 QVI/value-risk/mixed HCSN 的 N8/N32/N64 均值分别为 90.299% / 91.960% / 91.536%；相同参照规模 GRU 为 96.322% / 96.061% / 96.582%。在这组短序列合成任务上，现有结果不支持 HCSN 胜过 GRU。GRU 的实际训练成本也明显较低；不同执行并发和容量使这些壁钟比值不能直接解释为硬件无关的加速比。

## 3. joint：boundary 与 signed 联合

本组使用独立训练/测试来源，不能把不同 study 的均值当作同一数据上的配对结果。种子顺序为 `22011 / 32011 / 42011`。三个臂具有相同分配状态，但联合臂的 active recurrent 参数是单通道的两倍（1536 对 768），总 active 参数为 1954 对 1186。

| 通道 | 活跃参数 | 三种子准确率 | 均值 ± SD | pre-late均值 | 门 |
|---|---:|---|---|---:|---:|
| boundary_only | 1186 | 51.172/51.172/51.172 | 51.172 ± 0.000 | 51.172 | 0/3 |
| signed_only | 1186 | 92.090/92.090/89.844 | 91.341 ± 1.297 | 74.772 | 3/3 |
| boundary_signed | 1954 | 73.633/73.535/74.121 | 73.763 ± 0.314 | 69.531 | 0/3 |

联合臂相对 signed-only 的配对变化为 `−18.457 / −18.555 / −15.723` 个百分点，均值 −17.578；本协议下加入 boundary 没有带来联合收益。boundary-only 为 0/3 过门，signed-only 为 3/3。该观察不能推广为所有 boundary 控制无效。

## 4. communication：unsigned 变换与输入缓存

种子顺序为 `18011 / 28011 / 38011`。所有臂均为 N32/QVI/value-risk/mixed；unsigned+signed 比 signed-only 多 768 个活跃连接权重。所有七臂实际都分配 pending/held 张量，完整状态计数相同；hold/accumulate 改变的是缓存真正保留和参与控制的信息。因此，分配字节相同仍不能证明相同有效记忆容量。

| 臂 | 活跃参数 | 三种子准确率 | 均值 ± SD | pre-late均值 | 门 |
|---|---:|---|---|---:|---:|
| signed_only | 1186 | 92.480/91.211/92.188 | 91.960 ± 0.665 | 75.944 | 3/3 |
| unsigned_signed_raw | 1954 | 91.699/92.578/75.977 | 86.751 ± 9.342 | 75.618 | 2/3 |
| unsigned_signed_centered | 1954 | 93.164/94.336/93.652 | 93.717 ± 0.589 | 75.358 | 3/3 |
| unsigned_signed_centered_bounded | 1954 | 93.164/93.457/93.848 | 93.490 ± 0.343 | 75.488 | 3/3 |
| boundary_raw | 1186 | 50.293/50.293/50.293 | 50.293 ± 0.000 | 50.293 | 0/3 |
| boundary_accumulate | 1186 | 50.293/50.293/50.293 | 50.293 ± 0.000 | 50.293 | 0/3 |
| boundary_hold | 1186 | 94.922/50.293/50.293 | 65.169 ± 25.767 | 58.464 | 1/3 |

unsigned centered 相对 signed-only 三种子都提高，配对差为 `+0.684 / +3.125 / +1.465` 个百分点，均值 +1.758；centered+bounded 为 +1.530 个百分点。由于新增活跃参数，不能把提高全部归因于 unsigned 的表达意义。raw unsigned 的种子方差大，2/3 过门；boundary_hold 只有 1/3 过门，另外两个仍接近机会水平。

## 5. 参数、初态、状态与数据的可比范围

“active 参数”是扣除结构 mask 后的可训练坐标数，不等于函数秩或参数可识别性。下表取 QVI/value-risk/mixed 与对应基线；状态计数为保存报告中的最大测试 chunk，排除模型参数、输出和 AD tape。它是已有记录，本审计没有动态重演这些 bytes。

| 模型 | 分配总参数 / requires_grad / active | N8状态bytes | N32状态bytes | N64状态bytes | 初态/增长 |
|---|---|---:|---:|---:|---|
| HCSN mixed | N8: 306/298/154; N32: 3522/3490/1186; N64: 13186/13122/3906 | 26624 | 106496 | 212992 | 随机physical margin；固定时长状态 |
| GRU | 154 / 1186 / 3906（各自total=requires_grad） | 256 | 1024 | 2048 | 零初态；固定时长状态 |
| surrogate_LIF | 155 / 1142 / 3830（各自total=requires_grad） | 1728 | 5760 | 11136 | 零初态；固定时长状态 |
| causal_Transformer | 134 / 1190 / 3950（各自total=requires_grad） | 4608 | 16896 | 32256 | 零初态；KV随prefix线性增长 |

native32 的物理状态 bytes 为 mixed 的一半。joint N32 的物理状态为 106496 bytes；communication 各臂均为 106496 + 768 = 107264 bytes。跨架构比较没有匹配这些容量。

数据全部来自同一合成生成器族，但 source IDs 在各 study 的 train/dev/test 内严格不重叠。每个主测试候选为 16 个 sources × 64 个例子 = 1024；这不代表真实用户、更广泛任务或大语言模型能力。

### 终步与选择规则的精确区别

所有训练完成 512 updates，但 selected 由开发集最小 CE 选择。没有单独命名的 last_model 测试。已实读 cpu_prefix_step：main 有 21/63 个达到 512；baseline 有 27/27 个达到 512；joint 为 0/9，communication 为 0/21。因此前两组中的这些候选，其 cpu_prefix 已覆盖终步，不能笼统写成全部终步均未评估。比较 selected 是相同选择政策的比较，并非全部使用相同步数参数。

## 6. 全成本与嵌套边界

下表区分每阶段完整子进程 CPU（含启动/退出）与外层实际壁钟；不能把逐 worker、body、stage、outer 累加成新的总成本。不同 study 的候选数和并发不同，表中总数不是架构加速比。能耗没有可读硬件计量。

| study | fit完整child CPU秒 | test完整child CPU秒 | 外层/活动壁钟秒 | 解释 |
|---|---:|---:|---:|---|
| main | 21616.053 | 4751.620 | 3177.340 | outer prepare+campaign；9 workers |
| baselines | 213.934 | 204.026 | 2903.516 | campaign含等待main seal；27 fits+tests顺序child壁钟和仅425.690秒 |
| joint | 2277.083 | 436.827 | 720.250 | outer含source安装/preflight/freeze/audit；fit/test为6 workers |
| communication | 9421.373 | 1597.754 | 2604.238 | operator prepare 2.446 + run2601.792；5 workers，诊断observer计入 |

上表 main 的 driver CPU 为 35.258 秒，已包含其内层阶段 driver 计时；joint outer 的 complete children CPU 为 2733.225 秒（范围包括安装/preflight/audit，宽于仅 fit/test 的 2713.910 秒）。communication operator 记录 prepare subtree CPU 2.403 秒与 run subtree CPU 11037.101 秒；baseline coordinator CPU 10.330 秒。原始记录及所有逐 seed 成本在 summary/audit 内，scope 不相同时不混加。

本次独立审计自身为 **21.823 秒**启动到退出壁钟、**17.200 秒**child CPU（user16.711 + system0.489）；它不是重新训练的时间。remote job `1a2109c47dd-ffbe-3c79` 为 succeeded/exit0，stdout/stderr 均完整 EOF，output_complete=true。

## 7. 仍不能据此声称的结论

这些证据支持真实 HCSN 小网络在指定任务上的训练可行性，以及特定通信/特征选择的条件性效果；不证明端点条件唯一识别大模型 parameter field，也不证明 learned Circuit 在同参数域、同状态容量、同总资源下优于 fixed/random/single 网络。冻结连接会改变可编辑域，学习拓扑会增加结构选择自由度。严格 E4 六臂比较仍须同时约束 learned、fixed、random、single_equal_budget、edge_deleted、message_shuffled 的数据与完整资源向量。

同一已冻结父模型的删边/消息置乱只能回答当前通信是否必要。另一个模块执行的新因果干预应单列，与本报告的120个保存结果区分；此处没有声称已经完成严格同容量的学习连接优势验证。

## 文件与复核

- [audit.json.gz](audit.json.gz)：完整独立审计，解压后字节与 desktop 原件一致；原始 JSON SHA256 `47e37ca4e356f8adf06e7926c96247ea9906b7478808992b8a6d2d9d45b537ba`。
- [summary.json](summary.json)：40行分组、41组逐种子配对差值、完整成本与比较范围。
- [supplement.json](supplement.json)：CPU-prefix步数、原先报告的状态bytes、nested body costs与实测Torch解释器。
- [MANIFEST.json](MANIFEST.json)、[TRANSPORT_VERIFICATION.json](TRANSPORT_VERIFICATION.json)：交付文件hash、17个版本绑定读取chunk和解压验证。
- [remote_status.json](remote_status.json)、[remote_logs.json](remote_logs.json)、[RUN_TERMINAL.json](RUN_TERMINAL.json)：实际运行的完成状态与原始终端证据。

代码：`../pft_structure_audit.py`。可将四个原件根目录传给 `audit --input main=... --input baselines=... --input joint=... --input communication=... --output NEW_PATH` 重新核验；输出必须位于原件根之外且不存在。该命令不训练、不构造新的测试数据。
