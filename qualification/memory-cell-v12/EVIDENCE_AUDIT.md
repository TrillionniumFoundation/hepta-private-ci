# V12 科学证据归档独立复核

## 结论与复核范围

本报告记录对四个已冻结证据包的**本地只读独立复核**。四个包通过完整性核对，未发现归档内容、冻结源码或本报告列出的主要结果数字之间的不一致。

复核没有重新训练或重跑科学实验，没有修改源码、原始证据或实验报告，也没有访问 GitHub、创建提交或修改分支。报告由复核结论整理保存；保存时没有追加新的验证。该结论证明本地冻结材料之间的一致性，不独立证明实验设计没有偏差，也不替代远端 Git 对象和提交的发布核验。

核对对象为 `evidence-packs/` 下的四个包，以及各自 `evidence/` 原目录：

- `network-categorical`
- `network-categorical-seed51047`
- `factorized`
- `typed`

对照报告为 [CONTENT_RESULTS.md](CONTENT_RESULTS.md)、[NETWORK_RESULTS.md](NETWORK_RESULTS.md) 和 [TYPED_RESULTS.md](TYPED_RESULTS.md)。CONTENT 的实验包已由其他流程处理，本轮只对照其基础语料身份及报告边界；本报告不将其列入以下四包计数。

## 1. 分片、归档和原始成员

复核重新调用 `evidence_pack.load_package`，检查每个分片的名称、顺序、长度和 SHA-256，拼接后检查完整归档的长度和 SHA-256，再检查 tar.xz 的全部成员。随后另行逐一比较归档 manifest 与原始目录，确认文件集合、每个文件的长度和 SHA-256 相同。没有为复核解包出新的大副本。

| 包 | 原始成员数 | 原始 bytes | tar.xz bytes | 400,000-byte 分片数 |
|---|---:|---:|---:|---:|
| `network-categorical` | 208 | 51,791,233 | 22,746,996 | 57 |
| `network-categorical-seed51047` | 98 | 24,797,065 | 10,373,548 | 26 |
| `factorized` | 147 | 32,799,922 | 7,719,616 | 20 |
| `typed` | 153 | 22,144,707 | 7,470,272 | 19 |
| **合计** | **606** | **131,532,927** | **48,310,432** | **122** |

另有四份 manifest，四包共计 **126 个发布文件**。最后一个分片可以小于 400,000 bytes。表中的原始 bytes 是完整冻结目录的文件总量；它可能包含运行汇总、事后分析及归档所需源码。因此不能将它与某个运行收据中的“写入 summary 前字节数”误当作相同口径。

完整归档 SHA-256：

| 包 | SHA-256 |
|---|---|
| `network-categorical` | `2f5f62f8ce81f581b40aa99cfbadac81fc763da7fbc58d5d404e20ba56a2a080` |
| `network-categorical-seed51047` | `226e6b4bb8257d40ea421eee0bd67cce176fdfa4d08373af5e867ff7b842dba6` |
| `factorized` | `23086a5e8e2d93a09c2b7d298ae81ca1ef0cd3af94512584495c39d2b231b569` |
| `typed` | `c3b02b89847b414dd2f7c364bd12e0324d34a60c6fcbd42ee4baac8b5232b481` |

三个 network 系列包的全部文件路径、长度和 SHA-256，还分别与独立的 [NETWORK_ARCHIVE_INVENTORY.json](NETWORK_ARCHIVE_INVENTORY.json) 完全一致。

压缩后的包体是研究证据归档，不是一个部署 cell 的模型表示；以上压缩率不能用来宣称参数记忆的压缩收益或全生命周期成本优势。

## 2. 冻结源码与来源身份

四组 `FREEZE.json` 的 **30 项源码摘要**全部对应各自归档内的 `EXECUTED_SOURCE` 文件：两个 categorical attempt 各 7 项，factorized 7 项，typed 9 项。两组 categorical attempt 的七项源码摘要完全相同，协议差异仅为 seed 选择，与报告一致。

categorical 的原始 `network.py` 和 `network_experiment.py` 与后来修复后的顶层文件不同。原实验执行版本正确保留在其 `EXECUTED_SOURCE`，报告明确解释了后续修复。这是有意保留的版本差异，没有用当前源码替换旧实验身份。复跑旧实验应使用对应的冻结版本；不能给旧实验补记后来源码才实现的保证。

typed 的 `ANALYSIS.json` 所引用的 `SUMMARY.json` 文件摘要与实际文件一致，其 `analysis_source_sha256` 也与复核时的 `typed_analysis.py` 一致。后处理源码和结果身份不能被误认为训练前的独立预注册。

CONTENT 与 network 系列使用相同基础 corpus 身份：

`cbad82b9e82da96a26e3f8382a68816367a43c1d5827d35afa53494c6c3cadc1`

typed 增补真实文档前言与 identity 段后，使用独立的 640 条来源 profile，其 corpus 身份为：

`ea519ba0a0d3e1973409e862f205f3e7c943e7d1370d3d1ead667369c7c4f82a`

报告区分了这两个 profile，没有将 typed 的 640 条来源与 network 的 600 条来源合并为同一任务集。

## 3. Categorical 中断与补跑

原 `network-categorical` attempt 的 [中断凭据](evidence/network-categorical/INTERRUPTION.json)记录 **7/9 阶段完成**、退出码 **130**、共享磁盘可用空间为 0，以及没有保存整次运行 wall/CPU footer。归档保留中断前的全部文件，没有删除第三 seed 的已完成前缀。

