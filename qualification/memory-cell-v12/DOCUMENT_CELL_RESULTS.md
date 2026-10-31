# V12：真实文档字段 cell 的持久化、纠错与恢复结果

## 结论与范围

修订后的 document cell 完成了从真实来源字段、实际权重训练、不可变产物、事务发布，到更正、续训、崩溃恢复与撤销拒答的完整路径。V2 实际运行得到 **60/60 个正确回答、31/31 项检查通过、4 次真实 SIGKILL**。独立补充的四项生命周期回归也全部通过。

这里的成功范围很明确：显式规则解析公开 module 地址和三字段操作，再将问题转换为一个 canonical 输入，由小型 MLP 输出文档声明的 owner、deputy、lifecycle。**60/60 不是模型理解了 60 种陌生语义，而是 10 个 canonical 地址输入 × 3 种规则接受的措辞 × 2 个来源状态。** 本轮证明受约束内容映射能够接入可恢复的版本发布流程，没有建立压缩优势、开放语言理解或参数遗忘保证。

主要复核入口是 [V2 归档清单](evidence-packs/document-cell-v2/manifest.json)。下文的 `evidence/document-cell-v2/` 原始路径在恢复归档后可访问；旧版及失败 attempt 也独立保存，具体命令见第 8 节。

## 1．真实来源、任务和模型输入

[冻结计划](evidence/document-cell-v2/PLAN.json)使用固定 Git 提交 `527218f9b823540830907f861a309310b71d38c9` 的真实 `docs/modules/*/TECHNICAL.md`，按公开 module 名称排序选前 10 个。完整 corpus 身份为：

`cbad82b9e82da96a26e3f8382a68816367a43c1d5827d35afa53494c6c3cadc1`

这 10 个模块是 `auth.authbus`、`automation.taskflow`、`browser.servo`、`channel.matrix`、`cognitive.read`、`cognitive.store`、`cognitive.types`、`compact.engine`、`context.compiler`、`control.engineering`。另摄取第 11 个 `control.runtime`，专门验证不相关来源更新不会使当前 cell 失效。原始 10 份文档的 UTF-8 正文字节共 234,028 B，但模型任务只包含其中三个短字段，不能把全文体积当作其有效知识压缩分母。

字段值由真实正文中的声明提取。此子集的共享词表含 **7 种 owner、5 种 deputy、2 种 lifecycle**，按 5+4+1 个 bit 编码。词表存储允许的字符串，不包含 module 到三字段答案的映射。文档字段及 lifecycle 是来源声明，不代表本实验已核实对应功能的生产部署状态。

[执行协议](evidence/document-cell-v2/EXECUTED_SOURCE/DOCUMENT_CELL_PROTOCOL.json)为每个 module 只训练一个 canonical 问题：

```text
State the owner, deputy, and lifecycle of MODULE.
```

读路径先使用公开地址与操作 parser；只有唯一识别到一个允许的 module，且同时出现三类操作词时，才进入模型。parser 接受 owner/responsible/accountable、deputy/alternate/backup、lifecycle/implementation status 等显式词汇。之后模型看到的是上述 canonical 文本，而不是原始改写。该 parser 不读取目标值，但承担了地址识别、操作范围和部分未知请求拒绝的能力。

因此，保存的完整查询文本虽然有不同措辞，神经模型并未直接处理这些陌生完整措辞。有关未经 canonical 化的内容访问表现，见独立的 [WP2 内容实验报告](CONTENT_RESULTS.md)，不能用本轮 60/60 覆盖其中的失败。

## 2．真实权重和 Adam 续训

模型采用固定 lexical hash 特征，结构为 **128 → 32 → 10，ReLU**。四组 trainable tensors 均参与梯度更新；它是重新训练的小型 MLP，没有预训练语言模型。权重规模为：

| Tensor | 元素数 | FP32 bytes |
|---|---:|---:|
| hidden.weight | 4,096 | 16,384 |
| hidden.bias | 32 | 128 |
| head.weight | 320 | 1,280 |
| head.bias | 10 | 40 |
| 合计 | **4,458** | **17,832** |

