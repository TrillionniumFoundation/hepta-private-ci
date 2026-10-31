# Evidence map：原始记录、派生分析与恢复路径

本研究的源码、协议、审计源码、报告和图表直接发布；体积较大的运行记录、checkpoint、逐query预测、trace和派生分析保存在下面五类可校验归档中。每个bundle由一个JSON manifest和按manifest顺序拼接的连续XZ分片组成，每个完整分片为262144 bytes，最后一片可以更短。

恢复助手同时校验分片、完整归档和每个成员的SHA-256；拒绝覆盖内容不同的现有文件。五包均已经在新目录实际恢复并逐成员核验。报告内的`results/...`相对链接指向**恢复后的路径**，不是省略的证据；完成[REPRODUCE.md](REPRODUCE.md)中的恢复命令后即可使用。

## 1. 五类归档清单

下表bytes是manifest中的真实数值，压缩bytes只统计按序拼接的XZ分片，不包含旁边的manifest、核验记录或日志。

| Bundle | 成员数 | 分片数 | 成员未压缩bytes | XZ压缩bytes | 恢复目的地（仓库根目录为起点） |
| --- | --- | --- | --- | --- | --- |
| [development001](artifacts/development001/development001.json) | 228 | 21 | 24605445 | 5353028 | `experiments/hcsn_mechanism_content_v2/development` |
| [mechanism001](artifacts/mechanism001/mechanism001.json) | 126 | 54 | 237378624 | 13960020 | `experiments/hcsn_mechanism_content_v2/results/mechanism001` |
| [content001](artifacts/content001/content001.json) | 2448 | 183 | 149121856 | 47716564 | `experiments/hcsn_mechanism_content_v2/results/content001` |
| [content_analysis001](artifacts/content_analysis001/content_analysis001.json) | 8 | 2 | 5208677 | 442420 | `experiments/hcsn_mechanism_content_v2/results/content_analysis001` |
| [supporting001](artifacts/supporting001/supporting001.json) | 146 | 5 | 29176480 | 1292476 | `experiments/hcsn_mechanism_content_v2` |

共2956个归档成员、265个分片；成员bytes合计445491082，XZ分片bytes合计68764508。开发副本、独立复算及摘要副本存在有意保留的重复记录，这些总量不是独立样本数，也不能用来重复计算实验CPU成本。

完整XZ流的SHA-256如下：

| Bundle | Archive SHA-256 |
| --- | --- |
| development001 | `c3f2698c0484a21261dcc3c96281ef641cd55c93d60677a7c205a82a625edf1b` |
| mechanism001 | `5428a08477abb9268074a0e461d84d1241218f3f62dfd397ccdde7eafa2af556` |
| content001 | `a58534aec1c9bcad5c7cda65659c4d6f03bfb372c7b442767ee0a0fe0d90bd7f` |
| content_analysis001 | `6a28afaa0ae16459e313c9b4d9b6079e48780996ecd8fb93fa111b7e14ac6cba` |
| supporting001 | `7e6510aec276893c00f75abad614f1a166ecc6057eea8a0ca9e6b53967f9d993` |

## 2. 什么是原始运行记录，什么是后处理

### Development：保留选型过程与负结果

`development001`包含content和mechanism开发记录、索引和完整证据副本。无显式地址的Copy失败、增加共同地址后的改进、AV选择step0、binding机会水平结果均保留。开发记录不是正式heldout确认；部分最早probe仅保存旧源码SHA，未保存当时全部源码blob，这一历史重放限制已在`development/CONTENT_INDEX.json`披露。

### Mechanism：原始jobs、独立进程账本及当时的候选分析

`mechanism001`恢复后有三个子目录：

- `jobs/`：69个运行输出文件，包括模型、动作、READ观测、episode、预测、选择和trace记录。
- `meter/`：51个外部进程监督文件，记录实际CPU、wall、内存、退出码和输出哈希。
- `analysis/`：6个候选后处理文件。它们属于分析结果，不应与原始运行记录或独立审计混为一类。

