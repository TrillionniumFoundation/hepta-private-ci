# 固定四包的 pin-utils 回移与双锁 proposal 候选

本包审阅的是四个新增 CI 工具文件。它尚未生成真实项目的新 Cargo.lock 或 MODULE.bazel.lock，也没有改变产品依赖、既有维护补丁、检查策略或 Git ref。真实生成只由普通 `pull_request` 自动工作流执行，成功后交付待审 artifact；工作流没有自动提交或发布功能。

固定父提交为 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`，原树为 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。候选计算整树为 `cb7f5eaaadd55c1476a8b695c04c70848c603e85`。完整原树的 10,582 个文件叶及模式全部保持，只增加 `.github` 下一个 workflow、两个 Python 脚本和一个机械变换规格 JSON，共 10,586 叶。运行时源守卫再次验证同仓 PR、确切 base ref/SHA、单一父提交、完整树、17 个固定源 blob 和干净工作区。

## 为什么采用固定版本回移

新 cargo-deny 留存日志的 pin-utils advisory 已由根任务另包保存；本包不重新解释旧日志缺失的失败。当前四个直接反向依赖为 aws-smithy-http 0.64.1、aws-smithy-runtime 1.16.0、aws-smithy-types 1.8.1、loom 0.7.2。AWS 新发布还涉及协调的兼容线变化，因此本候选保留这四个版本，限定移除 pin-utils 的源码和 manifest 差异。原工作区已有的 aws-config 等本地维护补丁与 Git 依赖保持原样。

全部四个官方 archive 的完整字节已在 `research/official-archives/` 保存。`research/official-archive-attempt.json` 保留实际请求地址、返回状态 200、最终地址、长度与 SHA256；本次下载回执没有保存 HTTP wire、响应 header 或精确开始结束时钟，不能把这些未留存内容补称为原件。正常 PR 的下载程序会额外保存有限白名单响应 header。

| 包 | 固定版本 | 原 archive 字节 | 原 Cargo.lock SHA256 |
|---|---:|---:|---|
| aws-smithy-http | 0.64.1 | 31,772 | 639b4d8f8555f24a9be649811c3eb0b4d4616f4d61daf0c32e28873bc1ea9af1 |
| aws-smithy-runtime | 1.16.0 | 147,175 | d6e302ac1d88b99652489df31abdec6ac42a2ab2ac3982ad0ac49f64dfaf28ba |
| aws-smithy-types | 1.8.1 | 108,689 | 69bb407740a197147da48238ecc94498493c9e85445732360cec180296ca45f1 |
| loom | 0.7.2 | 73,989 | 419e0dc8046cb947daa77eb95ae174acfbddb7673b4151f56d1eed8e93fbfaca |

取件地址固定为 `https://static.crates.io/crates/<name>/<name>-<version>.crate`，拒绝不同最终 URL、非 200 状态、长度或校验和不符。四包共有 212 个原始普通文件。拒绝符号链接、目录或特殊成员、路径越界、不规范路径、重复成员及超限成员。

限定变换合计 14 个文件：HTTP 2、runtime 6、types 3、Loom 3。每个文件有完整前后 SHA256、逐项原文替换和次数，前后任一不符即失败。五个 AWS Rust 文件的变换后字节与固定上游新提交的文件完全一致，原提交 `b3bdfffc8dbbaf115b572079d7f170ec78ec939c`、新提交 `b964fc77de60b0a492ff788c40bb66524fd26a44`。HTTP 没有 pin-utils Rust 调用，仅删两份 manifest 中的依赖。Types 的 `Inner::collect` 是生产路径；研究时早期“仅测试使用”的表述已在 `research/static-transformation-proof.json` 明确纠正，不能沿用。

Loom 源依据固定 `a7033ee06a97c52eb2f8131c095fbea6c6eecba3`，将原作用域内一次 `pin_mut!(f)` 改为 `let mut f = std::pin::pin!(f)`，保留轮询、reborrow 和 Waker 代码。其私有回移明确将包声明的最低 Rust 版本 1.65 改为 1.68；工作区仍固定 1.95.0。原 `futures = ["pin-utils"]` 保持，并将原隐式 `pin-utils` feature 保为显式空 alias `pin-utils = []`，兼容旧 feature 名，不保留真实 pin-utils crate。

