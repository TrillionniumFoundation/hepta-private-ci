# Shared-pool tiny tokenizer fix

Actual preparation reached the CPU numerical gates after the original runtime
was restored. WarmStart passed; the shared-pool A/B/A test failed because its
generic `PreTrainedTokenizerFast` emitted `token_type_ids`, which Qwen2 generation
does not accept. The original failure is preserved with its raw SHA-256.

The only behavioral change sets the tiny fixture's `model_input_names` to
`input_ids` and `attention_mask`. Production prediction, pool behavior, resource
admission, numerical assertions and skip rules are unchanged.

The real tiny CPU A/B/A test then passed: one test, zero errors, zero failures,
zero skips, 16.088 test seconds. Its original base-sharing, adapter hash,
logit identity, mutation rejection and cleanup assertions all executed.
Required `just fmt` passed; formatting changed no AST. Raw before/after records
and the tested/formatted source hashes are bound in `RECEIPT.json`.

This is an engineering fixture repair. It adds no independent sample or model
task result. The original failed preparation remains intact; a new source and
run identity must pass the full preparation gates before experiments proceed.
