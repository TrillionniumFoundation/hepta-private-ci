# ebe273 Windows 原生资格记录

## 固定来源和终态

本记录只覆盖 [PR #7068](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7068)
的 `ebe2737b4014c9b45ad995adccc53eb71e718f3d`，tree
`992b66b378bbc9329ed418af39496eeec61fa37e`。
[正常 Windows workflow / job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45445453422/job/138627851875)
分别为 `45445453422` / `138627851875`，在 2026-11-24 17:39:10 UTC
结束，终态 **failure**。本次正常运行没有人为取消。

这是该次完整 scoped workflow 的结果，不代表整个仓库或其他 CI workflow 的资格。
`receipt.json` 保存全部唯一测试名称、选择器计数、日志散列和已知边界。
失败重试按同一测试的另一次尝试处理；日志末尾重复的失败摘要不重复计数。

## 实际执行结果

| 选择 | 唯一用例 | 通过 | 失败 | 选择器外用例 | 实际尝试 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原生路径与安全原语 | 14 | 13 | 1 | 5 | 15 |
| 私有 Registry | 2 | 2 | 0 | 26 | 2 |
| State SQLite 恢复 | 6 | 4 | 2 | 203 | 8 |
| Cognitive store / 恢复 | 23 | 0 | 23 | 249 | 46 |
| Directory / schema / Bao / retrieval / outcome | 30 | 26 | 4 | 259 | 34 |
| Prompt / final-use consumers | 12 | 12 | 0 | 227 | 12 |

这六个选择没有同名重复用例，共 **87 个唯一用例、57 个通过、30 个失败、117 次尝试**。
“选择器外用例”可能在不同选择间重叠，不能相加声称仓库跳过了多少测试。
Scoped Clippy 和随后 `git diff --exit-code` 成功，仍有 warning；最终 artifact 上传成功。
空 diff 日志未进入 artifact，diff 成功来自完整 job 步骤原文，不从文件缺失推断。

## 已取得的原生证据

原有九个私有路径原语全部通过，包括原子替换时保持旧 reader、单字符目标、真实目录
flush、排他锁、junction / reparse / 硬链接拒绝和严格 owner / DACL。新的同 retained
handle 规范路径用例通过，namespace 双遍观察和多页长名称用例也通过。
普通创建文件的继承用例仍然失败；本 head 尚未包含后续 owner 双上下文 fixture 修订。

State 的四个通过用例分别验证 reparse 根拒绝、替换 / 链接 / sidecar / 权限漂移拒绝、
仅从 retained replay 文件 materialize 且不覆盖候选，以及源检查只读且原文件 writer
入口仍然 `Unavailable`。其中三个此前被错误 owner fixture 阻断的用例已在本 head
实际通过。两项 cold-image 用例仍停在 owner 检查，不能宣称整个恢复流程闭合。

Registry 两个用例通过，包括第二 writer 拒绝和 rename 后失败的 poisoned / reopen
语义。Prompt / final-use 的 12 个用例实际通过；此前导致该选择零执行的编译问题已经
越过。完整名称和每项原始结果见 `receipt.json` 及 artifact 中对应日志。

## 仍存在的真实失败

### 26 个 owner 拒绝

原语 1 个、State cold-image 2 个、Cognitive 23 个的实际首因均包含：

```text
storage object owner differs from the effective token user
```

State 失败用例为 `cold_image_is_immutable_and_reconnects_to_same_copy` 和
`cold_image_rejects_wrong_guard_replacement_sidecars_and_size`。
全部 23 个 Cognitive 用例在创建 store 时返回 `Unavailable(...)`；尚未执行到其后续
事务、恢复、schema、witness 或撤销攻击断言。先前的 `cognitive root is redirected`
已经消失，说明同 handle 规范路径修复推进了执行阶段，**不等于这 23 个用例已通过**。

这些日志证明实际文件 owner 与 effective token user 不同，不能据此指认一个未观察的
具体 SID 或声称已读取 TokenOwner。严格 validator 未被放宽，也没有事后修复 owner / ACL。
修订普通创建的测试预期不能代替实际 SQLite DB/WAL/SHM/journal/temp 创建点的修复。
后续 opt-in explicit-owner VFS 和独立 owner fixture 不在该 head，资格不得回填。

### 4 个 ledger 测试观察前提错误

以下 `evaluated_shadow::tests` 用例通过独立 `fs::read(path)` 读取仍由 writer 排他锁定的
ledger，均在 `evaluated_shadow_tests.rs` 返回 Windows `Os { code: 33, ... }`：

- `durable_stage_records_a_decision_and_retries_after_reopen_without_new_bytes`
- `invalid_authentication_artifact_or_dataset_never_calls_any_port`
- `ledger_conflict_capacity_and_io_uncertainty_cannot_report_learning_recorded`
- `old_signed_evidence_cannot_enter_a_recomputed_new_authority_epoch`

该失败不能通过释放生产锁或删除 exact-byte / corruption / poisoned 断言解决。
后续 test-only 候选保留传入 ledger 的同一 open-file-object 的 duplicate，仅在串行观察时
读取真实磁盘字节并保存、恢复共享 cursor；重开时换用新 owner 的 duplicate。故意
`set_len(0)` 的损坏注入也保持生产锁连续持有。该候选不扩张生产 API 或应用克隆句柄契约，
必须在新 head 通过原有 Windows 用例才能获得原生资格。
该候选为 `2cdbf15c1f7fe5f6705bb997ed90d4415b918d1c`，仅修改测试文件，43 行增加、
27 行删除。提交前 `just fmt` 和 `git diff --check` 均成功；未进行本地大图重编译，
编译和原生执行留给既有正常 Windows 选择，当前不声称修复后的用例已经通过。

## 可独立复核的证据包

本目录的 `artifact.zip` 是 GitHub artifact `14946917714` 的完整下载，50,676 字节，
SHA-256 `bb5a3cc1b614a29d31ce024c7ad773cd9eeafabcbc674dc3ca8eb413dc6722ca`，
与 GitHub 返回的 artifact digest 相同。内部 `head.txt` 等于本记录固定 head。
所有成员原始字节数和 SHA-256 均在 `receipt.json`。

```sh
python qualification/ci-remediation/windows-native-ebe273-20261124/verify_receipt.py
```

脚本校验 ZIP 与每个成员的散列、来源 head、nextest 摘要，以及按 package / test / attempt
去重后的计数。完整 job 原文另有保留，其 CRLF 转 LF 后的文本散列在 receipt 中；该文本
不冒称 GitHub 原始日志 ZIP 的逐字节副本。本包仅含公开 CI 和合成 fixture 的证据。

通过的目录 flush / rename 测试不构成断电实验；namespace 观察不构成全域 currentness
或 ABA 排除；cold-image 用例也不替代尚不支持的原文件 writer fence。这些边界保持不变。

## 原始 API 依据

- [LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)：同进程第二次打开也受排他范围锁限制。
- [DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)：duplicate 引用相同对象，并共享文件位置。
- [Owner of a new object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)：新对象 owner 的选择与 DACL 继承是不同规则。
