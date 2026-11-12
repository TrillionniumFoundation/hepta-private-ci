# 固定 a96 原生审计材料的精确恢复

本目录保全原生审计输出的恢复过程、依赖和完整重组索引。原执行身份是 `a96-canonical-independent-validation-v1`，原 `ROOT_REVIEW.json` Git blob 为 `d7c135961dfacc04fe8b69697a66450e65566acb`。它记录 2026-11-12 16:33:35.443467 至 16:33:48.419914 UTC 的证据审计，395 个提供对象、16,082 个精确前置对象和七个固定提交的快照闭合检查。

**这批材料通过已核输入重建原字节，再同时匹配原长度、SHA-256 和 Git blob SHA。没有重新执行该原生任务，也没有新增 H 读取。** 这次恢复不改变任何 source-closure、caller、Rust、普通 A/B/C 或 Root 资格结论。所有新包装记录的 `qualification` 均为 false；原 JSON 的状态保留原样。

## 输出与身份

| 原输出 | 原 raw 字节数 | 原 gzip 字节数 | 已有编码分片 |
| --- | ---: | ---: | ---: |
| SNAPSHOT_LEAVES.json | 32,945,102 | 10,388,682 | 40 |
| OBJECT_AUDIT.json | 5,086,531 | 1,916,374 | 8 |
| TREE_AND_ANCHOR_RAW.json | 1,987,695 | 920,740 | 4 |
| CANONICAL_COMMITS_AND_DIFFS.json | 121,293 | 不压缩 | 本目录保留完整小原件 |

三组 raw/gzip 的完整 SHA-256、Git SHA、52 个分片的有序身份、偏移和每段解码摘要都在 [RECOVERY_MANIFEST.json](RECOVERY_MANIFEST.json)。52 个原 base64 分片已经由 Root 创建并全文 GitHub 读回，本次只读本地副本核验并引用；它们不计入本目录新保全的小文件数。大型派生 map、树体集合和 blob metadata 集合未再次上传。

原生审计检查的是固定快照的 Git 对象闭合。原记录中的 `source_git_state` 检查 HEAD/index/refs，明确没有逐个读取工作树文件；它也没有执行全历史 fsck，先前 fsck exit 3 的限制仍保留。恢复不增加对完整历史、当前工作树、运行时权限或实际模型采用的保证。

## 精确输入和重建过程

