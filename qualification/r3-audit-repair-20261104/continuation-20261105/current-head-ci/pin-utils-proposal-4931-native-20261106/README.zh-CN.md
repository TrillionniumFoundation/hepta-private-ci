# #4931 实际双锁产物与产品文件映射

本包绑定普通 pull_request 自动运行 42175704028、唯一作业 127753541837 和官方 artifact 13482877841。源码为 ddacfba30b28e86eae9615d7063fff2c7941b1d4，原树 cb7f5eaaadd55c1476a8b695c04c70848c603e85，原合并提交 dac3fcfb14c4686f7af8624a88ac5db93c1120e0。原始 ZIP 为 2,232,775 B，SHA256 9417426f75e0b56a2796782e8df49d0f1ea4992570dd1a85a04d826dcb041496；完整 41 成员共 21,038,943 B，CRC 和全部成员身份均已核验。完整作业日志为 1,512,530 B，SHA256 bafd4665289d896253067926d3e17028b6ec1dc1fd9298c555c3f582e6d72c88。

## 已实际取得的结果

原运行实际执行了固定工具版本检查、两轮 Cargo 生成、两轮原 just bazel-lock-update、原 Bazel 锁检查和原 cargo-deny；全部 15 个记录命令 exit 0。原 cargo-deny 完整日志保留 ANSI SGR 字节，四项结尾均为 ok，旧策略文件没有修改。两轮锁字节相等是原执行源码的强制守卫及实际结果所证明，本离线核验另做完整图和全字段比较，未重新运行 Cargo/Bazel。

Cargo 锁从 1,502 包变为 1,501 包：保持四个原版本，仅将 aws-smithy-http 0.64.1、aws-smithy-runtime 1.16.0、aws-smithy-types 1.8.1、loom 0.7.2 改为实际 path 来源，删去四条 pin-utils 边和唯一 pin-utils 0.1.1 节点。其余包身份、字段、依赖 ID 与顶层字段保持；工作区只新增四个排除项和四个 path patch，旧维护补丁全部保留。

MODULE.bazel.lock 的完整 JSON 比较只出现 5 个旧 registry fact 删除和 4 个对应 path fact 新增。其余所有字段及保留的 fact 原字符串完全相等。新四项的 dependencies、features、默认值、optional、req、target、空 strip_prefix 均与实际规范化 manifest 逐字段对应。固定 rules_rs 0.0.96 的官方 archive 由原 MODULE 锁中的 BCR source.json 哈希与 integrity 绑定；其语义另由独立审阅核对，不把锁重复生成相等当成依赖语义证明。

四个官方 .crate 均与原 Cargo.lock checksum、原 HTTP receipt、长度一致。220 个 vendor 文件由 212 个原 archive 成员与 8 个明确 provenance 文件组成：14 个原成员执行固定 preimage/postimage/次数的移除 pin-utils 改动，其余原成员、模式、许可证和历史嵌套 Cargo.lock 原字节保留。Loom 的 futures=["pin-utils"] 保持原值；新增的显式 pin-utils=[] 才是空兼容 alias，真实 pin-utils crate 已移除；私有 Loom MSRV 明确升为 1.68，工作区工具链仍为 1.95。

## 产品输入与实际 Git 对象

产品基线保持 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed / 3982ba56dc5a3f1da0c1de7ea57992f88125c359。同一官方 proposal.patch 的 223 路径为 3 个根文件加 220 个 vendor 文件，共 4,038,263 B。它不包含 4 个 proposal toolkit 文件。

在隔离 Git index 中，原 patch 对 cb7f 源正向精确得到原运行记录的 d0c70513b693ce6d1760a10420084e39f57ca04b，逆向精确恢复 cb7f；对产品基线 3982 正向得到 c7b9fb4e029dc38034a7dfce10a646ccde3e0bf6，逆向精确恢复 3982。两套 index 的 223 个 postimage 全部相同。产品树共 10,802 个叶，其中原基线 10,579 个未改叶保留。完整树 Merkle 独立计算与 Git index 结果一致。

产品树 c7b9fb4e029dc38034a7dfce10a646ccde3e0bf6 已实际 create_tree，根 53 条目完整 GET 相等；223 路径对应 219 个不同 blob 均已实际完整 GET，正文与原产物 postimage 逐字节相同。产品源码 registry 实际 blob 为 5cf849cc78dd2d706aa30f5b20868f941e96b90d（158,432 B），自身已完整 GET 相等。该 registry 是产品源对象映射，不能把其产品相对路径误并入审计证据目录。

精确清单在 verification-02/product-source-map.json，全部产品字节在 verification-02/product-only/，全树在 verification-02/intended-product-full-tree.json。注册原件位于 product-source-registration/。独立审阅收据作为后续单独不可变文件加入本包；当前源对象登记本身不代表审阅或产品原生测试接受。

## 离线恢复与范围

verify_native_artifact.py --root <本目录> --output <全新输出目录> 只使用 Python 标准库和本地 Git，核全部原始 ZIP、完整锁图、archive 来源、223 文件以及双 index 正反回放。它构造所有已验证 tree 对象与修改文件 pre/postimage；未获取未改 10,579 个 blob 的正文，使用 Git write-tree --missing-ok 仅保留其已验证 SHA 与模式。没有完整产品 checkout，也没有运行产品编译或测试。

PRODUCT-VERIFICATION-FREEZE.json 绑定首次成功 replay-02 的脚本、原 stdout、空 stderr 和各派生证明。完整原件均未改写。replay-01 是本地核验器错误地要求 cargo-deny ANSI 彩色结尾等于无色字节而拒绝；原脚本/错误 stderr 保留，随后只对派生判定去除 SGR，原日志不变。另一 local-receipt-write-correction.json 记录本地 apply_patch 写入回执时额外末尾 LF 被身份核验拒绝，并精确改回已实际注册字符串；产品字节和远端对象均未改变。

中断时 NOT_PRODUCT_ACCEPTED 检查点 e7b271d9cbe0534adc70a7d918da624b20fb40ee 及独立检查点 d6a7bc95203f2c8d7c7277b4ef43b596c8fceff4 保持历史原状。本次恢复没有 dispatch、rerun、私有容量查询、ref/PR/commit 写入。锁生成和原 deny 已获得真实结果；组合产品的编译、测试、平台合同仍需后续实际 CI，不能由本包预先授予。

## 传输回放说明

首次可移植外层回放的完整原 verifier 已 exit 0，6,979 B stdout 和四个派生文件均逐字相同；外层仅因 Git 原有 EOF 空行警告仍含旧绝对 patch 路径而拒绝。该警告来自完整保留的 Loom 原 archive 文件 ci/azure-check-docs.yml。首次外层脚本与错误原件保留在 transport-initial-history/；最终外层只规范化 argv 和两条原样 EOF 警告中的同一 artifact/proposal.patch 绝对路径，警告行号、正文、其它字段仍严格相等。没有更改原 patch、产品文件或冻结 native verifier。