Adam 的一阶、二阶 moments 合计另占 **35,664 B**，step 与序列化元数据另外保存。[实际训练 receipts](evidence/document-cell-v2/RESULTS.json)记录了各组梯度和参数改变量，初训与续训的四组参数均真实改变。

| 训练 | Seed | Adam 起止 step | 样本呈现 | Canonical 重建 | 最小绝对 logit |
|---|---:|---|---:|---:|---:|
| 初始来源 | 17041 | 0 → 600 | 19,200 | 10/10 | 5.44550 |
| 来源更正后 | 17042 | 600 → 1,200 | 19,200 | 10/10 | 6.48441 |

两次都使用 batch size 32、600 steps。独立 f64 evaluator 检查 canonical 输出及预设最小绝对 logit 1.0；publication 又在事务中针对当前真实来源重新执行重建检查。训练后的阈值不是通过 60 条结果选择的。

初始 serving 参数 SHA-256 为：

`2266fdd521de87fe5a2ef6439f7eff5ea75b3b6fddf5e3b83bd03d55e02db390`

续训 receipt 的 `initial_parameter_sha256` 与此精确相同，`initial_optimizer_step` 为 600；更正后参数 SHA-256 为：

`8173aec7f91d7314c63dc1fea8cfa6b0112202d8a414af037269072e372a907a`

这验证了真实参数及 Adam 延续，不能被“重训了一个相同接口的新对象”替代。更正发生在同一 module 集合、同一 codebook 下；module 集合或 codebook 改变时，V2 改为 clean fit，见第 5 节。

## 3．60 个回答与 20 次范围拒答的含义

[逐请求证据](evidence/document-cell-v2/PREDICTIONS.json)保留原文、解码字段、logits、epoch、artifact、参数身份和来源 cut 身份。每条记录明确注明 `explicit-public-scope-parser-plus-canonical-model-input`。

初始状态下，10 个模块各用三种完整措辞读取，共 30 次；受控来源更正、续训、第二次发布后，用相同三种措辞读取同一 10 个模块，再得到 30 次正确结果。更正后九个未更正模块也全部保持正确。它们不是 60 个独立事实、60 个独立语言任务，也不是新的独立数据集。

20 次范围外检查全部拒绝，其构成为：

| 范围外检查 | 实际次数 | 重复性和提供拒绝的机制 |
|---|---:|---|
| 已知 module 的 owner 私人电话号码请求 | 10 | 同一模板替换 10 个 module；不满足完整三字段操作规则。 |
| `an.unwritten.module` 的完整三字段请求 | 10 | 同一个完整问题重复 10 次；module 不在公开支持集合。 |

这些拒绝来自显式 scope parser，不能算成模型学会了未知事实、开放意图检测或 20 种独立 OOD 模式。关键字规则也没有被本实验验证为任意否定、歧义、混合请求的语义解析器。

读路径没有按 module 查找正确字段值，也不先取原文再解析答案。它从 SQLite 检查每个拟合依赖的版本、active 状态和正文摘要，随后从实际模型参数和共享词表生成字段。原文提取用于摄取、训练与 publication 重建；将来源版本检查与答案查表区分开，是这个实验成立的必要边界。

## 4．V2 的发布、失效与四次真实崩溃

[完整结果](evidence/document-cell-v2/RESULTS.json)中的 31 项检查包括上述 20 次范围拒答和 11 项生命周期检查。四次崩溃发生在独立子进程中，全部实际收到 SIGKILL，退出码均为 -9；不是用抛异常模拟。

| 崩溃位置 | 实际验证的状态 |
|---|---|
| Staging 原子 rename 前 | 私有暂存文件可以保留；还没有发布权威。相同 candidate 可重新 stage。 |
| Staging 原子 rename 后 | 完整 immutable artifact 已存在；丢失返回确认后，重试验证其清单并返回同一身份。 |
| Publication SQLite commit 前 | 事务回滚，epoch 仍为 1。相关来源已经更正，因此旧模型继续拒答。 |
| Publication commit 后、确认前 | 重开后 epoch 为 2；新字段与另外九个模块均正确。 |