1. 复用已经保全的 c0f 原完整物理源码 inventory：5,474,911 B，SHA-256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57`，Git blob `5ed18452e2e967281ac368f934b9e4358627b9d3`。其 14,851 个文件均在原记录中匹配 index 且稳定。原五个 gzip 二进制分片及重组证明见 manifest 的 `dependencies.c0f_original_inventory`；没有重扫当前文件系统来替代这份原件。
2. 使用固定 b298→c0f GitHub compare 的 41 条变动（32 修改、9 新增），以及 32 个固定旧 blob 的完整字节元数据，逆向恢复 14,842 条 b298 叶图。两个输入文件及原 compare 原样保全在 `inputs/`。32 个 blob 的 SHA/长度/SHA-256 已经由 Root 实际读取验证；恢复脚本只使用这些已固定身份。
3. 读取原 395-object packet：308 blobs、80 trees、7 commits，12,080,171 B JSON，SHA-256 `bcecb58bbaf97b6fbd83bb9f9bee9829c902d8c721b52f19aac2160a0a2b8af0`。每个对象按其原类型、长度及 Git 原始对象头重算 SHA；逐提交按真实 before/after 变动投影，保留所有其他路径。
4. 原恢复脚本逐一重算下列九个 Merkle 根。九张完整叶图用原排序和 JSON 编码生成，必须匹配原 SNAPSHOT raw 身份。派生的 1,867 个唯一树体用于后续对象审计。
5. b298、c0f 两个原 commit body 使用已固定 GitHub 元数据重构，保留真实 `-0500` 时区、父序和消息末尾。只在原 commit Git SHA 完全相等时接受；两个原 API 元数据、精确 commit body 及重构说明均在 `inputs/`。这里没有制造替代历史。
6. 第二个恢复脚本按原序列化规则重建 OBJECT、TREE 和七提交 canonical diff。原对象集合为 16,136 个既存对象；所需前置集合恰为 16,082，全部 395 提供对象可达。三组 raw 身份、三组确定性 gzip 身份以及 canonical diff 身份均必须匹配原 d7c 登记。gzip 的 OS 头字节只按原完整身份选择；不以“可解压”替代原字节一致。

| 快照 commit | Merkle tree | 叶条目数 |
| --- | --- | ---: |
| `b29869e856d08db1bfb066116a9c443376ccc57d` | `906546af39b07474f0b9d046a6e780b6d3342743` | 14,842 |
| `c0f78493f815780f68b9bf5e390a21314d79311f` | `313ee34febc8ccc54c611ab56286e289518c63cb` | 14,851 |
| `f526387acd44bd04b2df3c3957d85797bbb6501e` | `8ffddb3ba6bcce849433d6da86473638a9978f46` | 14,842 |
| `cc22a69972d029d3ef28d49096f396eb5214c616` | `827fb70ed75d30c48d4693cbd0d23ea04f5744da` | 14,842 |
| `521283379701cca53987cf5c3fe85b85fdda04e6` | `778a2c1c1f77fd1ea3d3cd0c203cef6c38db2ec0` | 14,842 |
| `639f894e088cdc5b30b65ed3732dcaa0a2fbe004` | `c5eb8391c55b6a13102dc44bb1664376dad7ec47` | 14,995 |
| `4ab34bbd3ca803213b6eecbaba81af719630f5d0` | `f947d38de96534b3882fba023e51ecd0476c809d` | 14,995 |
| `90fd0f22cfdfd6c839ef5ba9c694e9189c51e947` | `9d4c1dedfe14059c29ba6e6527c9a5de943658ed` | 15,156 |
| `a96d1b821d10ed3d9e99dd06c5141f9f242ae318` | `f96bebefbc1e7d8187efadb62f88d524cdd18451` | 15,161 |

[SNAPSHOT_RECOVERY_REVIEW.json](reports/SNAPSHOT_RECOVERY_REVIEW.json) 和 [OBJECT_TREE_RECOVERY_REVIEW.json](reports/OBJECT_TREE_RECOVERY_REVIEW.json) 是 Root 实际恢复时产生的两份原报告。[recover_snapshot_audit.py](scripts/recover_snapshot_audit.py) 与 [recover_object_and_tree_audits.py](scripts/recover_object_and_tree_audits.py) 保持原字节，含当时专用暂存路径。重现时应在隔离暂存环境按这些输入路径准备原材料；本次保全没有再次执行这两份脚本。

## 实际读取形成的独立锚点

TREE 四个 encoded parts 各自前 65,536 B 曾经通过 H 按固定文件版本实际读回。已有四份原 SDK 和前缀位于 placement `0028a36f1d5b75b643c6b39137e74b257b2281b3`。恢复后的四个完整分片均匹配原完整身份，且四个前缀与实际读取字节逐字相等；独立记录见补充 placement `1917113807562b607815b08c3887abdb69a34ce5`，review `e61daf7aa52219e2d63b6d801c40e74511363310`。其后一次读取控制 cell 被终止，遗失的第二轮 SDK 字节仍为 Unavailable；恢复分片不冒称恢复了那些 SDK。

OBJECT 的原 gzip 前 262,144 B 已由 native agent 从四次实际 65,536 B 读取保全，原 manifest 为 `022b2bbb59a23be9f4808d7b48fc59110d48ad28`。本次独立检查恢复前缀的整体 SHA-256/Git SHA 及四个原 chunk SHA，全部相等；原前缀 SHA-256 为 `db5ae723816e83f50ae9258615c0feb5c46e50c1eb68a8c1b07d4b0c990552b9`。四份原 tool result 和 base64 伴随的身份在完整 manifest 中引用，没有新的现场读取或完整 OBJECT 读取声明。

## 重组已有原分片

三组审计输出的 52 片各自独立编码。对 manifest 中每个 artifact 的 `parts` 按 `decoded_offset` 顺序：

1. 按原 Git blob SHA 获取分片，先核 encoded 字节数、SHA-256、Git SHA。
2. 要求恰好一个末尾 LF；移除该 LF 后，对该片独立严格 base64 解码。
3. 核该片 decoded 长度和 SHA-256；要求偏移连续，从 0 开始，逐片拼接二进制。
4. 对完整 gzip 核三重身份，随后解压，再核 raw 三重身份。所有身份通过后才解析 JSON，保留原字节用于归档。

原 395-object 输入 packet 的五片采用另一种明确记录的格式：先去各片唯一末尾 LF，按 ordinal 拼接 base64 字符，再整体严格解码及 gzip 解压。其完整规则和原五片身份保留在 [CANONICAL_MANIFEST.original.json](inputs/CANONICAL_MANIFEST.original.json)。原 c0f inventory 的五片是 gzip 二进制段，直接拼接后解压。三种编码各按对应原 manifest 处理。

## 本次打包检查及边界

本次只读检查重新核对本地 52 片、三组 raw/gzip、九张 map 行数/排序、两原 commit body、32 before 元数据、41-path compare 和 canonical diff 身份；没有重算九个 Merkle 根或重跑原生验证。其结果保存在 [PACKAGING_INDEPENDENT_CHECK.json](reports/PACKAGING_INDEPENDENT_CHECK.json)。

打包检查 v1 因将 JSON 的 `false` 直接嵌入 Python 而以 NameError/exit 1 停止；v2 只将该嵌入改为 `json.loads` 后实际 exit 0。两版脚本和原 exec SDK 均在 `packaging/`，该包装错误不是源门禁、恢复脚本或原生任务失败，也未被覆盖。

本地 `native-root-review.json` 是 48,163 B 的重新排版 JSON，Git blob `b794313a235b9ef1f800da9f2269df1e1c018eff`。已逐结构核实它与原 d7c 的 38,525 B 元数据完全相等，但两者字节身份不同。本目录引用原 d7c 身份，明确记录本地序列化差异。

本目录的 Git blob 保全与建议 placement 不移动 source ref 或 evidence ref；Root 仍是唯一 checkpoint 作者。恢复和保全完成也不表示下一候选已格式化、编译或通过资格门禁。
