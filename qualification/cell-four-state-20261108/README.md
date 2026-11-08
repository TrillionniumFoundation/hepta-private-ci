# Four-State Separation: Candidate Qualification

Status: **Scoped native qualification complete; production and scientific acceptance remain separate gates**.

This delivery hardens two existing boundaries: recovery of fast neuron state
under an exact frozen runtime configuration, and admission/correlation of Cell
parameter-update proposals under a host-registered training policy. It does not
introduce a new state owner or make a learning proposal an authorization token.

The native test results below are bound to the exact tested tree and original
JUnit run. Final maintenance output is captured independently; repository
instructions require tests before `just fix` and `just fmt`, with no test rerun
after that final maintenance. Production acceptance remains a separate gate.

## 1. Source and execution identity

| Item | Value |
| --- | --- |
| Repository | `TrillionniumFoundation/hepta-private-ci` |
| Base commit | `1eb72a1131285f5de98beeb7c95a27eab72d647e` on `codex/cell-six-contracts-20261108-r1` (parent PR #5358) |
| Tested source tree | `b46a21456566c7336d4ca8c6cbc1a693fd53b155`; the immutable formatted tree and per-file hashes are retained in `native_summary.json` and `source_manifest.json` |
| Final source tree | `804c66439165661d60a4c79d1eb5a1087075c66a`; production source is byte-identical to the tested source, with two test files changed by maintenance |
| Qualification host and toolchain | ROG native Linux, Rust `1.96.0`, nextest profile `local`, two build/test workers; full environment retained in `native_summary.json` |
| Native focused / package test evidence | Baseline control: 2 intended regression failures. Candidate: 1,362 executed tests passed, 0 failures; runner reports 69 skipped. Original green JUnit UUID `1f83fc2e-e1bc-4f73-b5a5-af155eabeeca` |
| Formatting and scoped lint evidence | Scoped `just fix` exit 0; 0 warnings in changed owner packages, 2 retained dependency warnings. `just fmt` exit 0 via a linked fmt-only continuation. No tests were rerun after maintenance. |
| Remote publication and CI evidence | Branch `codex/cell-four-state-boundaries-20261108-2b2d`, stacked on parent branch above. This document is prepared before publication; remote CI status must be read against the published head and is not asserted here. |

## 2. State classes and their owners

These are ownership boundaries, not four interchangeable fields in a model
checkpoint. A source path is a navigation reference; its presence is not proof
of deployment, current host composition, or production qualification.

| State class | Authoritative owner / existing interface | Source references | Update and recovery boundary |
| --- | --- | --- | --- |
| Fast state: task-scoped temporal vectors, activations, thresholds and local eligibility | `NeuronRuntime` and its `SparseJournal`; scoped `CellPartitionOwnerV1` / `CellOwnerJournalV1` | `codex-rs/hepta-neuron/src/runtime.rs`, `runtime_binding.rs`, `journal.rs`, `cell_owner.rs`, `cell_journal.rs` | Commit under the admitted scope and frozen definition. Recover against the independent witness. A changed runtime configuration cannot reinterpret existing fast-state history. |
| Long-term memory: episodes, facts, skills and source relationships | `CognitiveStore` with agent/workspace authorization and the existing memory writer; learning experience is separately appended through `LedgerWriter` | `codex-rs/hepta-memory/src/cognitive_store.rs`, `cognitive_memory_store.rs`; learning handoff: `codex-rs/hepta-agentd/src/neuron_generation_episode.rs`; learning facts: `codex-rs/hepta-learning-ledger/src/ledger.rs`; derived-artifact withdrawal preparation: `codex-rs/hepta-learning-artifacts/src/dataset_revocation.rs` | A Cell checkpoint is not a memory-write credential. The memory path checks citations and uses correction CAS; correction does not resurrect tombstones. Writes retain source lineage, and withdrawal/deletion remains with its owning services and current frontiers. The learning ledger is not a substitute for the memory owner. |
| Parameters and programs: model weights, adapters, controllers and skill artifacts | `CellUpdatePortV1` proposes; `LearningArtifactOwnerService` publishes immutable artifacts; independent selection and Control current-generation owners decide later use | `codex-rs/hepta-neuron/src/cell_update.rs`; `codex-rs/hepta-learning-artifacts/src/owner_service.rs`, `cell_bundle.rs`, `selection.rs`; `codex-rs/hepta-agentd/src/neuron_generation_current.rs` | A candidate is separate from selected live parameters. This patch admits only the registered Cell parameter subset and binds the returned candidate to its complete request. It does not implement an arbitrary program-diff verifier or a new adoption path. |
| Goals and permissions: task objective, tool authorization, selection/adoption authority | Independently retained Control, final-use authority and effect owner; authenticated learning role separation | `codex-rs/hepta-neuron/src/cell_generation_current.rs`; `codex-rs/hepta-agentd/src/neuron_generation_current.rs`, `learning_iteration_auth.rs`; `codex-rs/hepta-automation/src/authorized_effect.rs`, `effect_dispatch_ledger.rs` | Learning signals, model outputs and candidate hashes grant no authority. Actual dispatch requires current final-use checks and a durable provider-attempt/observation record. Restoring model state does not erase an effect attempt, renew a grant, or establish that an effect was absent. |

Task/session prompt context remains with its existing task/session owner.
`SparseCheckpoint` does not persist every kind of short-term context, and this
patch does not introduce a unified context checkpoint.

The memory mapping was verified by reading the exact source blobs
`968199c77d8d08dd66e0569694c51d6c06f5466e` (`cognitive_store.rs`) and
`9fca56d533985f6403e4a61fba12680d50016799` (`cognitive_memory_store.rs`). That
read-only verification is separate from native test execution and deployment.
This patch does not replace the memory writer or claim memory production
acceptance. Its native library tests are included in the four-package result below.

## 3. Repair A: bind fast-state recovery to the complete runtime configuration

### Problem

The sparse kernel journal already bound the native sparse configuration,
subject and objective. The surrounding runtime also has model/encoder pins,
calibration and resource-policy fields. Recovering the same sparse journal
under different outer runtime fields could otherwise reinterpret old state
under a configuration that did not produce it.

### Implemented boundary

`NeuronRuntimeConfigV1::bind_journal_scope()` derives a domain-separated internal
scope from the caller's original subject scope and all current runtime-config
fields: two IDs, thirteen digests and twenty-three numeric fields. The
objective remains separately bound by `JournalScope`. The shared compatibility
encoding is also used by the Cell definition digest, avoiding two divergent
field lists.

`validate_native()` still checks the supplied native configuration against its
computed digest, generation, model/head, normalization and width. A caller's
unverified digest is not substituted for that computation.

`bootstrap()`, `recover()` and `recover_chain_root()` use the same internal
scope derivation. Existing journal-header comparison therefore precedes frame
replay, incomplete-tail repair and catch-up witness CAS. `model_request()`
checks subject/objective context before model dispatch. Segment rollover and
composition retain the internal bound scope.

The chain-root path now also rejects a zero-length root file when the
independent witness lies in a later segment, before calling the journal opener.
The direct anchored branch already rejects missing history. Neither branch
may initialize a replacement header in that case. This guard is part of the
delivery, not an unresolved issue.

## 4. Repair B: separate training policy from a caller's update request

### Problem

A request-local trainable list and its matching hash can prove consistency
between two caller-controlled values without establishing that those
parameters were authorized for training. A returned candidate also needs the
full request identity to detect reuse across Cell/task/principal scopes,
source frontiers and cost budgets.

### Implemented boundary

`CellDefinitionV1` now has `trainable_parameters`, registered by the trusted
host and included in the definition's `hepta.cell.definition.v2` digest.
Empty means inference-only. Duplicate entries and lists over 1,024 entries are
rejected.

`propose_cell_update()` first matches the supplied definition to the state
owner's admitted definition. It then verifies that the request's nonempty
trainable list is a duplicate-free subset of the registered list and that its
mask digest matches. Supplying a new list and recomputing its hash cannot
expand the owner's policy. Replacing the entire supplied definition also
fails the comparison with the owner's retained identity.

`CellUpdateRequestV1::semantic_digest()` binds every current request field:
proposal ID, complete Cell scope, base bundle, source frontier, dataset and
credit identities, trainable mask/list, generations, dataset size and all
training-budget limits. `CellUpdateCandidateV1.request_digest` must match that
identity. Other existing checks still constrain reported changed parameters,
generation, nonzero artifact identity, resource limits and deny-all authority.
`NoUpdate` remains a valid outcome.

## 5. Executed qualification coverage

All 11 newly authored regression tests passed in the retained green run. The
mutation counts below are exercised within those tests; they are not additional
testcase counts. Original logs and JUnit are retained in `native_evidence.json`.

| Coverage | Required observation | Test source / result |
| --- | --- | --- |
| 32 valid outer-runtime configuration mutations | Each incompatible recovery rejects before torn-tail repair or catch-up witness CAS; original journal bytes and witness stay unchanged. | `runtime_recovery_binding_tests.rs`: `configuration_drift_rejects_before_tail_repair_or_witness_catchup` — PASS |
| Same-configuration recovery positive control | Retain a complete lost-ack frame, repair only the incomplete tail, catch up the witness, and permit the next valid tick. | Same test — PASS |
| Legacy subject-only journal | Reject implicit adoption under the new runtime binding, retaining journal bytes and witness. | `legacy_subject_only_history_is_not_implicitly_adopted` — PASS |
| Multi-segment recovery | Reject changed weights before segment composition; retain successful same-config recovery, rollover and canonical-checkpoint generation as controls. | `chain_recovery_checks_configuration_before_composing_segments` — PASS |
| Empty root in both chain-root branches | Return `AcknowledgedHistoryMissing`; leave the root empty and the independent witness unchanged, with no additional CAS. | `chain_recovery_does_not_initialize_missing_history_in_either_branch` — PASS |
| Wrong subject or objective | Reject before model dispatch; model call count remains **0**, with no checkpoint, journal or witness change. | `subject_or_objective_drift_is_rejected_before_model_dispatch` — PASS |
| Request attempts to expand the registered mask, even with a matching digest | Reject before contacting the learner; learner call count remains **0**. | `cell_update_tests.rs`: `caller_cannot_expand_the_registered_training_mask_even_with_its_matching_digest` — PASS |
| Caller replaces the registered definition / empty training policy / duplicate or oversized policy | Reject before learner execution; preserve the admitted state. | The corresponding three tests in `cell_update_tests.rs` — PASS |
| 10 retained-candidate reuse variants | Reject an unchanged candidate after changing agent, Cell, run, principal, source frontier, dataset size or one of four budget fields. For each case, a newly correlated candidate is the positive control. | `retained_candidate_cannot_cross_cell_task_principal_source_or_budget` — PASS |
| Authorized subset and `NoUpdate` | Preserve both observed Cell partitions; candidate authority remains `DENY_ALL`. | `valid_subset_and_no_update_keep_candidates_authority_free_and_live_state_unchanged` — PASS |
| Focused package / relevant host integration / formatting / scoped lint | Exact commands, toolchain, tested/final source identities, exit status and complete original logs are retained. | PASS within the stated scope; 2 dependency warnings disclosed below |

### Native commands and retained evidence

The baseline control runs the two recovery regressions against the unchanged
parent implementation. Both fail as intended: configuration drift was accepted,
and an empty root with an ahead witness could initialize a header before
rejecting recovery. The first `red-r1` invocation stopped on a duplicate CLI
flag before tests; it is retained as a harness failure. The corrected `red-r2`
run executes the two tests and retains its original failing JUnit, including
configured retry records. No failed attempt is represented as a passing run.

The green gate first builds `hepta-joint-propose` from this checkout using
Cargo's compiler-artifact output, pins the produced executable and its SHA256,
and supplies that exact executable to the integration tests. It then runs:

```sh
just test --locked -p codex-hepta-neuron -p codex-hepta-agentd \
  -p codex-hepta-memory -p codex-hepta-automation --lib --test-threads 2
```

The executed package counts are neuron **188**, agentd **698**, memory
**411** and automation **65**.

The retained original JUnit has 1,362 unique testcases and no failures or
errors. The runner additionally reports 69 skipped tests; these are not counted
as passes and are not present among the executed JUnit cases. This was scoped
library qualification across four relevant packages, not a full-workspace or
production run.

`native_evidence.json` contains the complete original logs, JUnit and result
records as individually SHA256-pinned gzip+base64 entries. Decode base64,
decompress gzip, then verify each entry's uncompressed byte length and SHA256.
The green JUnit SHA256 is
`950b99c53b710c02df0b36eb54b2d7df20046c8ab3290b5e810808df9b3ce16d`.
The green source identity is unchanged before/after test execution. The
maintenance capture records the exact tested-to-final diff and final file
hashes separately. Production Rust source remains byte-identical to the tested
version. Subsequent changes are confined to two test files: a named function
pointer type alias, removal of a redundant `Arc` clone, and formatting. The
initial maintenance attempt is retained, including a type-complexity diagnostic
that `clippy --fix` reported despite exiting zero. The second attempt removes that test diagnostic and completes scoped Clippy
with exit zero. Its two remaining diagnostics concern lifetime spelling in the
unchanged `third_party/i18n-config-0.4.8` dependency (lines 144 and 155); they are
retained and explicitly classified, with no warning attributed to the changed
owner packages. An overbroad harness warning check initially stopped before
formatting; a linked continuation executes only the remaining formatting step
and retains the original attempt. No test execution or repeated Clippy run is
claimed by that continuation.

The 32 runtime mutations exercise valid outer-config changes independently of
the unchanged native configuration. Native-coupled fields remain checked by
`validate_native()` and the existing sparse journal's computed configuration
identity. The 10 candidate-reuse tests reject the learner's returned candidate;
they are not zero-learner-call admission tests.

## 6. Intentional history incompatibility and upgrade procedure

This delivery deliberately changes compatibility identity:

- Old runtime journals use a subject-only scope and cannot be recovered
  implicitly by the new runtime binding.
- Cell definitions now use a v2 digest that includes host training policy.
  Existing Cell journal headers and semantic operation/request identities
  therefore do not become compatible merely by choosing an empty policy.
- Readability of an old individual journal-record encoding does not override
  the enclosing header/definition mismatch.

The safe upgrade is a host-owned lifecycle transition, not a header rewrite:

1. Retain the old journal, independent witness, selected artifact identities
   and the compatible binary/configuration needed to interpret that history.
2. Drain the old task boundary and fence its writers. Reconcile pending
   inference and external-effect operations with their original owning
   services and stable operation identities.
3. Admit the new immutable runtime/bundle and training policy through the
   existing artifact, selection and Control owners. Preserve independent
   evaluation and publication requirements.
4. Establish a fresh state generation / appropriately scoped new journal and
   independently retained witness using the explicit host lifecycle. Use an
   explicit state reset unless a separate, authenticated migration has been
   qualified. Do not clear the old witness or rewrite old receipts to make
   mismatched recovery pass.
5. Verify the new owner cut and a successor task's actual use. Keep the
   predecessor available under its original identity for audit and qualified
   recovery; an old model checkpoint must not roll back current tool authority
   or the provider-attempt ledger.

This patch does not supply a general legacy importer. A migration that
preserves state needs its own compatibility proof, source/target binding,
failure recovery and acceptance evidence.

## 7. Remaining trust and acceptance boundaries

### Candidate contents require a trusted owner

`request_digest` is a correlation commitment, not authentication or a proof of
artifact contents. `CellUpdatePortV1` remains a trusted owner adapter. The
learning/artifacts owner must read and verify actual candidate bytes, compare
the real parameter diff to the frozen trainable range, verify the immutable
dataset and source frontier, and retain genuine cost/evaluation evidence.
A dishonest port can relabel a candidate and misreport `changed_parameters`;
matching reported hashes alone does not solve that problem. This delivery
does not grant that candidate publication, selection, adoption or effect
authority.

### Training-budget authority remains a deployment boundary

The request carries its own training-budget envelope. This entry point checks
nonzero bounds, dataset size, reported cost and complete request correlation;
it does not independently authorize that quota. A trusted deployment/learning
owner must enforce the actual resource grant. Existing coordinator hard limits
are not evidence that this Cell entry point is connected to that owner in a
production daemon. This delivery establishes budget consistency checks, not
a new quota-authorization mechanism.

### Public checkpoint conversion trusts its caller

The public `canonical_checkpoint_v1(config, checkpoint, tick, expiry)` helper
checks checkpoint summaries and then uses fields from its supplied config.
It does not independently authenticate the config's provenance against the
checkpoint. The `NeuronRuntime::canonical_checkpoint()` wrapper uses the
runtime's retained private config and is the intended runtime path. Direct
users of the public helper must supply an already authenticated pair; this
patch does not make that helper an independent provenance verifier.

### Scope of the conclusion

Source checks and synthetic native tests do not establish the full production
loop of task execution, memory writes, real training, independent evaluation,
selection, adopted-version publication and successor-task consumption on one
qualified version. This qualification does not establish RSI, global
intelligence from local rewards, superiority over trained GRU/SSM or other
baselines, preservation of all prior skills, or ongoing learning capacity.
Production end-to-end and scientific acceptance remain separate evidence
gates.

## 8. Research boundary

E-prop combines local eligibility traces with learning signals; its online
signals approximate terms whose exact values depend on future network
activity. That does not justify replacing global credit assignment with an
independent reward for each Cell. Continual-learning evaluation must also
separate loss of old-task performance (forgetting) from loss of the ability to
learn new tasks (loss of plasticity). These motivate separate state ownership
and separate retention/adaptation tests; neither paper proves this system's
production behavior or RSI.

- Bellec et al., *A solution to the learning dilemma for recurrent networks of
  spiking neurons*, Nature Communications (2020):
  https://www.nature.com/articles/s41467-020-17236-y
- Dohare et al., *Loss of plasticity in deep continual learning*, Nature (2024):
  https://www.nature.com/articles/s41586-024-07711-7
