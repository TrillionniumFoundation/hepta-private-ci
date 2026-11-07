# r26 原四包门：完整失败证据

**工程门 FAILED100；科学 HOLD；权限 DENY_ALL。** 本组绑定 source51 commit `e28b0f385ee882f842911044958b2810f62f6379`、staged tree `763c8d2b4089f6e9806c3bbb68fa247bc2f6af36`，194 个变更路径。原生 HEAD 为 framework `bef6fa…`，Git 对象身份不冒充 checkout。没有运行新测试或改动源码。

| 原阶段 | 原返回码 | 原进程总秒数 | 结果 |
| --- | ---: | ---: | --- |
| Python runner | 0 | 71.14943599700928 | unittest 报 32 项、0 skip、OK；自报执行 59.132 秒 |
| 四包 strict | 0 | 412.096182346344 | 原命令通过，source/双锁守卫通过 |
| 四包完整测试 | 100 | 363.3845314979553 | nextest 执行 84.109 秒，1564 unique＝1562 PASS＋2 FAIL，0 TIMEOUT；另报 3 skipped |

四包为 CLI、exec-server、network-proxy、external-agent-migration。原 1564 个 binary/name 全出现，无新增 filter；原日志末尾两条失败复述已排除，未重复计数。Python/strict 的成功不把完整项目门变成 PASS。r25、r27 旧惰性工作区门未启动，fix/fmt 未执行。

## 实际失败与旧例变化

| source51/r26 原失败 | 原耗时 | 原观察 |
| --- | ---: | --- |
| `runtime::tests::host_blocked_subdomain_wildcards_exclude_apex` | 5.089 秒 | `Blocked(NotAllowedLocal)`，预期 `Allowed` |
| `runtime::tests::host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist` | 5.267 秒 | 同上 |

完整错误块保存在 [failure-1.txt](original/failure-blocks/failure-1.txt) 与 [failure-2.txt](original/failure-blocks/failure-2.txt)，逐字对应原 log 的 211476..212277 与 212277..213194 byte spans。原件没有给出具体 DNS 回答、resolver 错误或 timeout，不能凭测试耗时推断根因。archive 中 runtime.rs 是 75473 B 的原 source51 support source；source52 的修复候选没有混入此组。

原 r24 三项失败在本轮均实际 PASS：两个 exec-server sandbox/bwrap 例为 1.424 和 0.100 秒；DetectTls policy 例为 0.006 秒。逐 ID、原失败块和新 PASS 行在 [R24-FAILURE-TRANSITIONS.json](readback/R24-FAILURE-TRANSITIONS.json) 中分别绑定两个源码，原 r24 FAILED100 不改写。

## 原件与复算

- [CLOSURE.json](CLOSURE.json) 与 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 是本次新读回结论。
- [checkpoint-r26-closed.tar.gz](checkpoint-r26-closed.tar.gz) 保留 279 个 regular 原成员：194 source、33 evidence、44 input、3 failure-blocks、1 guidance、2 locks、1 support-source 和 INDEX。整个 archive、278 条 INDEX、所有 raw SHA/Git blob、解出字节均逐项核对。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json) 覆盖每个成员；194 source、原双锁与 support-source 从原 archive 读取，没有复制第二棵源码目录。原 INDEX 和 tar 的 transport mode 与源 manifest 的 Git mode 分别处理。
- original/ 内保留完整 log、结果 rows、raw rc、receipt、resources、环境、守卫、原 runner、baseline 和 apply/lock 前置原件；大 UTF-8 文本用 mtime=0 gzip 无损保存，映射记录解压前后完整 pins。
- export-custody/ 保留唯一只读封包任务的原控制回执。其自然退出 0 仅说明归档成功，原 Rust 测试及其外层任务仍自然退出 100。
- root-review/ 的原根报告按原字节保留；supplemental-r24/ 仅补原历史失败与前置证明，不改变旧正式组。

运行 `python3 verify_and_assemble.py --verify-only` 可离线核对本组最终 manifest 和 gzip 往返；它不会执行 runner、Git、Rust、网络、metadata 或 formatter。完整 scope 及局限见 CLOSURE，科学结果仍 HOLD，后续源码不得继承本轮工程资格。
