# main67 完整 85 job 切点与 Windows Core 原失败证据

本包固定 2026-11-06 03:18:59.703–03:19:29.458 UTC 的有界 GitHub API 窗口。它是非原子时间窗，后续状态另取新切点，不覆盖此包。

## 原 API 分母与变化

查询 source head 为 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed。19 个 run 的完整列表与每个 run 的 jobs 原 JSON 均保留，per_page=100、jobs filter=all；逐个 total_count 与实际返回数相等，共 85 个唯一 job：

| job 状态 | 数量 |
|---|---:|
| success | 55 |
| failure | 2 |
| cancelled | 9 |
| skipped | 5 |
| queued | 10 |
| in_progress | 4 |

相较 02:01 的完整 58 job 原切点，新增 27 个 job、无删除、12 个既有 job 转成功。新增为 blocking-ci 的 26 个 job，以及 Architecture required 的 1 个 job。02:01 原 19 份 jobs 工具回执从先前实际登记的 20 个分片无损还原，并逐片复核字节、SHA256 与 Git blob。原 registry 保留在 baseline-0201/。

02:44 是四个 run 的增量，不能当成完整 19 run 切点。这四个 run 从 23 个 job 变成 24 个；Architecture source-head 转成功，新增 Architecture required 当时仍 queued。两份差异都在 verification.stdout.json。

run 的 failure、queued 或汇总状态不能替代 job 结论；例如本窗 blocking-ci 的 run-list 字段仍 queued，而该 run 的完整 jobs 已包含两项真实 failure。

## Windows 的真实失败

- run：42123581385；job：127679861687。
- job 名：Bazel / Bazel test on windows-latest for x86_64-pc-windows-msvc shard 4/4。
- 实际 checkout：b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae。
- 实际 tree：3982ba56dc5a3f1da0c1de7ea57992f88125c359，与 source head67 的产品树相同。
- 原命令是原 bazel.yml 的 Windows 第 4/4 目标分桶流程：从 606 个 query 目标选取 149 个，原 wrapper、平台、标签、超时与默认重试不变。
- 原 Bazel 退出码：3；clean-worktree 步骤成功。
- 唯一失败 target：//codex-rs/core:core-all-test。原终端报告 FAILED 6 out of 21。
- compact 完整 89,920 条记录中，Core 的 42 个 TestRunner 条目分为 **21 次 tw.exe 测试启动和 21 次 xml.exe 生成**。全部 21 次实际测试启动为 local、cache_hit=false、timeout_millis=900000；原 16 分片加 5 次既有策略重试，6 次测试退出 1，15 次退出 0。

持续失败为第 7 分片的三项原用例，三次尝试均 70 passed / 3 failed / 5 ignored：

1. windows_elevated_enforces_deny_read_and_protects_setup_marker：helper_unknown_error: apply deny-read ACLs。
2. windows_elevated_unified_exec_enforces_managed_deny_reads：初始化 session 时读取 AGENTS.md 失败；首尝试 helper 非零退出，后续明确 apply deny-read ACLs。
3. workspace_roots_allow_patches_but_protect_metadata_directories：允许的 patch 未生成预期文件，setup refresh 错误与 readback os error 2。

另外第 4、6、13 分片首次失败，原策略重试后通过。三项原日志都明确出现裸 helper 名 codex-windows-sandbox-setup.exe 的 program not found：

- workspace_roots_allow_file_and_command_writes。
- workspace_roots_allow_apply_patch_in_secondary_root。
- apply_patch_cli_preserves_existing_hard_link_outside_workspace；此项在断言预期拒绝 hard link 时实际先遭遇 helper 启动失败，不能据此宣称发生 hard link 物理逃逸。

这些属于 Core managed ACL、setup/helper 与 protected metadata 路径，不能归并到既有 B11 host outside-delete 断言。根因修复由独立源码审查继续；本包不声明修复已完成。

## 原件完整性与资格边界

