# Windows 175 原具名资格的四项缺例：固定选择器与源码契约不一致（2026-11-24 UTC）

延续 [原 19 组原生记录](7032-b1af67a-auxiliary-native-gates-20261124.md)，实读 GitHub run 45184438752 元数据（completed/failure，head b1af67a38f8cf9cee700cc067da1e6001ce220a8，workflow .github/workflows/hepta-windows-current-ci.yml），以及 exact source 与 PR #7032 base 67b04d5833f5660a22c5658a90793f7f76249aa0 的三个完整文件。

两版本三文件 Git blob 逐一相同：
- .github/fixtures/windows-current-ci-scope.json = 63f95a04e16b8eb49bf75c0998a3324d58c47d02
- codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs = f44c32d214c22eaea0973f7c8be8ebb0395d050e
- codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs = 0ed6b443d7584f9b7b2f99d86ebed564849803e3

独立逐行函数声明与 exact test(=...) 选择器核对：每侧四个旧名声明均为 0，以下四个相关新声明均恰为 1；选择器仍含全部四个旧名、未含任何新名。前 3 项属 sandbox-original-failures（13→10），第 4 项属 sandbox-legacy-delete-admission（4→3）。行号在两版本均相同。

| 原冻结测试短名 | 现有相关函数短名 | 行 |
|---|---|---:|
| elevated_non_tty_cmd_forwards_env_output_and_exit | elevated_non_tty_cmd_refuses_before_env_output_or_exit | tests.rs:263 |
| legacy_non_tty_refuses_before_elevated_cmd_emits_output | legacy_and_elevated_non_tty_refuse_before_cmd_emits_output | tests.rs:859 |
| legacy_refuses_before_elevated_delete_is_limited_to_writable_roots | legacy_and_elevated_refuse_before_deleting_owned_roots | tests.rs:993 |
| legacy_refuses_before_elevated_four_cell_delete_boundary | legacy_and_elevated_refuse_before_four_cell_delete_attempt | delete_permission_tests.rs:30 |

实读四个完整函数：第一项要求 elevated unavailable 与 home snapshot 不变，不是成功转发环境、输出及退出码；第二项同时要求 legacy/elevated 拒绝和 home 不变；第三项同时拒绝两个入口并核对 fixture/home 快照；第四项保留 ordinary-host 四单元物理删除对照，两个沙箱入口均拒绝且原四单元与 allowed roots 保留，源码明确说明 admission refusal 不是 filesystem qualification。另读 main 732e934 的 tests.rs blob 3571fed975ef0821053bf1db110a6b6dc20ad453，第307行仍存在第一个旧名。不能把新名作为旧正例的等价替换。

**判断**：缺例可由冻结选择器与当前函数集合不一致解释；并非单纯执行超时或双锁修补造成。这是已存在于 #7032 base 的契约分歧。需要分别保留原175具名资格（及真正可准入的正例）与现有 fail-closed 负例，审核明确新的测试契约后才能执行新范围。不能改名称冒充原测试、缩减175、放松权限或把拒绝当端到端生产正例。不修改 fixture、PINS 或产品代码，不重跑同一源，无新原生通过。main 与 #7016/#7021/#7032/#7052 heads 读回未变，四个 Draft 未合并。整体 HOLD。