原 attempt 保存的训练成本下界为 **330,240 次 presentations、5.700260562 fit wall seconds**。由于可能存在尚未记录的在途工作，这些数字不能充当完整运行成本。

[NETWORK_CATEGORICAL_COMBINED.json](evidence/NETWORK_CATEGORICAL_COMBINED.json)选用的九个完整阶段，其每个结果文件 SHA-256 均已独立核对。第三 seed 在新目录的完整补跑没有覆盖原 attempt；重复 phase 0 不计为新独立试验，重复工作仍需计入成本。

两次 attempt 已记录的训练成本合计下界为 **483,840 次 presentations、8.557472298 fit wall seconds**，与 `NETWORK_RESULTS.md` 一致。中断 attempt 的完整端到端 wall/CPU 总量仍未知，不能因补跑成功而补写或忽略这一缺口。

报告保留了重复 phase 0 的神经参数、Adam 状态与神经 trace 逐位相同，以及 BM25 浮点累计的细微差异。复核确认组合凭据和冻结材料的身份一致；本轮没有重新执行补跑来制造第二份重复实验。

## 4. Factorized 报告数字

复核重新读取九个 phase/seed 单元，四种方法的 known accepted-correct 和 unknown rejection 数字逐格与 `NETWORK_RESULTS.md` 表格一致。

同时核对每格 `top2` 与 `top1_twice` 的以下字段：接受正确率、未知拒绝率、raw top-2、实际来源读取次数和来源字节。它们逐格相同，且 `equal_budget_read_plans_equal` 全部成立。

该结果支持相同冻结分数、相同最多两读预算下的执行一致性。第二次读取并没有基于第一次文本重新规划，因此不能解释为自适应推理收益。相同最大预算也不意味着各方法的实际读取次数相同。

[执行收据](evidence/factorized/EXECUTION_RECEIPT.json)的 **9 个完成阶段、69.2501784 秒 wall、54.6697575 秒 CPU、91,736 KiB peak RSS** 与报告一致。收据记录的 `retained_bytes_before_receipt` 为 32,798,059 bytes；本轮完整包的 32,799,922 bytes 还包含收据及后处理文件，口径不同。

[语言形态事后核查](evidence/factorized/NORMALIZED_QUERY_AUDIT.json)记录 phase 1/2 各 403 个 known 请求，在移去公开 module 名称后，403/403 都与过去已知问题形态相同。历史 nearest 的满分不能解释为陌生语言泛化；报告保留了这一限制。

## 5. Typed：从逐题 trace 重新累计

复核直接读取三个 seed、未来 phase 1/2 的八个 arm 的逐题 trace，按 `query_id` 对齐，重新累计正确数、可回答和不可回答数、输出完全相同数及双方独占正确数，没有只引用 `ANALYSIS.json` 的汇总。

| 方法 | 正确 / 总评估 | 与完整系统逐题输出相同 | 完整系统独占正确 / 对照独占正确 |
|---|---:|---:|---:|
| 完整类型 | 582/618 | 618 | 0/0 |
| 去掉 event | 582/618 | 618 | 0/0 |
| 去掉 semantic | 582/618 | 618 | 0/0 |
| 去掉 procedure | 582/618 | 618 | 0/0 |
| 去掉 meta | 582/618 | 582 | 18/18 |
| BM25 generic | 582/618 | 582 | 18/18 |
| History generic | 546/618 | 574 | 40/4 |
| Single generic | 347/618 | 383 | 235/0 |

完整类型和 BM25 generic 都为 **372/408 可回答任务正确、210/210 不可回答任务正确拒绝**。History generic 为 336/408 可回答正确，Single generic 为 137/408；二者也都正确拒绝 210/210 不可回答任务。

这些逐题重新累计的结果、配对差异和输出一致性，与 `TYPED_RESULTS.md` 及 [ANALYSIS.json](evidence/typed/ANALYSIS.json) 完全一致。三个内容类型消融的零损失不能解释为没有执行任务：报告描述的是强通用替代实际完成同样的事件重放、声明解析和有界程序执行。

**618 次评估来自同一组 206 个未来任务的三个 seed，不能当作 618 个独立任务。** 数据、模块、语言模板和程序块高度相关。该证据没有独立样本显著性保证，也没有证明四类型读取优于强检索加通用 reader。

## 6. 发布与证明边界

本地四包复核完成时，执行本次复核的代理此前两次 create-blob 尝试均未得到成功返回，分别在异常等待后被中断。因此其当时记录的 **0 个确认成功上传**是透明的状态记录；不能据此断言服务器没有创建同内容但尚未挂树的对象。

根代理随后接管全部 126 个 blob 的上传与挂树，本次本地复核没有继续调用 GitHub，也没有覆盖根代理的上传 checkpoint。远端对象是否存在、分支是否完整引用，以及最终提交身份，应以根代理的上传清单和提交核验为准。

本报告证明四包与本地冻结材料一致，并复核了上述报告数字。它不把以下事项提升为已经取得的科学结论：参数化正文压缩优势、全系统净收益、候选分裂净收益、陌生语言泛化、三个 seed 构成三个独立数据集、原生四类型模型部署，或通用 memory system 的自发形成。
