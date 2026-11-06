# Core r8c 闭合失败分类

源码树：`6d88ca9c8964669a408d8549efaeff7b94d68674`。原命令：`just test --locked -p codex-core --retries 0`。原 strict 退出 0，原 tests 退出 100。

**计数：3,824 个唯一执行测试 = 3,608 PASS + 206 FAIL + 10 TIMEOUT；另报告 9 skipped。** 日志末尾 216 条失败复述已去重。测试阶段 820.471 秒；原命令含构建 1,142.0338122844696 秒。

以下按日志实际错误签名分组，并不代表每组已经证明同一根因。每个不通过测试的完整 ID、错误签名、panic 位置和证据行，见 `core-r8c-failure-classification.json`；原日志完整保留。

| 观察分组 | 数量 |
|---|---:|
| `other_state_or_request_assertion` | 6 |
| `provider_private_metadata_projection_assertion` | 6 |
| `stream_fd_EPERM_output_contamination` | 5 |
| `nextest_watchdog_timeout_no_further_cause` | 10 |
| `explicit_missing_helper` | 108 |
| `other_code_mode_result_or_tool_contract_assertion` | 28 |
| `code_mode_result_JSON_parse_error` | 8 |
| `code_mode_exec_dispatch_rejected` | 6 |
| `expected_second_result_missing_index_panic` | 9 |
| `code_mode_host_spawn_ENOENT` | 1 |
| `internal_event_or_turn_deadline` | 22 |
| `wiremock_expectations_unmet_no_explicit_helper_signature` | 7 |

显式辅助程序证据涉及 109 个失败：108 个 metadata 缺失（stdio97、codex9、code-mode-host2）加 1 个 code-mode-host fallback spawn ENOENT。stdio97 包含 8 个先打印内部“skipping test”后触发 wiremock 断言的失败；这些没有被记成 nextest skipped。其余107个不通过没有这些明确签名。

原七包17 skipped 的补充仅是静态源码/cfg身份审计：14个直接ignore加3个非Windows条件ignore，与原日志总数一致；没有伪称原日志逐例SKIP，也不能用于推断Core的9个skip。

已核全部110个归档成员：109个manifest载荷（82源码、27原证据）逐项SHA/size通过，82源码Git blob通过，6组receipt/log/resources退出码一致。tar导出权限0600与声明Git mode100644分开记录。没有读取活动r9日志、执行Rust或修改源码。