四份许可原字节保持；其它 archive 文件（含三份历史 Cargo.lock）完整保持。每包只另加两份来源说明，共生成 220 个 vendor 文件。两份 Cargo manifest 同步采用相同依赖、feature 和 MSRV 变换。历史包内锁是被保存的上游文件，实际解析权威仍为工作区 Cargo.lock。完整原 archive 可独立恢复所有原字节。

## 真实工作流的生成与失败语义

工作流仅由固定 base 分支上的普通 PR 触发，读取权限、固定 checkout/head、原准备环境、Rust 1.95.0、cargo-deny 0.19.0、just 1.51.0、Bazel 9.3.0；保留原 proposal 的 30 分钟 job 预算。没有 dispatch、rerun、私有容量查询或产品测试预算修改。

运行次序如下。

1. 验证版本、原 source 和实际 workspace member 清单，留存三份 before 文件及原 Bazel lock 基线检查。基线检查的退出码完整保留，但与既有 lock proposal 一样不阻止修复旧锁；后续两轮检查必须成功。
2. 下载和验证四个原 archive，应用固定变换，在原 Cargo.toml 添加四个 path patch 和仅这四个 vendor 路径的 workspace exclude。逐字段证明所有旧 patch、成员及其它 manifest 字段不变。
3. 实际运行 `cargo +1.95.0 update --workspace`。完整 Cargo 图守卫只允许四包从原 registry 身份变成同版本 path 身份（移除 source/checksum）、各删一个 pin-utils 边，以及删唯一 pin-utils 0.1.1 节点。所有其它 package 字段、依赖 ID 和锁顶层字段严格相等；任何额外变化失败。再实际执行同一命令，要求锁字节相等，并重新取得真实 workspace member 清单要求相等。
4. 原样执行 `just bazel-lock-update` 和 `./scripts/check-module-bazel-lock.sh`，再执行同一更新与原检查，要求 MODULE.bazel.lock 两轮字节相等。**这一层证明原生成、错误检查与重复性；没有声称已证明未来 Bazel 锁每个非目标字段都不变。完整实际 before/after 和 patch 仍需后续审阅。**
5. 原样执行 `cargo +1.95.0 deny --locked --all-features check --config deny.toml`。不增加 ignore，不放宽 deny.toml，不替换原命令。再次确认两锁与 root manifest 未被后续检查改变。
6. 确认 tracked/untracked 文件集合仅含三份 root 文件与固定 vendor 文件，验证全部 vendor 内容与可执行模式，使用私有 Git index 生成 patch，实际正向及反向重放并核树。没有创建 commit 或改 ref。
7. 最后捕获 source-after 和 after 文件。捕获失败即使发生在前述步骤成功之后，仍会使 `proposal_validated=false`、退出失败，并把可能已生成的无资格 patch 移出待上传目录；原始日志继续保留。收集步骤单独输出 validated 标志，workflow 最终同时要求生成、收集、上传成功及 validated=true，不能仅凭步骤绿色通过。

原 Cargo/Bazel/deny 命令 stdout/stderr 留存完整；五个版本命令和 metadata 的 stderr 单独留存：版本只解析 stdout 的原固定字段，metadata 只解析 stdout JSON；stderr 不丢弃。原命令非零退出码向上传播。失败后仍执行收集与上传安全日志，但最终 job 维持失败。源守卫失败、setup 失败或工作流强制终止等早期情形，只有实际已取得的文件可以留存，不承诺尚未执行的命令有日志。

## 上传隐私与固定源豁免

完整原日志首先写入上传目录外。收集前检查已知凭据值（及既有 base64/JSON 表示）、四层百分号解码、控制字节、authorization/token 语法和 URI user-info/query/fragment；不把 secret 或 secret-derived 指纹写入拒绝回执。未通过时不创建公开目录，不改写原日志来假装完整。

