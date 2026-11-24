# Cold01 修复候选、实际格式检查与物理诊断检查点

这份检查点保全两份 Rust 修复候选、已完成的一次格式检查，以及从原 Cold01 失败留下的物理文件读取出的诊断原件。**候选在本检查点的状态仍是 NOT_BUILT / NOT_UNIT_TESTED / NOT_COLD_QUALIFIED。** 没有新的成功 cold、Adopt 或学生学习收益。

## 候选修改了什么

独立不可变候选 commit 为 `bf6d51904c8bcda5d50f3782c85ece84cb73a78f`，tree 为 `03f7135e2c060422f9dbd51bb38c5701cfaefe24`，单亲为 `61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd`。原 Git 创建回执和实际 commit diff 一并保存，两份完整候选文件的本地 Git SHA1 与原回执一致。

此前 completed C 读取的是最终 drained generation，而 cold 验证的旧合取要求这个晚期对象仍是 genesis，并用它的晚期观察摘要对照首次 publication。候选通过既有 `observe_original_feature_boundary` 从同一受校验 journal 保留原 genesis 摘要，再分别比较首次 target 与实际最终 drained 状态。原语义 patch、两份修改前/后的完整文件、来源 pins 和静态 peer 意见都在原件包中。

静态 peer 只审这两份 Rust delta。它没有执行编译、单元测试或 cold，也没有证明 actual80 中所有失败谓词。原准备稿的状态与验证清单保持原样；测试文件或测试名称的存在不证明相关模块已编入或测试已运行。

## 实际格式检查

ROG job `1a1fe1069a8-ffbe-2064` 实际 SUCCEEDED / exit 0，H 终态 complete、durable、confirmed，完整 stdout 为 294 B、stderr 为 0 B。六份 owner 原件共 50,300 B，各自固定 version、完整字节与 SHA 均核对。

实际运行了一次 `just fmt --base 7f790fb2f907ef9e618c3c7d233d22135ab00580`。登记范围中的两份 Rust 文件被格式检查，另两份归档 Python 不在 Ruff registry 中；四份 payload 的 before/after 字节相同，保存的两份 Rust body 与候选 Git blob 相同。fmt 命令耗时 0.174355016 s，owner 3.740145592 s，前者包含在后者内，不相加。

格式 owner 使用受限的 `7f790...` checkout 与固定 formatter 来源，**不是完整 bf6d 或 61503 checkout**。这里证明实际格式命令和指定文件字节稳定，不提供 build、unit test、全仓检查或 cold 资格。格式阶段没有运行 native、physical collector 或模型任务。

## 实际物理诊断补全了哪些事实

AI395 job `1a1fe1384e2-ffbe-2069` 实际 SUCCEEDED / exit 0。五页原始 H 响应连续还原完整 66,804 B stdout 与 0 B stderr；stdout 本身是两行 NDJSON，第二行携带原始 gzip 的 base64。原 gzip 为 48,927 B，SHA256 `47364fc10bd07779339fbce47456586bab173a01b23ad45c83151f703f7fa5d4`。

gzip 有 35 个普通文件：34 份源原件共 242,765 B，加上此次 collector 的 RESULT 23,871 B，共展开 266,636 B。逐成员字节与 RESULT 的 34 行长度/SHA 全部一致。collector 对这些源文件做了两遍完整读取，共 485,530 logical B，并报告两遍完整字节与身份一致；这仍不是原子快照。

本次按已冻结的 11,866 B reader 进行只读诊断，固定源路径，逐级 NOFOLLOW、原件 NOATIME，30 s 内层 alarm / 90 s H 上限；归档在内存中构造。记录为源权限变更 0、源写入 0、native 启动 0、诊断进程 1。它不提供新的独立 postterminal 进程组或 mount 快照，旧 mount-cleanup 只能说明原清理时点。

新原件确认 first-publication 的 CURRENT 等于 completed CURRENT，original profile 等于 registered profile，且保留相同 initial 绑定。**其余 publication 验证条件没有在本检查点独立重算。** 旧 errno13 拒绝仍是当时真实访问结果；这次经授权读取补充后续事实，不把旧拒绝改写成已读取。

## 原失败与科学边界

原 Cold01 job `1a1fdeb7f2f-ffbe-2013` 仍为 FAILED / H exit 1、nextest 100、内层 Rust 101；1 case、0 pass、1 fail，原错误仍为 `actual first publication verification fact differs`。旧 main 和 canonical XML 的完整 SHA 与新诊断包中的对应原件一致。完整失败原包已在 `c93f22d5c5c34b38078c81ebad27d47f34a11e45` 保全。

这属于 Q24 解析 fixture 的生命周期问题。格式检查成功和只读诊断成功不能计作 cold 成功、真正 Adopt、自有学生改进或未来独立任务学习信号。文件数、读回页数、命令数与重复观察都不是独立样本数。本包不纳入随后编译、模块挂载排查、单元测试或新的 native 任务。

## 封包与使用范围

`CHUNKS.json` 给出按 offset 顺序拼接的二进制分片及其 SHA，`CONTAINERS.json` 给出完整 xz 的 SHA。解压后的 `MEMBER_INDEX.json` 给出每个保留文件的字节数与 SHA。原 gzip、原工具 wrapper、原 text、候选/格式/只读准备稿、root 控制回执与明确标记的本地复核分别保留。原件内容没有重新序列化。本地复核报告中的 process_launches 为新增远端/H/业务进程口径；本地解析、哈希和压缩工具确实执行过，不计作 native 或科学实验。

一次本地展示辅助代码曾把两行 NDJSON 当作单个 JSON 解析，报 Extra data；随后两次本地封包准备也分别在 JavaScript 解析及记录文字构造阶段报错，尚未写出包。它们没有远端调用、源文件修改或 native 执行。原观察单独保留；没有虚构最初未保存的完整失败展示输出。随后按实际两行结构完成字节核验。

本检查点默认只追加证据路径，不把两个 Rust source 路径写入 branch，不把 bf6d 作为提交 parent，也不声称因此使 bf6d 经 ref 可达。包内 OPTIONAL_SOURCE_DELTA 只列出现有两个不可变 blob；另交给 root 的 SOURCE_TREE_ELEMENTS 可供随后明确决定是否追加 source delta。root 独占 commit/ref/PR 操作。
