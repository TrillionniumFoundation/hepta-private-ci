# #7032 b1af67a 补读原专项门（2026-11-24 UTC）
固定源码 b1af67a38f8cf9cee700cc067da1e6001ce220a8。此次是旧运行的首次补充归档，不是新运行；只读原 job 名册与解码日志，未独立下载 ZIP 字节。不能替代全仓 46 job 或产品隔离资格。

## Windows 原 19 组/175 例
[原运行 45184438752](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184438752) 三 job：owners 137726265948 success，process 137726266447 failure，required 137750634452 failure。独立解析两份日志中实际具名组 JSON，排除每份开头 6 个验证器自测 JSON（original/second 等合成控制记录），实际 owners 8 组 98/98，process 11 组应选 77 实选 73，其中 9 组通过，两个组 selectionMatches=false。合计 19 组，应选 175、实选 171，实际组中 nonPassingTests 均为空；17 组通过，2 组缺例而非测试运行成功。以下四例缺失：
- sandbox-original-failures (13 应选、10 实选)：unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit
- 同组：unified_exec::tests::legacy_non_tty_refuses_before_elevated_cmd_emits_output
- 同组：unified_exec::tests::legacy_refuses_before_elevated_delete_is_limited_to_writable_roots
- sandbox-legacy-delete-admission (4 应选、3 实选)：unified_exec::tests::delete_permission_tests::legacy_refuses_before_elevated_four_cell_delete_boundary

两个组原 exitCode=0 但原组判定 passed=false。required 原 14:12:38 UTC JSON: FAIL_DECLARED_WINDOWS_SCOPE; ValueError: shard did not reach a passing terminal; productionAuthorityGranted=false; finalProductQualification=false。process 原 ZIP artifact 14825707114，原上传记录 19405214 字节、SHA256 86f1f61415687960d8125d64c6632f30ed96739a0f6cb19b4119bd5e197dc763（尚未独立下载复算）。缺例不等于四个端到端生产隔离例通过或失败的同一集合；不得把选择器缩小到 171 或用替代名称冒充原用例。

## NDU native Windows storage observation
[原运行 45184438797](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184438797)：observe 137726266589 success；appcontainer-mechanism 137726266086 failure；acl-observe 137726266664 failure。原 appcontainer 日志 13:31:52 UTC “Reviewed experiment source bytes differ”，13:31:55 “reviewed native trace source bytes differ”，缺 child trace artifact。ACL 13:31:56 “Reviewed mode/OID/SHA/size differs: codex-rs/.config/nextest.toml”；之后缺 preflight.json 和原 ACL 记录。这是源冻结拒绝，不能解释为真实机制已执行失败或成功。
独立 Git blob 读回：nextest.toml 在 b1af67a 与双锁修补前 610f9108 同为 b0644005ace7aee0203fbc5de50094a158083a1f；main 732e934 为 f0430497b34b5335929e24b9e19745f467362641。因此该文件差异并非本次双锁引入。仍须原审核者逐项核准源差异后合法重新冻结，不能自动重写 PINS、弱化比较、改权限或盲重跑。

## 其他原专项运行
- 45184438839 Keyring Sync：Windows/Linux 成功，macOS 取消。三个 job，无完整跨平台资格。
- 45184438866 VERIFY-1：Windows/Linux 成功，macOS 取消。
- 45184438982 v8-canary：14 job，11 success、2 cancelled、1 skipped；两项取消均 aarch64-apple-darwin（release 与 ptrcomp-sandbox）。不可签收完整 canary。
以上未重跑。main 与 #7016/#7021/#7032/#7052 原 head 保持不变，均未合并；本次只增审计记录，HOLD。