其他真实执行的路径如下：

- 只 stage 文件但未发布时，读取拒绝；文件存在本身不构成发布。
- 关闭后重开 owner，答案和完整 optimizer 仍一致。
- 更新 `control.runtime` 时，当前 cell 的参数身份和回答保持不变。
- 受控更正 `cognitive.read` 的 owner 为已有词表值 `automation-platform`，先使相关旧模型的全部读取及旧 candidate 发布失效，再以真实 Adam 续训恢复服务。这是实验构造的来源编辑，不是声称仓库发生了该历史事件。
- 损坏已保存 serving 文件一个 byte 后，artifact 校验拒绝释放回答。
- 将未被当前查询直接访问的拟合依赖 `automation.taskflow` 撤销，整个依赖该 cut 的 cell 拒答，旧 checkpoint 也不能重新发布。

`read` 使用同一个 SQLite `BEGIN IMMEDIATE` 事务完成发布选择、完整依赖新鲜度检查和结果生成；来源写入不能在该检查与事务完成之间提交。保证的时间点是这次事务完成，不意味着后来撤销可以收回已经返回给外部的答案。

归档中的 owner 数据库最终停在撤销后的状态。恢复它后直接读取当前 cell 会按预期拒绝；这不是归档恢复失败。要重做完整生命周期，应在新输出目录重跑冻结的 experiment。

## 5．初始 SQL 失败、V1 成功及独立审查修复

### 首次 attempt：初始化失败，未训练模型

[首次失败凭据](evidence/document-cell-attempt1/FAILURE.json)记录第一条来源 INSERT 的 SQL placeholder 错误：表有 6 列，语句提供了 7 个值。进程退出 1，失败发生在任何模型训练之前。工具观察到的 wall 为 0.107708255 s；该失败未独立记录 CPU，不为它补造完整计时。

原 SQL、冻结计划、数据库和失败凭据保留在 [attempt1 归档](evidence-packs/document-cell-attempt1/manifest.json)。之后修正为 6 个 placeholder，未覆盖旧源码。

### V1：已跑通的路径没有覆盖全部恢复边界

[V1 结果](evidence/document-cell-v1/RESULTS.json)曾得到 60/60、29 项检查、2 次 publication SIGKILL。独立代码审查随后发现两个未被该成功 run 覆盖的问题：

1. **Staging 不能安全重试。** V1 直接创建最终 digest 目录并逐个写文件，且 `exist_ok=False`。中途崩溃可能留下不完整最终目录；即使已经完整成功，仅丢失返回确认也会让相同候选重试遇到已存在目录。V2 在私有暂存目录写入、fsync，再原子 rename；最终目录已存在时必须完整验证 inventory 才复用。损坏目录不会被静默覆盖。
2. **Scope 收缩可暗中继承旧参数与 optimizer。** V1 只比较 codebook 就允许继续训练。如果去掉的 module 没有改变全局词表，子候选会继承父参数，却仅声明收缩后的来源 cut。V2 要求 codebook 和完整 module 集合均相同才继承 Adam；否则从 clean base 重建，避免把缩小输出范围伪装成独立训练来源。

[V1 原始实现](evidence/document-cell-v1/EXECUTED_SOURCE/document_cell.py)保持原样，其 SHA-256 为 `cdcd8fa282ad0ff29064d89e0dbc42b37a925cc1c6a05cd82b40435d65400630`。V2 实际执行实现的 SHA-256 为 `8d720b2b20f6de3b4f798a89d9a45c6537c592e77d6e4e13d509306e59011248`。V2 六项冻结 source 文件均与 `PLAN.json`/`RESULTS.json` 的摘要一致。

修复后在独立 V2 目录重跑，新增 staging 两个边界的真实 SIGKILL。没有把修后源码或新增保证写回 V1 的旧证据。`document-cell` 与 `document-cell-v1` 曾存在逐文件完全相同的本地副本；它们代表同一次 V1 run，只归档并计入一次，不增加样本数或训练成本。

### 四项独立行为回归

