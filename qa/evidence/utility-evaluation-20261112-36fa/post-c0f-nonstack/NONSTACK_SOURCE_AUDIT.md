# Two actual c0f failures: fixed-source review and separate fixture preparation

## Scope and observed execution

This review uses the actually tested source `c0f78493f815780f68b9bf5e390a21314d79311f` (tree `313ee34febc8ccc54c611ab56286e289518c63cb`), fixed upstream `a96d1b821d10ed3d9e99dd06c5141f9f242ae318` (tree `f96bebefbc1e7d8187efadb62f88d524cdd18451`), and the separately composed c0f+a96 baseline tree `7d26396020a11227914948be902fb3721084630c`. It does not follow a live upstream branch.

The original JUnit is Git blob `96d5b747e0579ff70730a89f70eb7ae3b70dd479` (49,808 bytes, SHA256 `e1e7901986fef0bb4a682156d87eef31b93a54f7e8759e564966dac136e198e7`). Root's separate classification is `9f876775e386e4f9ca51e8c9ca5f429fd0d72331`. The two actual results are:

| Original case | Original result | JUnit duration |
|---|---|---:|
| `runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::original_evaluation_accepts_unsorted_source_policy_without_reordering_its_bytes` | `Error: InvalidBinding` | 12.044 seconds |
| `runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::q24_next_use_command_readback_refuses_actual_publication_withdrawal` | `Error: OwnerUnavailable("original learning evidence owner")` | 8.949 seconds |

Neither case's XML contains a backtrace or an exact Rust failure line. This review preserves that limitation. It does not attribute a runtime line from the error text alone, report another execution, or transfer c0f results to a prepared source.

