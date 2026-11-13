# Four reviewed repairs after the consumed fix, then the original formatter

Status: prepared for Root's exact-request review. No new H process, staging operation, source write, formatter, test, or ref update has been performed under this plan. The execution-candidate config contains the two proposed approval values solely so Root can review concrete immutable request bytes.

## Actual starting point

The completed maintenance job `1a1d3eccd3a-392-231` had a normal supervisor exit of 1. Its one scoped `just fix` command returned 101, without timeout or output-limit termination. The formatter was not attempted and no behavioral test command was dispatched. These facts and their cost remain part of the evidence chain.

The native checkout is `/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1`. Its detached HEAD is `0c59aaca0b4932507f068c723f73da2f96729b3d`, committed tree `4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09`, sole parent `cc57c7198db6293ccca562253c42fffbe2a04633`. Its 15,237 current physical source leaves have tree `4ed32552042fee522965ea54caf95bbebb31ad43` because the failed fix actually changed `codex-rs/hepta-learning-ledger/src/witness.rs`.

The complete actual final inventory has 5,629,749 bytes, SHA256 `b19022cb0957b760703a1193f20b0c2934738e68f7c0cf6956fab34468c41dfa`, and Git blob identity `d7e2e31df4c8d463b643874bdcd11309a1df02f4`. Its locally available exact reconstruction matches the native raw/gzip/all-five-part identities. It is described as an exact reconstruction of previously observed producer bytes, not another native full-inventory transfer.

The full 2,642-byte original Git metadata before/after bodies were actually read and are identical: SHA256 `7549fff731bd055a4dbe895bb0a37fa2486a6e2818e302e8af89495436d704e4`, Git blob `d13c50e149ba23ff1acbd0f99b29669131c1312b`. The index is still 2,079,344 bytes / SHA256 `50bdaa37fe419d29ac53fb52cbf984db4a69d10cfbfc6e92786c8ca1892c4051`. The new control compares original raw metadata bytes and uses Python integers; no JavaScript numeric reserialization is used for nanosecond values.

## Why there is no second fix

The actual captured AGENTS file, blob `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a`, requires the scoped fix for a large Rust change and formatting after code changes. Its text does not itself define a failure retry. The separately frozen maintenance contracts `50c0a5eabfcab306dc84111fa1f67318267c08ae` and `56ff9b0019da0e2b9d4c49189ef170acd13eb45e` define the original single fix stage, stop on failure, and require concrete successor approval. The original 7,200-second fix allowance was consumed by the actual attempt; its failed result cannot be refunded or reclassified.

Root selected the narrower successor: preserve the actual witness postimage, apply the four reviewed source repairs, and attempt only the previously unrun original formatter. This plan does not claim successful Clippy maintenance. Qualification of the eventual final source is a separate future operation; no prior cc57 source PASS or test result is transferred to this new source.

## Exact manual application

The input is ordinary's complete frozen repair proposal `12a664ce2905feb8107ae66b303c4975f17a9fe3`, 152,573 bytes / SHA256 `84b79dd4fc36e070f57f3de05982cd7a55130b5af67f7890a98ad187a1219300`. The four manual paths are:

- `codex-rs/hepta-agentd/src/authority_host_learning_resident_provider_transport_tests.rs`
- `codex-rs/hepta-agentd/src/circuit_original_evaluation_fresh_training_support_tests.rs`
- `codex-rs/hepta-agentd/src/circuit_resident_candidate_first_material_support_tests.rs`
- `codex-rs/hepta-agentd/src/circuit_resident_candidate_provider_unstarted_material_tests.rs`

Each is an existing tracked 100644 file. Both full before/after content and its three-part identity are fixed. The fifth HEAD delta, the actual witness postimage `a45cfde5e0d6c17a8b9502f66c43979f26f6bc4d`, is read and protected verbatim during this manual application. It is not reapplied. The complete expected tree immediately after the four writes is `1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1` with 15,237 leaves. This is an expectation until actual execution verifies it.

The unchanged original application procedure records each attempted write and sibling temporary path, verifies the original bytes immediately before replacement, fsyncs the new file and directory, then records the observed result. An incomplete operation retains its actual partial state. There is no rollback, reset, checkout, index edit, HEAD movement, ref change, dependency installation, or automatic retry.

## Reused control and budgets

The thin driver is `0938761e369ddfa215da98b70423cfd5d48ac819` (34,454 bytes). It derives from the actual earlier apply-plus-format driver `9101b44fb2ab24ae41a1344425dd74b536a40de4`. The full functions `identity`, `first_read`, `lock_identity`, and `main` are byte-identical. The underlying maintenance module `3a0f6dec8127aa9587129d6e0f24bad55837ca13` (68,496 bytes) and its actual configuration `d27dd8ee763c75eb5a0f195bb034fc9ca32b727e` remain unchanged.