[document_cell_tests.py](document_cell_tests.py)在明确标为功能 fixture 的合法文档字段上执行真实训练、SQLite 和 artifact I/O，四项全部通过，unittest 本次报告用时 2.311 s：

| 回归 | 断言的实际行为 |
|---|---|
| 相同 candidate 幂等 stage | 包括关闭后重开，artifact 身份、文件 bytes 与 mtime 均不变；仍可发布并读出字段。 |
| 同名损坏拒绝 | `stage` 与 `publish` 均拒绝；重试不修补或覆盖损坏 bytes。 |
| 同 codebook 的 scope 收缩 | 2→1 module 后初始 Adam step 为 0；参数与完整 optimizer 均等于相同 seed 的独立 clean fit。 |
| 伪造 fresh cut | 给旧权重换上当前 cut，使声明新鲜度及完整性通过；publication 仍按真实当前来源重建拒绝，原 release artifact/epoch 不变。 |

最后一项尤其说明：不能仅靠候选自己声称“来源已更新”就发布旧答案。检查真正落在当前来源与权重输出的一致性上。这四项不是新增语义效能试验，也不增加 60 个查询的统计样本量。

## 6．实际字节与运行成本

### 单模型与可恢复 artifact

| 层次 | 初始版本 | 更正版本 |
|---|---:|---:|
| 原始 FP32 权重 | 17,832 B | 17,832 B |
| 原始 Adam moments | 35,664 B | 35,664 B |
| serving.json | 39,083 B | 39,096 B |
| checkpoint.json，含参数与 Adam | 108,730 B | 108,744 B |
| training.json | 1,321 B | 1,333 B |
| manifest.json | 326 B | 326 B |
| 实际完整 artifact | **149,460 B** | **149,499 B** |

更正版本 serving.json 内部包含 model、182 B 的 module 列表、296 B 的 codebook、1,252 B 的来源 cut，以及 schema/margin 等字段；这些组件是 serving.json 的组成部分，不能再重复加到总计。checkpoint 同时保存参数与 moments，原始权重和 Adam 字节也不能再加一次。当前实现的 `load` 每次校验完整 artifact，包括 checkpoint；不能把实际读取成本描述为仅有 17,832 B 的权重或 39,096 B 的 serving 文件。

### V2 完整证据和来源历史

[归档清单](evidence-packs/document-cell-v2/manifest.json)含 37 个原始文件，共 **1,873,841 B**，逐文件字节可分为：

| 证据层 | 实际 bytes |
|---|---:|
| 主 owner SQLite，含来源历史、provenance 和 release | 364,544 |
| 两个完整 immutable model artifacts | 298,959 |
| 真实 staging 中断留下的暂存产物 | 149,460 |
| 独立损坏测试副本，含其数据库和 artifacts | 772,003 |
| 六份 EXECUTED_SOURCE | 69,466 |
| 计划、逐题预测、结果、inventory 与 pending candidate | 219,409 |
| 合计 | **1,873,841** |

主 SQLite 保留 11 个来源地址的 14 个版本，正文 UTF-8 bytes 合计 336,308 B；它们已经包含在 364,544 B 的数据库中。数据库还保存原始来源、受控更正、无关更新和撤销记录，不能当作参数化记忆的免费外部存储。

这张表是该研究证据的完整文件账，不是隔离测量的部署总 RSS。Python、NumPy、标准库、SQLite 实现、动态库与操作系统属于共享运行依赖，本轮没有逐 cell 完整分摊，也没有独立峰值 RSS 测量。包体压缩、重复证据和测试副本均单列，不用它们推导运行时压缩比。

### 已记录的执行成本

| Attempt | 结果 | 内部 wall | Parent + child CPU | 真实训练呈现 |
|---|---|---:|---:|---:|
| 首次 SQL 失败 | 初始化退出 1 | 工具观察 0.107708 s，口径不同 | 未记录 | 0 |
| V1 | 60/60，29 checks，2 SIGKILL | 0.983411 s | 1.155171 s | 38,400 |
| V2 | 60/60，31 checks，4 SIGKILL | 1.879312 s | 2.032806 s | 38,400 |

