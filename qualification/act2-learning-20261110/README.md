# ACT-2：受控 SQLite 技能选择研究负结果

本地实际运行已完成，两个学习候选均不晋级，继续保留固定 skill library。
这是新增的受控研究基准，不是原 Hepta workflow、FinalUse、Notes 产品入口或独立生产客户验收。
任务请求和故障是人工生成的；SQLite 事务、只读观察、效果和训练优化实际执行。

## 冻结范围与实际执行

共同开发基线为 `ae8a08059df73ccb875f4f541f76ad01080ba74b`。
实际受测文件由每次 receipt 和 frozen manifest 中的完整 SHA-256 绑定；
不能将本地文件运行称为对后续 Git commit 的整仓验收。

一次实验有 80 条训练轨迹、80 个确认任务、8 个独立模型初始化种子，
每个种子分别真实训练线性 head 与 12 单元 GRU，每次 220 步 Adam 优化，合计 16 fits。
所有候选在训练前冻结任务、特征、技能、预算、epoch、种子及判据，没有按确认结果选优。
每个确认任务执行五个标签 arm，共 3,200 次实际 episode；这些不是 3,200 个独立任务。
同一确认集重复匹配八个训练种子，固定对照没有八次独立训练。

五个标签为 reference workflow、手写 macro、flat primitive、无状态 head 和私有 GRU。
**B0 workflow 与 B2 flat 当前共用同一 primitive reference 实现**，属于冗余对照；
不得将它们描述为五种独立算法或原产品的三条独立执行路径。
五个 arm 使用相同 inspect/stage/apply/stop 能力、原始任务、故障、目的地设置及 primitive 预算。
macro/学习选项 ensure 内部仍计入实际 stage/apply 调用，不将一次选项调用冒充一个原语。
结束建议经过 fresh 只读目的地查询，模型本身不能签发 success。
模型输入是十个确定性运行状态特征，没有训练或验证 Hepta 的共享语义 encoder。

训练使用两种物理 SQL schema、两个数据库实例名和 1/2 个子目标；
确认使用另两种 schema、另两个实例名和 3/4 个子目标。这些集合互斥，
但统一 provider 将 schema/实例规范化，全部仍是 SQLite 同一任务家族。
每个 split 只有 10 个 length×fault 行为层，重复 payload 只更换目标内容；
80 个实际任务不等于 80 类独立机制，也不构成目的地家族外推。
本轮训练和固定对照确认分别只有 9 条不同的规范化 feature/action 轨迹；
这进一步限制了有效行为多样性。
故障含预先部分完成、预先 stage、丢回复及 apply 后读回中断。
当前确认 oracle 标签全部可用；UNKNOWN 与实际目标不完整分别记录，没有把 UNKNOWN 当训练终局标签。

## 实际结果（run2）

| 标签 arm | 实际完整目标 | success 声明 | UNKNOWN | 平均 primitive 调用 | 平均策略选择耗时 |
|---|---:|---:|---:|---:|---:|
| B0 reference workflow | 512/640 | 512 | 128 | 9.600 | 14.50 µs |
| B1 macro | 512/640 | 512 | 128 | 9.600 | 10.84 µs |
| B2 flat（与 B0 同实现） | 512/640 | 512 | 128 | 9.600 | 13.69 µs |
| B3 head | 512/640 | 512 | 128 | 9.600 | 89.68 µs |
| B4 GRU | 464/640 | 464 | 176 | 9.375 | 327.35 µs |

受测范围内所有 arm 的 false success 和 duplicate effect 均为零。
head 没有提高目标质量或减少工具调用，另增加训练与选择成本。
GRU 两个训练种子的完整目标为 40/80，其余六个为 64/80；
它较少的调用来自较早停止和质量下降，不能算效率提升。
八次 head 训练外层共约 0.265 s，八次 GRU 训练共约 1.650 s，
训练轨迹采集另约 0.089 s；完整 CPU、工具、独立 oracle、初始化、保管和墙钟记录保留。
私有 GRU 隐藏状态每个 episode 重置，96 bytes；没有建立其跨进程恢复资格。
人工策略设计及工程开发成本没有量化；本轮也没有开展匹配的调参研究，
因此不声称已完成现实全成本的最优策略比较。
这些时间来自单机受控运行，不能用于部署性能或能耗外推。
报告描述性配对结果，不给出将 episode 当独立训练重复的显著性声明。

## 原件与两次运行的关系

- `run1` 为首次实际运行；`pilot-source.zip` 保存其完整原源码，原 receipt 未改。
- `run2` 仅增加在线特征和所有实际 SQLite 数据库字节的保管。
  策略、优化器、任务、预算和判据没有改变，两个学习候选的负结果保留。
- `execution*-receipt.json` 记录真实命令、返回码、外层耗时、日志摘要与源码前后身份。
- `run2/FROZEN_MANIFEST.json` 在训练前写入；模型、完整逐步 loss 序列、训练/确认轨迹和文件摘要齐备。
- `run2/destination-databases.zip` 保存 80 个训练目的地和 3,200 个确认目的地的实际数据库字节，
  每个 trajectory 绑定 archive member 与完整数据库 SHA-256，可独立读回验证原目标和 effects。
- `optimizer-records.jsonl.gz` 是 220 步 loss 历史及最终权重摘要，**不是**全部梯度、Adam moments 或完整优化器状态。
- BPTT 额外完成 13 个参数块首坐标的有限差分检查，误差小于 `1.1e-11`；不是所有参数坐标的穷举证明。

本轮完成了实际训练和真实受控工具效果研究，避免继续将所有学习实验统称 NOT_RUN。
它没有关闭产品五条原控制路径、目的地家族外推、真实训练来源、完整生产授权、
独立 field evaluation 或 learned hierarchy 晋级 blocker。下一步产品研究仍需原 provider 接入与新的独立确认任务。

## 发布原件与复现

原 `run2/destination-databases.zip` 完整容器由 `run2/destination-databases.zip.xz` 无损保存。解压后 SHA-256 为 `b0ec17badc0595c18a876949f6bcfd07e42c37f825fb30c11ccdc79ec853d983`；全部 3,280 个原数据库字节及 ZIP 容器均未丢弃。其余原件逐个保存，各 blob 均小于仓库 512,000-byte 门禁，没有扩大上限。`run2/source-postimages.zip` 保留原 run2 的三份受测 Python 字节。

审阅器原字节保存在 `review/audit.py.txt`，仅后缀改变以免格式化改写原件。可运行 `python3 scripts/act2_learning/reproduce.py --repository .`：它在临时目录还原原 ZIP 和受测源码，只映射审计器两个本地路径，再重训、重放与查验。该打包复现已本地 exit 0；它是同数据的复核，不是新的独立确认集。

新 hosted CPU run 为同一冻结研究的再执行，结果必须另绑其实际 source SHA。官方 formatter 在实验之后运行，保留 patch/postimage；冻结源 ZIP 不参与格式化。本地文件身份结果不自动变为后续 Git commit 的整仓或生产验收。