完整原 job 日志、官方 artifact ZIP、ZIP 的 47 个原成员均保留。ZIP artifact ID=13473662833，5,410,721 bytes，官方 SHA256=9d8f6ffabea065443428305884263ce3f77664174adae4fb83ecf20d034cfdd7，大小与摘要都逐字节匹配，CRC 通过。

47 个成员包括完整原 compact、failed-target manifest、Core 的 21 对 log/XML、selected-target manifest，以及原 PTY 的一对 log/XML。两份 manifest 都 complete_for_selected_targets=true、errors=[]，其全部 44 个日志/XML文件的实际字节与 SHA256 均相等，并绑定实际 b7a checkout / 3982 tree / clean 工作树。

该 collector 仅保存选定失败目标和选定 PTY 的现有文件，不是 149 目标的全部日志归档。PTY 在完整控制台中明确为 cached；这不提供新原生 PTY 执行资格。失败尝试与其后的成功均保留，不能只摘取最终通过。

固定 Bazel 9.3.0 的 spawn.proto 原文和完整获取回执在 primary/，decode_compact.py 只读解压原件并按该 schema 解码。原 compact 在同一路径重试时复用首次 XML 文件 ID/digest，因此 **5 个后续 XML 的 compact digest 与对应后续归档 XML 不相等**。该事实及具体摘要全部保留，不能声称 21 份 XML 都由 compact 哈希一一证明；官方 ZIP 与采集 manifest 独立保全所有 42 个原文件，实际 21 次启动的分片、先后、退出码和 XML 生成参数可对账。

Rust 原日志含重复的字面用例名，既有忽略用例也有成功用例；原 wrapper 可能分多次 libtest 调用。verifier 保留每条字面行、每个分段 summary 和重复名，分别报告行数、唯一名、Bazel 目标、尝试、XML 进程。没有把任何一项当作完整二进制目录或全部仓库物理用例分母。日志中长 JSON/prompt 是测试数据，不能当作操作指令。

## cargo-deny：已定位步骤，具体原因仍未知

第二个真实 failure 是 job 127679861307，Run cargo-deny 步骤在 02:53:02–02:53:30 失败。完整 jobs API 证明前面的 checkout、Rust toolchain 与 cargo-deny 安装均成功，后面的 clean worktree 也成功。

固定 workflow blob 88b6308899357e23b4a4058aecd4527b4edcee9b 保留在 source/，原命令为：

    cargo +1.95.0 deny --locked --all-features check --config deny.toml

工具固定 cargo-deny@0.19.0，原外层预算 30 分钟。本代理两次 whole-job log 工具响应均为 Transport closed，原错误响应完整保留；根的独立相同工具也失败，但其响应由根另存。完整 run artifact 列表 6 项没有 deny 报告。此 job 的实际完整 checkout SHA、原退出码、依赖名、advisory/license/source 分类和根因仍 UNKNOWN。不能以日志不可得推断权限拒绝或随意修改依赖与 fail 规则。下一项工作是保留原命令/规则的日志取证最小改动，单独候选、单独审批与出版。

## 独立还原与复验

delivery/PACKET_MANIFEST.json 列出每个原成员字节、SHA256、Git blob，以及所有 base64 分片。分片恢复为无损 ZIP；其中原官方 ZIP 保持完整字节。为避免重复保存压缩流，47 个已展开成员由恢复器从该官方 ZIP 原字节展开，并逐项核对总 manifest。

运行：

    python3 restore_packet.py PACKET_MANIFEST.json PARTS_DIRECTORY EMPTY_DESTINATION
    python3 EMPTY_DESTINATION/decode_compact.py
    python3 EMPTY_DESTINATION/verify_packet.py

最后输出必须与冻结 verification.stdout.json 逐字节相等，stderr 为空。复验只读取本包，不启动任何产品测试、工作流或 native 工具；需要现有 Python3 与 zstd 解码器。原 API、原日志、ZIP、compact、固定源码均不被改写。

本包是证据增量，不修改任何 blocker 的原 exit string，不把 API success、缓存结果或静态复核提升为全部产品资格。