V2 parent CPU 为 0.467259 s，子进程 CPU 为 1.565545 s；两次模型 fit 合计 0.387621 wall s、0.167008 CPU s。四次 SIGKILL 子进程的已运行 CPU 计入 V2 总量。两个完整 run 共 76,800 次训练呈现、3.187977 CPU s；首次失败 CPU 未记录，独立行为回归及其他开发时间不包含在这两个 run 的 receipt 中，因此这不是整个实现工作的无缺口总成本。

计时来自共享 host 的短运行，不能据此宣称稳定的生产延迟或吞吐优势。读路径包含事务、完整 artifact 校验和参数解码；本轮没有与同服务能力 registry 做匹配的端到端性能比赛。

## 7．没有由这些结果证明的能力

本实验输出三个有限词表字段，并保留原文、来源历史、codebook、地址、训练 checkpoint 和恢复证据。它未证明相对精确 registry 的压缩优势，更不能用全文大小除以模型参数来宣称通用内容压缩。独立 WP2 实验中精确字段 registry 已是强控制，本轮未推翻该结果。

它也未证明开放语义访问：陌生措辞由规则映射到 canonical 输入，未知请求由范围规则拒绝。多类型协作、长期事件关联、任意数值与长文本恢复、自动 split/merge 或通用 meta network 不属于这个 10 地址服务的验收内容。

版本更正和撤销保证的是当前服务输出与来源状态的关系。续训后的参数仍有历史学习过程；本轮没有证明旧信息从全部权重、Adam 或保留 checkpoint 中消失，不能写成机器遗忘。旧产物受到版本门控而不能重新发布，和物理删除所有历史副本是不同的验收条件。

持久化验证限定为一个受信任的本地 SQLite owner、真实进程 SIGKILL、文件完整性检查及冻结来源重建。它没有验证分布式共识、跨节点并发发布、恶意管理员回滚或整机断电语义。该范围与协议一致。

## 8．归档、恢复与复现入口

三个 attempt 独立打包，旧源和失败证据不被新结果替换：

| 归档入口 | 原始文件 | 原始 bytes | 压缩 parts bytes | Parts + manifest bytes |
|---|---:|---:|---:|---:|
| [document-cell-attempt1](evidence-packs/document-cell-attempt1/manifest.json) | 9 | 90,582 | 18,488 | 20,106 |
| [document-cell-v1](evidence-packs/document-cell-v1/manifest.json) | 28 | 1,421,440 | 126,172 | 131,331 |
| [document-cell-v2](evidence-packs/document-cell-v2/manifest.json) | 37 | 1,873,841 | 128,572 | 135,070 |

V2 压缩 archive SHA-256 为 `de269fdfd3c3a5e6412735fbb95399f351290e89309e8b1fb0510e6a2198cea7`。压缩 parts 是无损的证据传输容器，不能替代前述模型、来源或执行成本。

从仓库根目录恢复 V2；输出目录必须不存在：

```bash
python3 qualification/memory-cell-v12/evidence_pack.py restore \
  --pack qualification/memory-cell-v12/evidence-packs/document-cell-v2 \
  --out qualification/memory-cell-v12/evidence/document-cell-v2
```

`evidence_pack.py`先校验 parts、整体 archive、每个原始成员的路径/长度/SHA-256，再写入新目录。将 label 分别替换为 `document-cell-v1` 或 `document-cell-attempt1`，即可恢复相应旧 raw 路径。已经存在的 raw 目录不会被覆盖。

恢复后使用 V2 自己的冻结源码，在新目录重做实验：

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
python3 qualification/memory-cell-v12/evidence/document-cell-v2/EXECUTED_SOURCE/document_cell_experiment.py \
  --repo "$PWD" --out /tmp/hepta-memory-v12-document-cell-reproduction
```

独立生命周期回归可从仓库根目录执行：

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=qualification/memory-cell-v12 \
python3 -m unittest -v document_cell_tests
```

包含计时的 training receipts、artifact 身份和归档哈希可能随重跑改变。复现应保留新 attempt 的全部结果，不覆盖旧预测或把后续修复追记成旧 run 已有的保证。