The original c0f inventory was independently restored by root from retained bytes: 5,474,911 bytes, SHA256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57`, computed Git identity `5ed18452e2e967281ac368f934b9e4358627b9d3`. Its source header names exact c0f, its status is clean, and the source pins below match index and working blobs. This is an inventory identity check, not another filesystem observation or test run.

## 1. Unsorted policy: a deterministic fixture precondition still fails

There is a concrete, independently source-provable refusal in both c0f and a96. It is also present in their composed baseline.

1. `circuit_cell_test_support.rs::definition` defines the complete original candidate vector in order `[a, b, abstain]`.
2. `circuit_cell_tests.rs::configuration` creates the corresponding complete route objects in the same order. The objects are `a -> Succeeded/[done]`, `b -> Succeeded/[slow]`, and `abstain -> Abstained/[]`.
3. `circuit_original_evaluation_source_support_tests.rs::BFixture::populate` implements `ObservationMode::NonCanonicalOrder` by sorting the actual input masks in descending candidate-ID order, both for history and held-out targets. It explicitly asserts a descending pair.
4. `circuit_original_evaluation_task_support_tests.rs::original_evaluation_source` correctly preserves the original candidate-to-activation mapping and rebuilds `definition.candidates` in the complete actual input order. However, after `configuration()` it only replaces `bindings[0].cell`; it leaves `bindings[0].routes` in the old order.
5. Production `circuit_cell_binding.rs::CircuitCellRegistryV1::new` compares route IDs and definition candidate IDs position by position. Lines 102–107 of blob `d67f5a628c1729105205564df359ec154240747a` reject any mismatch with `CircuitCellErrorV1::InvalidBinding`. Recomputing the route-policy digest does not align the route vector or waive this predicate.

Consequently this fixture cannot construct the intended original unsorted source using that inconsistent binding. This establishes a deterministic source refusal; the actual XML still does not identify whether the observed run reached this exact line or encountered an earlier refusal.

### What fixed upstream changed

Upstream a96 changes candidate lookup in the helper from repeated vector removal to a `BTreeMap` keyed by original ID and adds original-policy ordering assertions. It does not reorder the route vector. The composed baseline retains c0f's complete candidate-count check in addition to the a96 lookup. The original failing test method itself is byte-identical across all three versions.

### Separate minimal prepared correction

Only `codex-rs/hepta-agentd/src/circuit_original_evaluation_task_support_tests.rs` changes. The independent patch adds 18 lines after `configuration()`, before replacing the cell and recomputing the original route-policy digest. It takes the existing complete route objects into an ID map and moves each original object into the actual definition's order. It checks original count, uniqueness, missing IDs and complete exhaustion. No route's outcome or selected edges are reconstructed or changed.

The helper's original candidate set/order checks, activation swap and selected ID are retained. Its two existing `pretty_assertions::assert_eq!` calls remain byte-for-byte intact. The production registry predicate, input bytes, actual source publication, policy extraction, receipts, signatures, thresholds and authority are unchanged. No test is removed, ignored, filtered or rewritten to expect a weaker result. Existing canonical and noncanonical provider cases remain the relevant real regression inputs.

| Prepared artifact | Git blob | Bytes | SHA256 |
|---|---|---:|---|
| Exact postimage | `bc7be5dd406bb4da8afda7a9fd9df06cda2cece0` | 5,395 | `47d5369b7021820692819215f27e8b17b1ffde2cf5f1f656d916c4d2c99ab030` |
| Exact one-hunk patch | `fde4f2fd5123f8727ce97e1a851efccbfc4246ae` | 1,340 | `8163972cb4addb3046188f887e972cec521fdb54238e75390aeac4ea4fbea248` |
| Full before/after packet | `ed23fa728a2a61b3c8a171983e6e8578b073a359` | 14,326 | `5ee1dd1d14aaccccc75519150bc4ca99763ea92ff16d1579fecda3616896a8b8` |
| Manifest | `dfd30e0e1471c5bd8f4dd74fca42dedee99e36bd` | 2,933 | `0cf9e2594d9e4fe614f38dea6edcae1a23998aba027ec3334382e54a22fdac50` |

Each listed blob was created as immutable content and then read back in full with exact text equality. The required preimage is composed helper blob `bdfdc2f72241589983b33a01dc8d8d101b3c40bf`, 4,567 bytes, SHA256 `6238d49f05923e67628db58ebfb646d2b3e19778a58d5c6c92b95fb6f3c599c4`. Applying this patch requires the actual target's entire bytes and both hashes to match that preimage. A differing target must be reviewed and merged, not overwritten.

Status: prepared in an isolated directory only; not formatted, compiled, executed, integrated or published as a source ref. The frozen 59-Rust ordinary-profile package remains unchanged. No behavioral PASS is claimed.

## 2. NextUse withdrawal: upstream adds diagnosis, not a proved repair

The reviewed original path is a real prior C publication and original Observer command/evidence owner. In the test, actual C completes, the original Observer attests it, and an evidence connection reads the original completed receipt. Only after that successful read should the test withdraw the original Version publication and require both original evidence and command readback to reject. It also preserves original owner bytes and verifies original server request counts and teardown.

In fixed a96, `circuit_next_use_command_owner_tests.rs` adds a diagnostic around the first direct evidence read. On its error, it preserves the original error and elapsed time, drops that evidence client, joins that original evidence server through `spawn_blocking`, and returns all three facts. It does not send another request, create a replacement channel, extend the evidence timeout, skip withdrawal assertions, or change the success path.

The next-use evidence client fixture, original evidence client, original evidence service and original command service are byte-identical between c0f and a96. In `circuit_next_use_receipt_owner.rs`, the only c0f→a96 change is replacing an already explicitly typed `trainer.readback(...)` with `LearningIterationEvidenceClientV1::readback(trainer, ...)`; receiver, arguments, await and behavior are retained. These changes do not establish a functional fix for the observed failure.

`learning_iteration_evidence_client.rs::readback` deliberately maps several different failures to the observed owner-unavailable error: channel lock/take/request exhaustion, transport read failure, response correlation mismatch, and final lifetime/channel restoration failure. Its `unavailable()` helper supplies the exact error text. The XML does not distinguish them. The original endpoint's 500 ms exchange cap is still explicit in `circuit_next_use_command_service.rs::serve_evidence_readback`, and the actual fixture uses 500 ms on both sides. The observed total test duration is not a measurement of that exchange and does not prove timeout.

The original server's `evidence_response` reads its fixed actual C owner and live predecessor peers, authenticates the exact original receipt and returns the existing signature. It cannot execute/attest C through this evidence purpose. It maps inner failures to the original framer's invalid-request error. A client-side generic error alone cannot identify the inner rejected invariant.

### Required evidence before a functional repair

Keep the fixed a96 diagnostic in the composed candidate. When the new exact source is legitimately executed under the original test budget, preserve the entire original test output, the first evidence read's exact error and elapsed time, and the joined original server result. If the failure occurs before that diagnostic, retain the exact failing stage/backtrace or add an isolated stage context without changing behavior. A server error may still require a narrower original-owner failure context before any production change is justified.

No additional NextUse source patch is prepared here, because the currently available evidence does not establish a specific functional defect. The status is **unresolved/Unknown**, not fixed, and not evidence of fraud or a complete negative comparison. No retry, new authority, deadline change or assertion weakening is proposed.

## Source identities

All paths below are under `codex-rs/hepta-agentd/src/`. The companion `SOURCE_PINS.json` records the original inventory's index/working match and the fixed a96/composed identity for each file.

| Path | c0f blob | a96 blob | Composed baseline blob |
|---|---|---|---|
| `circuit_original_evaluation_task_support_tests.rs` | `9505db2dcf4d62cc1b80d586f88a8a3c3c5a2749` | `5a462fab5c7b93038596953957434c52e62a00ee` | `bdfdc2f72241589983b33a01dc8d8d101b3c40bf` |
| `circuit_original_evaluation_provider_tests.rs` | `a42826fa67ed1c598916c3bd9046dfd255e64280` | `a5fadf41d93333097f9b3613e07f9ca705f36223` | `c1cf7010e8dcc20a29f821a5e6eb46715340cd6f` |
| `circuit_next_use_command_owner_tests.rs` | `5c1958b2ab3e8d552a0d82d1a6f0e8ec059f2cae` | `0169864d8a5743a1ce00eacf293392a118026d8d` | Same as a96 |
| `circuit_next_use_receipt_owner.rs` | `467831627aaf7833f035804b3c94629739b3a981` | `23e8989ebd2644947b15c80ab9c641a70767de99` | Same as a96 |

The following pins are identical in c0f, a96 and the composed baseline:

| Path | Exact Git blob |
|---|---|
| `circuit_cell_tests.rs` | `a2256001fb5a8c5fd3b2e22b0586e5240669f3ff` |
| `circuit_cell_test_support.rs` | `5428558e44bb9ee3116ac1d0ab372d2d74e4f93b` |
| `circuit_cell_binding.rs` | `d67f5a628c1729105205564df359ec154240747a` |
| `cell_q24_dataset_source_test_support.rs` | `60491689bfdfdb2d4e9551bc6a91aa2d22c7259d` |
| `circuit_original_evaluation_source_support_tests.rs` | `a2fefd967723c342e51784b0b0aafbadff4fbfb6` |
| `circuit_next_use_command_support_tests.rs` | `901c0a2fdfb475d4f09477a273a00fe437d47393` |
| `circuit_next_use_command_evidence.rs` | `b3aaf6c65e0cc9f84a2c076aca6bc22f04c5225c` |
| `circuit_next_use_command_service.rs` | `01b1f7d02600b16eba09c581e1dab831b7c9e248` |
| `learning_iteration_evidence_client.rs` | `443bfc37618c2ca04e0d9ef301a45f9471ca8c17` |
| `learning_iteration_evidence_wire.rs` | `3a83d75c9fd2ca470a173bb2eb7a7152efc42b51` |

## Verification limits

Completed here: exact source reads, full Git/SHA256 identity checks, fixed-version diffs, direct inspection of original registry and evidence predicates, immutable blob publication/readback, and preservation checks for the independent one-hunk correction. No Rust test, compile, formatter, caller gate, desktop operation or source ref mutation was performed. The original c0f failures remain historical failures. Future runtime acceptance must belong to the eventual exact frozen source, with its own raw output and inventory.