固定 source-only 语法豁免只有 `before/Cargo.toml`、`after/Cargo.toml`、已验证的 `proposal.patch`：before 须与固定原 manifest 的完整 Git identity/字节相等；after 须为原件或唯一固定变换；patch 须与成功正反 index 校验后绑定的完整 identity 相等。它们仍执行已知值和控制字节检查。**所有原日志及两份生成锁始终执行完整日志/URI 检查。** 二进制 archive 仅接受原 Cargo.lock 校验和的完整官方原件，不能借此上传任意二进制。

第一次离线检查真实原 MODULE.bazel.lock 时，旧 fragment 规则误拒七个既有来源 URI。原失败 stdout/stderr 已保存。修正仅允许原 blob `1904db189003cb0b559f71958518e33a45fb6bb7`（1,738,619 字节、SHA256 `11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3`）中七个完整值；先执行已知凭据、userinfo 与 query 检查，最后才允许其既有 fragment。没有后缀通配或新 URL 放行。验证包含精确集合相等、七个正控、七个近似后缀拒绝和凭据 query/user-info 拒绝。

公开目录只含固定文件白名单，拒绝符号链接、硬链接、特殊文件、读取中变化、单文件超过 64 MiB 或合计超过 256 MiB；完整复制之后核逐字节和路径集合。检查覆盖范围明确，不宣称检测所有未知秘密或任意编码。

## 离线结果与重放

`verification-v2/static-verification.json` 为 109 项已通过的静态与受控验证：完整原树、17 份实际固定源、四 archive/14 变换、真实 Git 正反 patch、Cargo 图漂移拒绝、manifest/patch 伪造拒绝及日志隐私拒绝。六个小型合成流程分别覆盖Bazelisk 冷启动 stderr 后正确版本成功、错误版本拒绝、Cargo exit17、Bazel exit23、deny exit1、source-after 捕获失败；所有合成 result 均带 `synthetic_control_only`。这些 fixture 的 Cargo/Bazel/网络/metadata 输出是替身，六包锁也标为 synthetic，**不属于真实项目的新锁、deny PASS 或产品 native 资格**。

在独立目录可运行：

```sh
python3 verify_candidate.py --root /absolute/path/to/restored/package --output /absolute/path/to/new-verification-output
```

输出目录必须不存在。仅依赖 Python、PyYAML 与 Git，不需要 Cargo/Bazel。`source-patch-verification.json` 另记录四新增源文件在真实临时 Git index 中的正反重放；它是四文件的加法 patch，原全部产品叶保持由完整 Merkle 证明负责。

本机 `cargo`、`just`、`rustfmt` 不可用。遵照本任务明确范围，没有安装工具链或调用产品/native 作业；`just fmt`、真实双锁生成、原 cargo-deny、产品编译及相关测试均为 **NOT_RUN，等待正常 PR CI**。独立审阅与 immutable 实际登记在后续独立回执中补充；计算 hash 不等同已发布 ref。

## 第二版修正与旧候选保留

第一版四源及其 actual GET 保持不变，位于父工作包的 `final-review/` 与 `source-registration/`。独立审阅用固定 Bazelisk v1.28.1 的完整源码确认：冷缓存下载在启动 Bazel 前向 stderr 写入 `Downloading` 行；旧版本检查合并 stdout/stderr 后取首两词，会在命令 exit0 且 stdout 正确为 `bazel 9.3.0` 时误拒。该独立受控复现是工具初始化边界，不是一次真实产品或 Bazel 原生失败。固定 primary 原GET已复制到 `research/bazelisk-cold-start-primary/`；旧受控原件由独立审阅包保存。

本第二版只在两个 Python 文件内分离五个版本命令的 stderr，并将五份完整 stderr 日志加入精确收件白名单；将辅助参数从 `json_output` 改为准确的 `separate_stderr` 名称，原 metadata 逻辑保持。workflow 与 spec 全字节相等，所有版本断言、命令、工具版本、生成及上传最终门不变。`v1-to-v2.patch`、逆向 patch 与真实 Git index 重放可核这一限定差异。新增控制先写下载 stderr 再写正确 stdout，完整成功链通过；输出 9.3.1 仍拒绝，且日志保留。此前七项 URI 误拒及旧 v1 冷启动误拒都不能被覆盖为通过。