The module is loaded for its original helpers, environment guard, recorders, full-source capture, and one formatter stage. Its original main, fix stage, clean-materialization initial preflight, and behavioral-test entry points are not called. Historical materialization proof validation is kept separate from the newly observed dirty working-tree baseline.

| Scope | Unchanged allowance |
| --- | ---: |
| Live preflight and four-file application | 600 seconds |
| `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` | 900 seconds |
| Shared source/input/failure recording | 300 seconds |
| Outer combined request | 2,100 seconds |

The original complete c0f formatter-base identity check remains. The original runtime/tool/material validation, current complete V8 bytes, existing target directory, 32 GiB free-space requirement, same-UID active-build/formatter rejection, source-entry checks, stable reads, and strict raw Git equality remain. A prior quiet process observation is not treated as a lease.

## Single lock and the combined launch

The proposed key is `hepta-utility-36fa-provider-0c59-fix101-apply-fmt-v1`. The request has exactly the seven original fields: host, executable, args, cwd, stdin, timeout_seconds, and idempotency_key. It uses desktop, `/usr/bin/python3`, `-B -c`, `/home/qian-qi`, 2,100 seconds, and no environment override.

The new control directory is `/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-fix101-apply-fmt-v1`. The combined bootstrap validates all four payloads in memory, creates this fresh directory, writes each file with O_EXCL/O_NOFOLLOW, fully reads back the exact regular 0600 bytes and stable metadata, records its actual bootstrap/argv/payload, fsyncs, and execs the thin driver. Existing controls or an unexpected input cause rejection; no renamed attempt is created automatically.

The four staged inputs are the thin driver, proposed formal config, unchanged repair proposal, and the original failed-maintenance supervisor. The proposal uses the original bounded gzip transport. The actual payload is 77,588 bytes and complete typed request 83,679 bytes, both below the existing 1 MiB transport cap.

The bootstrap neither opens nor locks `SOURCE_COORDINATION.lock`. The unchanged thin main is the only new holder: it opens and takes LOCK_EX|LOCK_NB on the original fixed inode, retains it through application, formatter, and final audits, verifies it again, and closes it. There is no second inherited lock description that could self-conflict. The lock coordinates cooperating writers only; full-source and raw-Git checks remain mandatory.

## Actual evidence required after a future execution

First report actual admission and authoritative supervisor status promptly. Then preserve complete stdout/stderr, the actual bootstrap/argv/payload and four-file readback, the EX lease, original failed-fix proofs, current full preimage inventory, raw Git metadata, four application records and actual postimages, formatter execute_logged record and terminal, full formatter log, final complete source inventory/postimages, input identities, read-only command journal, and all final audits.

The new producer format is `hepta-fix101-repair-format-result-v1`. Its expected success status is `APPLIED_AND_FORMATTED_REVIEW_REQUIRED`, not the old maintenance success status. Even an actual normal0 result still has qualification=false and freeze_approved=false. A known formatter failure or uncertain cleanup/retention remains failed or Unknown with all actual changes retained.

The consumer contract is separately frozen in `SUCCESSOR_CONSUMER_CONTRACT.HOLD.json`. A future consumer must verify the failed original fix as failed101, the exact four manual repairs, and the new formatter's actual normal0 proof independently. It must not manufacture a fix0 result to satisfy an older successful-maintenance schema. Formatter changes require actual-byte review and corresponding fence/registration synchronization before any final source freeze. The final source gates and unchanged original fourteen native phases require their own actual final-source binding and exact authorization.

## Completed preparation checks and limitations

The pure proof-schema audit `722bfc6c4e726a29133d181f2118731e74ca0b3f` passed against the complete retained actual failure records. The complete mode-aware 15,237-leaf pre/post application projection matched 4ed/1eacf. This executed only selected pure parsing/Merkle helpers over frozen cloud data, never the driver main, preflight, H command, formatter, or tests. The first audit helper's missing `pathlib` namespace failure is retained; its v2 namespace correction did not alter the driver.

The exact launch static review `02555074403188c748bc44f3a0fe311a59d5a5f0` proves the candidate config's two changed approval leaves, the bootstrap's full inverse to its actual 9101 ancestor, the unchanged four helpers and exec tail, all four decoded payloads, single-lock responsibility, and seven-field request shape. The candidate request `b63bd0d12684a3ba39e63f1f12fef56cb56cb3d9` remains non-executable until Root grants its exact engineering approval.
