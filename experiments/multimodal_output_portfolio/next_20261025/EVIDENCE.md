# 完整证据索引

本轮八份新归档均已封存，并在封存后逐成员重新读取、核对大小与 SHA-256。建立此索引时又核对了八个完整压缩文件的 SHA。总计 **1,159,644,739 字节**，含 manifest 共 **319,660 个成员**。原始字节、失败和实际成本保留在相应档案中。

| 范围 | 压缩文件 | 字节数 | 成员数，含 manifest | 封存回执 |
|---|---|---:|---:|---|
| sources | `hepta-ndu-next-sources-20261026.tar.gz` | 63,637,614 | 26 | [JSON](SOURCE_EVIDENCE_ARCHIVE.json) |
| control | `hepta-ndu-next-control-20261026.tar.gz` | 58,153,451 | 227 | [JSON](control/EVIDENCE_ARCHIVE.json) |
| action_value | `hepta-ndu-next-action-value-20261026.tar.gz` | 54,586,274 | 262 | [JSON](action_value/EVIDENCE_ARCHIVE.json) |
| native_h1 | `hepta-ndu-next-native-h1-20261026.tar.gz` | 25,505,892 | 36,961 | [JSON](native/EVIDENCE_ARCHIVE.json) |
| native_h2 | `hepta-ndu-next-native-h2-20261026.tar.gz` | 62,575,673 | 266,617 | [JSON](native_h2/EVIDENCE_ARCHIVE.json) |
| media_asr_assets | `hepta-ndu-next-media-asr-assets-20261026.tar.gz` | 581,564,397 | 16 | [JSON](media/ASR_ASSET_RECEIPT.json) |
| media | `hepta-ndu-next-media-runs-20261026.tar.gz` | 209,567,455 | 11,381 | [JSON](media/EVIDENCE_RECEIPT.json) |
| joint | `hepta-ndu-next-joint-20261026.tar.gz` | 104,053,983 | 4,170 | [JSON](joint/EVIDENCE_ARCHIVE.json) |

[EVIDENCE.json](EVIDENCE.json) 保存每份完整 archive/manifest SHA、原绝对路径、回执身份和本次复核结果。各回执列明完整内容与外部输入范围；大共享模型、旧输入和已封存的 ASR 资产可通过另一份完整归档引用。操作系统、系统 codec 和完整工具链镜像不在这八份归档中，不能把研究数据完整性解释成已交付一个便携生产容器。

## 来源、版本和失败的保留

各研究自己的冻结协议、精确执行快照、独立审计和过程回执构成判断依据。H1 校准有明确登记的历史源码映射；媒体依赖连续性有封存前后的准确补充记录；它们不被改写成从一开始就完全相同的单一版本。全部原质量门与失败仍保留。

H1 的完整档案随后用于逐字节核验并回收重复展开副本，[回收回执](evidence/H1_EXPANSION_RECLAIM.json) 与原完整 journal 也已纳入 joint 档案。封存回执中的 `original_files_retained` 指封存时事实，不是对展开缓存永久留存的承诺。媒体档案保全所有 4,460 个本轮必要录音；未分配公共音频缓存的零字节占位不属于可用来源。

## 交付边界

源码、报告、紧凑审计和这些归档身份提交到同一私有研究分支。完整原始归档保留在实际工作区；此前将内部原始证据上传到另一目的地的自动审批拒绝仍有效，本轮没有上传或绕行。正式模型不获生产替换资格，原授权保持 `deny_all`。

具体科学结论见 [README.md](README.md) 和 [STATUS.json](STATUS.json)。证据完整与质量门通过是分别记录的结论。
