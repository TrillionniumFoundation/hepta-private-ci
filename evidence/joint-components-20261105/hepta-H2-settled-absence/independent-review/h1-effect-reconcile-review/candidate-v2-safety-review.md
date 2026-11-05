# Independent review of the H2 settled-absence v2 candidate

## Result and exact reviewed bytes

No concrete production semantic or Rust interface blocker was found in this source review. The candidate repairs the observed H1 recovery-read defect while retaining the current PQ dispatch, generation, nonce and active-effect-fence paths. This is a static review; formatting, Clippy, compilation, the two new controls, and the unchanged original PQ controls have not been executed on this candidate by the reviewer. H1's original 9/2 result remains a failed gate.

Reviewed patch: `settled-absence-v2.patch`, 23,927 bytes, SHA-256 `906788c15547a5a21f0f90bcfc95f45d4aa25d163a83a51d29981c3919adba7e`. Implementation manifest: `patch-manifest-v2.json`, SHA-256 `36a901c3a2e1e3f9bc73fad53841d8b2aefd917a5ecf1dda1f98988e72ed1bce`. Base is exact H1 `9f785cb201ba12ab0ae0f0d341c0f7912cc65efc`, tree `24804b21d0306b617e12fa3f5b9454a12ed4ad41`.

The reviewer independently fetched the base files, verified their raw Git blob identities, copied those exact bytes into an isolated local directory, applied the patch, and verified all four resulting files against both the candidate and its manifest. `patch-v2-identity-check.json` records this check. These Git operations are not native validation.

| Changed path under `codex-rs/` | Reviewed new Git blob | Reviewed new SHA-256 |
| --- | --- | --- |
| `hepta-automation/src/authorized_effect.rs` | `b596b9061737a7bc8387807af27fdf5d2e230956` | `c9d2247573cc205b66366d40cfc4d15872d65db0122c66e324e9371b9dcd20d4` |
| `hepta-automation/src/taskflow_step.rs` | `43c7df417047b4295b7120c8dbcba7357504d151` | `4839aa3abbdafffdf2b542efa990972050964a7d837cd04620f99b9a366014be` |
| `hepta-agentd/src/automation_effect_host.rs` | `c11b1c06bdd5690fc48e49f3106a5f9916c90dd3` | `f11950fe8a5f8a4e33425a7aec68ac0e4a872b60f341e11de306815ef280b2df` |
| `hepta-automation/tests/support/authorized_owner_recovery_tests.rs` | `12cabc35fd44816ec7c6913a9a47d9b03cda5990` | `ab1920270a169e4b82bdef1fe4c02626731d4bce19398877cf0e809878566fa5` |

## Evidence and owner binding

The new public store method first uses the existing provider-ledger decoder and requires `EffectDispatchObservationKind::ProvenAbsent`. Missing attempts, missing observations and other observation kinds return no settled-absence fact. The private step reader then verifies the complete current run history, the immutable definition/node and the exact `(owner, run, step, attempt)` step chain. It requires `Reconciled`, `Cancelled`, and a step receipt digest equal to the provider absence proof.

The method locates the exact historical `effect_command_id("requeue-absent", durable)` event, rather than inspecting the last event or inferring absence from `Queued`. The owner/run/command query is parameter bound, uses a fixed SQL literal, and reads at most two rows so duplicates are rejected. It verifies the transition name and deserialized `RequeueProvenAbsent` payload against the proof. Numeric conversions and checked subtraction reject invalid timestamps/revisions and a zero revision.

The original command digest is recomputed using the original step's fence, the event revision minus one and the event's recorded timestamp. This is the same JSON serialization and SHA-256 construction used by `TaskFlowCommand::digest`; it binds the historical settlement to the immutable original owner tuple. The public wrapper additionally checks the durable intent digest, payload digest and exact cancellation-command identity. Direct pre-contact cancellation and cancellation of an earlier indeterminate step have their separate existing command domains. A previously succeeded/failed step cannot become absence.

The full run history, exact step chain and historical settlement event are read in **one step/run SQLite transaction**. The provider ledger is decoded in an earlier, separate transaction by `effect_dispatch_attempt`; the candidate relies on the existing append-only terminal observation/reconciliation semantics for that fact to remain stable. This is not one transaction across all ledger reads, and it is not an atomic snapshot across the automation database, FinalUse owner, external frontier, or provider. No such stronger claim is made.