该包保留了原始及派生目录结构。独立审计和路径迁移后的复算结果在supporting包中。

### Content：108个正式jobs的完整运行证据

`content001`只包含`jobs/`和`meter/`：2013个job输出文件及435个进程账本文件。108个jobs全部成功；包内有**324个`.pt`文件**（每job的初始参数、selected和final checkpoint）及**717份raw预测表**，同时保留任务标签、sample/group/source IDs、逐query位置、读出时间、输入/checkpoint哈希、训练trace、选点记录、冻结状态与准备/推理成本。

因此正式实验的原始运行数据、参数与checkpoint可以完整恢复，不需要从报告中的均值反推原始数据。可直接阅读的小摘要是[overview/content_meter.json](overview/content_meter.json)，它与原始`results/content001/meter/summary.json`逐字节相同。

### Content analysis：可从raw logits重算的派生结果

`content_analysis001`有8个文件：`jobs.json`、`metrics.json`、`aggregates.json`、`paired_seeds.json`、`paired_bootstrap.json`、`diagnostics.json`、`cost_aggregates.json`和`manifest.json`。它们是从原始content records计算出的质量、整序列exact recall、配对差、描述性bootstrap、干预和成本汇总。`manifest.json`保存输入与分析器的SHA，分析器没有训练模型或重新选择checkpoint。

### Supporting：独立验证、审计、复算和可移植性证据

`supporting001`内的成员已经带有`results/`等前缀，必须恢复到实验根目录。它包含：

- `results/validation001/`：冻结研究的验证执行与输出。
- `results/audit_development001/`：prepared AV重建、开发核查和验证研究审计。
- `results/audit_formal001/`：完整mechanism/content独立审计、发现、训练成本核对，以及保留的首次失败记录与修正版。
- `results/replay_blueprint_check001/`：机械迁移路径后的plan、108个content模板和检查收据。
- `results/analysis_replay_check001/`：在新路径上复算的机制分析结果。
- `audit_source_history/`：旧auditor精确源码快照、修改前身份记录和路径迁移一致性核验。
- `overview/content_meter.json`：108 jobs成功的原字节摘要副本。
- `SUPPORTING_COPY.json`：staging成员、来源前缀、大小和SHA清单。

该包没有再次包含formal content/mechanism原件，也不包含持续变化的`publication/`目录。[INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md)和审计源码直接发布，独立审计不会因为与候选分析数值相同而变成候选分析的一部分。

## 3. 输入数组与原始媒体的边界

五包保存本轮的完整运行证据。实际读取的prepared AV数组由基线已提交的`foundations001`归档恢复；其命令在[REPRODUCE.md](REPRODUCE.md)第一节，三份NPZ及归一化身份由[DATA_IDENTITY_VERIFIED.json](DATA_IDENTITY_VERIFIED.json)固定。合成输入由冻结代码、formal data seed和任务参数生成，预测记录还绑定输入数组SHA。

这足以恢复本轮消费的模型输入、raw预测和checkpoint，并重新计算报告指标。它不表示五包包含所有解码前的原始音视频文件，也不表示重新采集了新actor。媒体来源、许可证和历史处理记录保存在`provenance/`及基线证据中。

## 4. 核验与成本收据

每个bundle旁均有`VERIFICATION.json`，记录归档SHA、成员/分片数和实际restore结果。content、content_analysis和supporting另有`WHOLE_PROCESS.json`，由Linux wait4记录整个归档子进程成本：分别35.658287、1.076759、4.637627 CPU秒。它们包括import、打包、恢复和核验，必须与模型实验预算分开。

development和mechanism保留各自原有归档内部计时（5.133238888、35.388496837 CPU秒），不把该内部计时伪称为另行测得的完整子进程成本。各阶段存在包含关系，不能把pack/restore分项再加到包含它们的总时间上。

报告、图、审计代码与输入清单直接可读；大raw证据通过manifest指定的全部分片完整恢复。请保留manifest顺序和原始字节，使用恢复工具完成校验，不把只下载部分分片视作完整证据。
