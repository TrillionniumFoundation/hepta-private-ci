# r24：source50 四包原门失败的闭合证据

**工程结论：FAIL，原完整测试与外层进程均自然退出100。** Python runner 的32项测试通过、原严格检查退出0分别成立；它们不替代完整测试结果，也没有触发后续 r25 工作区门或最终 fix/fmt。

源码身份是 commit `1fdd647b0ecb235530e8b88bbea45b3d3762906f`、tree `ea48acf562499192a25e05ae28926a32632dee62`，194条变更源码。该身份来自固定源码清单和原生 guard；本附件没有把 GitData 身份等同于 native HEAD checkout。原 native HEAD 值、历史 pending 字段均按原件保留。

## 原门结果

| 阶段 | 原返回码 | 已观察结果 | 原耗时 |
|---|---:|---|---:|
| Python runner 完整发现 | 0 | 32通过、0跳过；10原测试＋22 helper 测试 | 3.8193337917s，总进程 |
| 四包原 strict | 0 | 原 `just clippy --locked … -- -D warnings` | 217.4727106094s |
| 四包原 full tests | 100 | 1564唯一ID＝1561通过＋3失败＋0超时，原报告3跳过 | 503.7940561771s，含构建；nextest64.588s |

选择保持 `codex-cli`、`codex-exec-server`、`codex-network-proxy`、`codex-external-agent-migration`，原 `just test --locked`、`--retries 0`、默认features与已有平台/ignored条件不变。基线1564个 `(binary, name)` 全部出现，没有新增或缺失ID。基线仅用于完整执行后的验收，没有用作过滤器。Summary后的三行失败复述已排除；3个skip只保留原报告总数，不从日志推断具体身份。

| 失败 binary | 测试 | 原耗时 |
|---|---|---:|
| `codex-exec-server::capability_discovery` | `sandboxed_discovery_batches_roots_without_combining_different_permissions` | 0.101s |
| `codex-exec-server::file_system_unix` | `sandboxed_file_system_helper_finds_bwrap_on_preserved_path` | 0.079s |
| `codex-network-proxy` | `http_proxy::tests::http_connect_accept_defers_brokered_host_mitm_until_protocol_detection` | 5.279s |

前两项原日志记录真实 helper 在 loopback RTM_NEWADDR 初始化失败；第三项记录 direct CONNECT policy fixture 得到403 `blocked-by-allowlist`。本组保留原失败，不把后来独立诊断或未资格候选写成这次通过。

## r23 旧不通过用例的逐ID交叉核对

r23 的原8个不通过块已从闭合原件精确恢复并单列为补充证据。本轮6个通过、2个仍失败；本轮第三个失败不在此前8项不通过集合中。下表来自本轮完整原日志的唯一ID和原r23块，不是重新运行：

| binary / 测试 | r23 | r24 | r24原耗时 |
|---|---|---|---:|
| `codex-cli::exec_server` / `local_exec_server_flushes_telemetry_on_stdio_disconnect` | FAIL | PASS | 0.085s |
| `codex-exec-server::capability_discovery` / `sandboxed_discovery_batches_roots_without_combining_different_permissions` | FAIL | FAIL | 0.101s |
| `codex-exec-server::file_system_unix` / `sandboxed_file_system_helper_finds_bwrap_on_preserved_path` | FAIL | FAIL | 0.079s |
| `codex-external-agent-migration` / `service::tests::plugins::marketplaces::import_plugins_infers_external_official_marketplace_when_missing_from_settings` | TIMEOUT | PASS | 0.043s |
| `codex-network-proxy` / `mitm::tests::mitm_policy_allows_matching_hooked_write_in_full_mode` | FAIL | PASS | 0.006s |
| `codex-network-proxy` / `http_proxy::tests::http_connect_accept_blocks_hooked_host_in_full_mode_without_mitm_state` | FAIL | PASS | 0.006s |
| `codex-network-proxy` / `mitm::tests::mitm_policy_blocks_hook_miss_for_hooked_host_and_records_telemetry_in_full_mode` | FAIL | PASS | 0.007s |
| `codex-network-proxy` / `mitm::tests::mitm_policy_blocks_encoded_path_traversal_for_repository_allowlist` | FAIL | PASS | 0.008s |

完整行号、原字节offset和旧块SHA见 [交叉表](readback/R23-FAILURE-TRANSITIONS.json)。本次附件工作没有重新解析r23完整工作区日志；其8块原始身份及自身字节hash已核验。

## 可复核入口

- [闭合结论](CLOSURE.json) 与 [独立读回](INDEPENDENT-READBACK.json)。
- [原归档](checkpoint-r24-closed.tar.gz) 保留249个regular成员、248条原INDEX及全部194源码和双锁；没有重复复制源码树。
- [原INDEX](original/INDEX.json.gz)、[逐成员映射](ORIGINAL-MEMBER-MAPPING.json) 与 [原件到附件映射](SOURCE-DESTINATION-MAPPING.json)。
- [完整原测试日志](original/evidence/native-source50-project-r24-tests.log.gz)、[原测试回执](original/evidence/native-source50-project-r24-tests-receipt.json)、[原资源](original/evidence/native-source50-project-r24-tests-resources.txt) 和 [原失败块索引](original/failure-blocks/INDEX.json)。
- [原执行runner](original/input/native-run-r24.py)、[固定源码清单](original/input/native-candidate-r24-source.json)、[原基线](original/input/source50-four-package-r23-baseline.json.gz) 与 [根AGENTS](original/guidance/AGENTS.md)。
- [根独立归档读回](root-review/ROOT-ARCHIVE-READBACK.json) 原字节保留；本组另从原日志重算并与其完整结果集合逐项匹配。
- [压缩往返核验](GZIP-ROUNDTRIP.json)、[二进制登记计划](BINARY-PLAN.json)、[全部附件清单](ATTACHMENT-MANIFEST.json)。

大文本采用 filename为空、mtime=0 的gzip，并逐项验证解压结果等于原字节。归档transport mode全部为0600；这不等于源码原Git mode。原Git mode按固定源码清单保留，194份文件的实际字节SHA256和Git blob均重新计算。本组不冒称独立重建了完整Git tree。

资源记录使用每阶段原 `/usr/bin/time`；共享文件系统余量不能相减当作本任务独占消耗。所有源、原回执、失败块、历史字段均未修改。科学HOLD与DENY_ALL不变。