The new helper reuses the existing schema initialization guard. It does not append or mutate workflow/effect evidence, restore or consume a nonce, issue a token, renew a lease, or contact a provider. As with the existing readers, the schema guard may create missing schema objects before the read transaction; “fact read” describes the data/authority boundary, not a new guarantee that a physically uninitialized database can never receive DDL.

## Preserved authorization paths

The Agentd change is an additional local fact read immediately before the old `owner_fence` reconstruction. Its existing pending-attempt owner and destination checks still occur first. Only a verified settled-absence receipt causes the early `ProvenAbsent` return. Unknown, unobserved and partially settled cases proceed to the existing fenced path or fail; no provider status request is made by the new branch.

`execute_at_boundary`, `execute_ordinary`, grant claim and nonce persistence, the driver callback after the durable store await, current generation admission, PQ signed-feed validation, contract epoch, external frontier checks, and `with_verified_effect` are unchanged. The host's live/current owner reconstruction is unchanged for paths that need it. Neither current PQ nor the active-effect fence is bypassed to perform a new effect or external lookup. The patch does not add an owner fallback, use a caller-supplied fence for fact reads, synthesize a root/key, change a signed domain, or change provider operation identity.

The existing `read_verified_step_tx` decision block for an explicit fence and for the no-fence completed-run reader is byte-identical. Only its shared immutable loading and verification body is extracted. The new absence reader has a separate explicit boundary; ordinary queued runs and arbitrary cancellations are not made terminal. A legitimate later claim/start does not erase the verified old attempt's fact. This is historical information for the requested attempt; it is not a declaration that a provider key has never been used by any later attempt.

## New controls and original assertions

Exactly two integration controls are added to the existing `authorized_effect` test binary's `owner_recovery_tests` module:

1. `settled_absence_fact_read_survives_reopen_and_new_owner_without_redispatch` covers both direct pre-contact absence and indeterminate-to-owner-proof settlement. It checks queued state with the whole old lease tuple cleared; the original cancelled immutable step/fence; store reopen; a legal generation-2 claim and Start; unchanged newer run after reading the old fact; rejection of redispatch of the old attempt; driver call count 1 and consumed nonce count 1.
2. `settled_absence_fact_read_rejects_unknown_unsettled_and_corrupt_evidence` retains unknown as unknown. A real INSERT trigger prevents the run requeue after the absence record and cancelled step have been persisted, and the new reader must still return no fact without changing the run. Separate fixtures then inject proof, intent, payload, fence and settlement-time corruption. Each first demonstrates the existing immutable UPDATE trigger rejects the operation, then explicitly removes that trigger for the fault injection and verifies that a row actually changed.

The timestamp case is especially relevant to the added binding: H1's legacy run-event hash does not include `recorded_at_ms`. That mutation must therefore fail at the new exact command/fence comparison, with the expected specific error, rather than claiming coverage from an unrelated old event-digest failure. The other corruptions retain the existing history-verifier rejection boundary. They do not establish resistance to every possible coherent rewrite of an entire database.

The original owner-recovery test function is byte-identical. The original Agentd PQ test file, SHA-256 `7645fc19a734b2ffbbc5ecdb7001069e29f41e9aef3249fc0a5f383ed0e99a78`, is excluded from the patch, so both observed failing controls and all of their assertions remain unchanged. The v2 SQL calls use literals, including each mutation and trigger-drop branch; no SQL string is constructed from the fault label.

These two new controls use the existing explicitly classical automation fixture to exercise the store/owner contract. They supply no independent PQ credit. The unchanged native Agentd controls must prove generation refusal, consumed nonce retention, settled absence readback, later signed revocation refresh after fence release, and no HTTP contact on the new committed candidate. The real-process and remaining original gates also retain their own source/binary requirements. The full H1 native result cannot be carried over to H2.

## Remaining qualification boundary

This review supports proceeding to the required formatter/compiler/native gates on an exact committed successor source. It does not grant a native PASS, a complete recovery qualification, a current-PQ bridge for all generic tools/providers, or a long-run resource/service qualification. If formatting or a native fix changes the candidate bytes, the final evidence must identify that resulting source and executed binary, with any further semantic delta reviewed before claiming closure.
