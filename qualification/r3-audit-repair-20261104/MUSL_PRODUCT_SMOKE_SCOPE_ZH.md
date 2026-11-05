# Hepta musl 产品最小资格候选

**当前状态：仅源码候选，尚未构建或运行。** 新增一个工作流 `.github/workflows/hepta-musl-product-smoke.yml`，blob `6aad46b1fe0edcf315ef8b1a5546225c59efe235`。原 GNU/musl blocking 配置、测试断言、平台定义和依赖不变。

## 要补的实际缺口

现有两个 Linux blocking 标签共享 GNU/glibc RBE 平台；四个显式 musl V8 归档构建有缓存成功证据，但其 Cargo smoke 都实际跳过。它们不能证明本产品 musl 可执行进程。原审计 JSON 为 `29c4057e04593d314dcf95a9ebf7fec1aaf4bdf0`，本文新增的是可执行资格入口。

本候选只选择已存在的 `//codex-rs/cli:hepta_linux_amd64_musl`。其 platform_data 规则将真实 Hepta rust_binary 切到既有 `@llvm//platforms:linux_amd64_musl`。GNU 主机/执行工具链仍供 proc macro 和构建工具使用；没有新造平台。

## 运行及证据合同

1. PR 或手动执行时 checkout 明确的 `github.sha`，分别记录 PR head、实际 merge/commit、tree、原始 Git parent 头、关键源码 blob、runner/image 和前后源码洁净状态。不会把浅克隆的历史遍历空结果当作无父提交。
2. 复用原 `prepare-bazel-ci` 和 `run_bazel_with_buildbuddy.py`。命令顺序为 `ci-linux → ci → opt → 显式 musl 平台 → lockfile_mode=error → remote_download_toplevel`。Keyless 回退保留原 CI 设置；有 key 时使用原 RBE/cache，实际缓存命中不称新编译。
3. 构建现有目标。使用同组选项实际查询平台 alias 的 canonical label，再与包装目标及内部 Hepta 的配置逐值相等；不猜 Bzlmod 仓库前缀。
4. 读取两个目标的 `DefaultInfo.files_to_run.executable.path`，验证唯一主仓 label、相对 bazel-out 路径、实际 output_base/execroot 所有权及 samefile。不会从多个输出中随意取第一项。
5. 复制实际 ELF，校验 SHA256，记录 `file`/`readelf`；本项要求静态 ELF64 x86_64，无 PT_INTERP、无 DT_NEEDED。再运行该确切文件的 `--version`、`--help`，每个命令只执行一次，各 30 秒，保留原 Hepta 输出合同。前后及上传前哈希必须相等。
6. 上传实际二进制、源码身份、每条命令 argv/退出码/耗时、构建与查询原输出、ELF 输出和逐成员哈希清单。BEP 仅保存不含 options/environment 的事件与指标投影；原始 BEP 不上传。文本日志对唯一显式 BuildBuddy 凭据作字节脱密，smoke 子进程不继承该 key。

新 job 的 120 分钟、build/smoke step 的 110 分钟只约束这项新资格。全部现存测试时限不变。构建失败、工具缺失、链接失败、进程超时都应真实失败；不添加重试、跳过或 GNU 备用产物。

## 实际通过后能关闭的范围

完成同源原工作流、下载工件并独立核验 ZIP/CRC/每个成员和执行哈希之后，可以关闭「该提交的静态 x86_64 musl Hepta CLI 构建及两个实际 CLI 进程 smoke」缺口。不能将它扩大为完整 musl 业务测试、Alpine 部署、ARM musl、sandbox/security、联网工具或正常 Root/Session 入口验收。

原 `rust-release.yml` 不作为此入口，不触 tag、release、签名或发布。手动运行采用选定工作流 ref 的实际 commit，不接受另一个未审源码输入。

## 固定源码依据与待验收

静态依据固定为 `ff72d462d74f9eb856aa9edbc368caad9c466708` / tree `f780fe13946102a33b329898af48810be9c7bf0c`。详细 JSON 列出 14 个原文件及其完整 blob、上游 platform_data 源和 cquery API。

Root 的两项修订（浅克隆 parent 与 canonical platform 真值）和 architecture 的两项修订（主仓 label 精确相等与输出目录归属）均已纳入。当前没有 YAML/Python 解析执行记录，也未启动 GitHub、native Cargo 或 Bazel；实际工具链解析、链接和执行仍须真实 CI 验收。
