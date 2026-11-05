# 原四包测试的追加逐名审计清单

`required-tests.with-e65.json` 保留原 `required-tests.json` 的全部 49 条记录原样，并追加新统一基线 e65 的 10 项消息输出回归。合计 59 项，仍然只是完整四包结果中的必要审计子集；原 `just test` 保持无 filter，重试、超时、profile 均不改。原 49 项清单的 SHA-256 为 `16f15023d778b5c230c47f8ca934a434f522856622e6b9760630a10380d9af50`，追加版为 `f832236003c1937c29ba9ca3f6faeafa2dc9799664ae1069d0df78339366f56e`。

新增用例的 package 为 `codex-hepta-infer-worker-host`，binary 为 `codex_hepta_infer_worker_host`，module 为 `native_app_server::tests::message_output`：

- `complete_only_message_is_observed_only_for_the_bound_turn`
- `completed_snapshot_replaces_partial_text_without_double_counting`
- `distinct_item_ids_preserve_identical_message_text`
- `item_start_order_survives_later_item_text_arriving_first`
- `terminal_summary_merges_last_message_without_dropping_earlier_messages`
- `interrupt_grace_keeps_item_identity_and_cannot_restore_cancelled_authority`
- `oversized_complete_item_preserves_previous_output_and_pending_state`
- `empty_items_cannot_retain_unbounded_metadata`
- `conflicting_completion_or_late_delta_cannot_change_a_completed_item`
- `oversized_terminal_snapshot_cannot_authorize_completion`

全部原 10 个测试叶名及 30 个断言保留。测试文件只适配已有 accumulator、事件 helper 和 metadata 测试 API。最终 formatter/Clippy 后对冻结 commit/tree 运行 `bind_required_tests_manifest.py --review-manifest required-tests.with-e65.json ...`，生成独立 schema-v2 execution 清单，然后将原真实 JUnit 交给未改动的 `check_required_junit.py` 审计。源码绑定、构建及 lint 都不表示这些测试已执行。
