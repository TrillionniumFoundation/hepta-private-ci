# Original Training readback and retention fencing: version 2 preparation

## Status

This is a preparation for review against fixed upstream commit
`b29869e856d08db1bfb066116a9c443376ccc57d`. It is not a published source change,
a full caller-proof result, a Rust test result, or an ordinary A/B/C qualification.
The published source inspected for the original failure was
`e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`.
Fourteen relevant production/fixture source blobs have identical Git identities
at these two commits; the mapping is included in the manifest.

The exact e8 full-caller run returned 1 without timeout. Its complete log is
Git blob `e4d0dce9b262a67a469dbfedb74b7ae99e3ae613` (192 bytes,
SHA256 `39ca8695a50ab0408e13e693c7bfb4563e989d3b1a13e07ec3a01c18fc8ca139`).
The original run record is blob
`3cfa7bdefec6aa5af6fe523f027f39829816a7ab`.
The failure was:

```text
FAIL_HEPTA_CALLER_PROOF: learning_source_bound_training_stage_readback: caller set mismatch; missing=[], unexpected=['codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs']
```

This is a real omitted caller, not conservative receiver misattribution. The
call already uses explicit original UFCS:
`SourceBoundCellQ24TrainingStageV1::readback(&self.stage, &self.context.dataset)`
in `cell_q24_training_command_readback_service.rs`, lines 76–81.
The exact receiver is the private `stage:
Arc<SourceBoundCellQ24TrainingStageV1<TW, RW>>` field declared in
`cell_q24_training_command_service.rs`, lines 45–54. Moving or disguising the
call, changing the verifier, or adding another UFCS would not fix the manifest
omission honestly.

## Authority and custody chain actually inspected

All short filenames below are under `codex-rs/hepta-agentd/src/`; line anchors
refer to the identical e8/b298 source blobs recorded in the manifest.

| Boundary | Actual implementation and evidence | Consequence |
| --- | --- | --- |
| Original custody | `cell_q24_training_bootstrap.rs::bind_original_custody`, lines 143–186, accepts the pre-held files, witnesses, Generator key, baseline and original Material/evidence connections. It checks initial Dataset/Source context, Generator principal/key and original signer binding. | The readback endpoint does not create custody from unsigned context. |
| Original construction | `cell_q24_training_bootstrap_build.rs::build_original_owner`, lines 101–234, consumes the custody, binds the actual opaque Dataset, captures the same live source, checks freshness before writer creation, and chooses original create/recover according to the retained Origin. It then consumes the original native and receipt owners into one Stage, one SourceBound facade and one command owner. | A readback response borrows an already constructed original owner. It does not use this construction path. |
| Command context | `cell_q24_training_command_service.rs::bind_original_stage`, lines 83–106, validates the frozen context and calls `require_original_command_context` before retaining the Stage. `cell_q24_source_bound_stage.rs`, lines 49–63, checks the exact Dataset and frozen scope in the occupied original lane. | A caller-supplied request cannot select a different Dataset, stage, scope or owner. |
| Bootstrap state | `cell_q24_training_bootstrap_service.rs::ready`, lines 98–105, returns no owner for Awaiting, Busy for Starting, an Arc clone only for Ready and Uncertain for Fenced. The state lock is released when this helper returns. | No bootstrap state lock is held across the subsequent Stage I/O, and no owner is invented for an unready host. |
| Read-only dispatch | `cell_q24_training_bootstrap_readback.rs::original_training_readback_response`, lines 75–119, checks the new purpose, Readback action, no cancellation, bounded sequence, original operation/actor/scope and canonical nonzero digests before `ready()`. Only Ready delegates to the same command owner's read-only response; Awaiting returns ReadbackRequired. | The new purpose cannot execute or recover an Awaiting owner. Cold recovery remains a separate original-host operation. |
| Transport admission | `learning_owner_command_channel.rs::original_owner_command_channel_v1`, lines 20–57, requires a distinct process and UID, original boot/start identity, pre-held pidfd, positive exchange/session limits (at most 30/300 seconds), bounded frames and repeated peer liveness. Both new serving methods acquire their existing connection permit and admit this original channel before queueing blocking work. | The new readback purpose reuses the original transport limits and process identity; queueing does not restart its lifetime. It does not widen the older separate evidence transport's 500 ms limit. |
| Fixed request | `cell_q24_training_command_readback.rs::require_request`, lines 245–267, checks schema, exact purpose, sequence 1..128, domain binding, operation, Dataset head, scope, actor, Readback action and no cancellation. The service calls it before the actual Stage read. | A wire request contains no new Dataset, training data, signing payload or authority. Wrong purposes and Execute are rejected before the native lane. |
| Original lane | `cell_q24_training_stage.rs::readback`, lines 199–205, requires exact Dataset and invokes `Owners::read_original_completion` through `in_lane`. Lines 228–265 retain the one-permit lane and original owners mutex in the blocking operation, check the existing fence, Dataset/scope, live source before work, live source after work and captured tail CURRENT/signature state. | This new caller shares the original serialization and invalidation checks. It does not receive a native writer or independent execution lane. Errors remain errors/uncertainty. |
| Original receipt | `cell_q24_training_receipt_owner.rs::readback/authenticate_completed`, lines 134–178, reads the original observation and journal, reconstructs the payload at the retained issued time, verifies the original Generator identity/controller/signature and re-reads native observation and journal bytes. Stage tail checks verify the retained attestation at a fresh time. | There is no fit, claim, new signature or expiry renewal in this readback path. |
| Final host response | `cell_q24_training_command_readback_service.rs::original_training_readback_response`, lines 69–85, uses the same Stage and `completed_response`. The latter uses `wire::encode_completed`; `cell_q24_training_command_wire.rs::authenticate_receipt`, lines 216–247, checks exact actor, predecessor, observed/issued time, original role signature and scoped one-receipt extension. | The response is authenticated original evidence, not a publication or effect grant. |
| Client attenuation | `cell_q24_training_command_readback.rs::from_original_stream/bind_original_training`, lines 40–148, checks original initial binding before/after admission, consumes the original stream, verifies opaque D and full T, and moves that exact peer into the existing evidence-only client with no general command channel. | The client cannot use the old Execute purpose. It retains the original session end. |
| Client failure and return | `OriginalTrainingReadbackV1::readback`, lines 163–216, takes the peer before awaiting, binds the expected receipt and sequence, validates correlated response, liveness and current D, verifies the returned full T, and restores the same peer only after complete equality. Missing/Pending for an already pinned T become CommitUncertain; errors do not restore the peer. | Uncertain or changed evidence cannot be recycled into a new NoUpdate or a reusable command capability. |

This establishes the legitimacy of the narrowly bound read-only source seam.
It does not establish a live ordinary product owner, actual independent
operations, material availability, a complete qualified committee or permission
to execute a subsequent Selector/C/Version action.

## Smallest complete manifest reconciliation found in this purpose

A single added path would repair the first observed mismatch only. Inspection
of the same three readback files found five further explicit calls to already
protected original APIs omitted from their existing caller sets. The proposed
change is exactly these six membership additions across four existing rows:

| Existing boundary ID | Additional exact product caller |
| --- | --- |
| `learning_source_bound_training_stage_readback` | `cell_q24_training_command_readback_service.rs` |
| `learning_original_owner_command_channel` | `cell_q24_training_command_readback.rs` |
| `learning_original_owner_command_channel` | `cell_q24_training_command_readback_service.rs` |
| `learning_original_owner_command_channel` | `cell_q24_training_bootstrap_readback.rs` |
| `learning_original_material_initial_context_check` | `cell_q24_training_command_readback.rs` |
| `learning_original_material_dataset_context_check` | `cell_q24_training_command_readback.rs` |

The other five mismatches are source observations, not independently executed
full-gate failures. No claim is made that these are every possible remaining
failure elsewhere in the repository.

All 534 existing boundary rows remain, in the same order and with the same
symbol/receiver/definition fields. Existing caller memberships remain in order;
only the listed paths are appended. No wildcard, new ignore path, altered
receiver inference or arbitrary caller is admitted. No new boundary or public
Rust API is introduced.

The fixed b298 manifest had no protected-file row for these three readback
files. Version 1 appended three readback protected rows. Version 2 additionally
strengthens existing panel-binding protected row 338 and appends the previously
absent model-material verification row. All 386 existing entries remain; only
that one original row changes, and the three version-1 readback rows remain
identical. The resulting counts are 534 boundaries and 390 protected rows. All
other top-level manifest fields,
including authority and required-boundary inventory, are unchanged.

### Three new protected contracts

1. **Client:** keep the private original peer/Material/D/T/context, fixed purpose
   and binding domain, original actor/pidfd and before/after initial checks.
   Require consuming handoff and complete D/T authentication before attenuation.
   Require peer consumption, fixed expected receipt/sequence, response binding,
   liveness/current D/final clock, full original T equality and only then peer
   restoration. Preserve Missing/Pending as uncertainty. Forbid execution,
   signing, writer creation, reconnection, recovery, authority cloning and
   bootstrap mutation.

2. **Command owner service:** require connection permit, original channel
   admission, then blocking dispatch; preserve the 128-exchange bound.
   Require exact read-only request validation before original SourceBound read,
   then authenticated completion. Forbid Execute, cancellation mutation,
   bootstrap/build/recover, new writers and signatures.

3. **Deferred bootstrap service:** require the same bounded admission/order and
   read-only request/context checks before Ready lookup. Only the retained Ready
   owner may serve; Awaiting remains ReadbackRequired. Forbid bootstrap state
   mutation, owner construction/recovery, Dataset bootstrap reads, fits and
   signatures.

These use the unchanged original `_verify_protected_files` function and its
function-local ordered/top-level code markers. They are regression guards, not
a formal proof against all possible malicious rewrites.

## Explicit additional scope: both retention guards remain fenced

The original b298 panel-binding row 338 checked complete member sets, original
unknown dispositions and retained evidence digests, but did not require the
new positive-primary/negative-retention refusal. Version 2 adds the exact
primary Eligible condition, every retention member (skip 1, any non-Eligible),
Binding error and top-level-before-success ordering to the existing function
contract. Its earlier checks remain unchanged.

There was **no protected-file row** for
`neuron_cell_evaluation_model_material_verify.rs` in b298. Creating a row is
therefore necessary; this is explicitly approved additional scope, not a second
existing-row edit. The new contract requires current original T/E authentication,
complete member count and order, `member::verify` and original cohort binding,
namespace/run separation, complete signed retention identity, the new retention
guard, then the original Qualified/NoUpdate mapping and final exact receipt
comparison. No original verifier semantics or production API changes.

The guard production inputs are separately reviewed immutable postimages:

- `neuron_cell_evaluation_panel_binding.rs`: original blob
  `a3be9f7b415d4783886b346d273296ae8ecb32e5`, prepared guard blob
  `8a779085dd02536a646415406abcaa471b097c10` (+14 lines).
- `neuron_cell_evaluation_model_material_verify.rs`: original blob
  `c9b8a264cbf51fbf4c405042e1252e931717524a`, prepared guard blob
  `aea0027ad5f6e51825469b5d8fb8b14d202da575` (+8 lines).

These Rust files are dependencies of this CALLERS/QA package, not duplicated
Rust edits inside it. The two guards reject a Qualified combination that violates
its frozen retention member conditions. Complete member comparisons remain
complete. The guard does not relabel a known negative comparison as missing
evidence, fraud or a new aggregate NoUpdate, and does not re-sign an owner result.
An original complete primary-negative NoUpdate keeps its existing mapping.

A second sibling source-mutation QA checks removal, inverted primary/retention
conditions, wrong quantifiers or skipped members, hidden/non-top-level guards,
changed error semantics, bypassed original signatures/membership and damaged
NoUpdate mapping. It supplies no fake qualified fixture or opaque seal.

## QA changes and preserved adversarial rejection

A directed text search of all 55 Python files in fixed b298's
`qa/b4-no-bypass/` found nine existing QA files carrying one or more of these
four exact caller-set expectations. Only those tuple leaves are synchronized.
Their methods, assertions, mutation logic and unknown-caller rejection remain
unchanged. The original source-capture QA still injects both an unregistered
capture caller and an unregistered Model lane and requires rejection.

The new sibling
`qa/b4-no-bypass/test_original_training_readback_source_closure.py`
adds nine methods using the same original verifier:

- check the four exact caller sets and reject additional typed and qualified
  callers; removal of each registered adapter must report a missing caller;
- delete original stream, actor, pidfd, Dataset and complete Training binding;
- invert the purpose/context/sequence/action conditions or permit cancellation;
- move channel admission after queueing, remove its permit/pidfd, or widen the
  exchange count;
- remove, comment out or move host request validation after actual readback;
- remove current evidence/signature checks or restore a peer before validation;
- turn a pinned completed Training into Missing/Pending, or restore a peer on
  uncertain response;
- detach Ready-only delegation or replace Awaiting's ReadbackRequired response;
- inject execution, signing, reconnection, custody recovery or bootstrap state
  mutation into a read-only adapter.

The original frozen b298 workflow `.github/workflows/hepta-daemon-learning-native.yml` (Git blob `72d4b247d90dde972ac592b2d568cd6e470f97ff`), lines 311–315, selects `python3 -m unittest discover -s qa/b4-no-bypass -p '*source_closure.py' -v` under the existing 600-second runner and minimum-tests=1 contract. Both new filenames match that existing pattern. No workflow, entry list or selection filter is changed. All original QA function definitions are checked byte-for-byte unchanged.

The nine readback methods have not been executed in this preparation. The
three methods in the new retention-guard sibling have actually run against
the exact prepared source inputs: all passed, including rejection of each
guard-removal/inversion mutation. This is source-fencing evidence only. Existing Rust
readback fixtures also have not been rerun by this review. They are useful
behavioral follow-up inputs:

- `original_training_readback_unready_and_wrong_purpose_never_initialize`
  checks fresh/cold Awaiting, purpose rejection and unchanged actual native and
  Material bytes.
- `original_training_readback_preserves_cold_signature_and_initial_deadline`
  checks original signature bytes, old-purpose refusal, the pre-bound absolute
  deadline, cold Awaiting refusal, separate original recovery and subsequent
  readback without renewed evidence.
- `original_training_readback_changed_evidence_and_withdrawal_consume_channel`
  checks renewed/Missing/Pending replies, cancelled queued reads, actual source
  withdrawal, consumed channels and retained original file bytes.

Those tests explicitly use same-process framing and fixture enrollment.
They cannot be reported as independent deployed UID/actor qualification.

## Preparation checks and integration instructions

Actual preparation checks were TOML/AST parsing, exact structural comparison of
the original and prepared manifest/QA tuples, and a **three-row diagnostic**
calling the original `_verify_protected_files` on the exact immutable source
bytes. All three new rows passed that diagnostic; its six recorded input hashes
were unchanged. It ran for approximately 0.016 seconds. The complete record is
included as `scoped-baseline-diagnostic.json`.

Version 2 also ran the original verifier on all five affected protected rows
(three readback plus two retention), with five scoped passes and unchanged
inputs. Its separate retention sibling ran 3 tests successfully in 0.323s
(return code 0; captured wall time about 0.411s). Raw log and original run
metadata are included. The complete all-Rust four-boundary diagnostic is
prepared separately and has not run at this package freeze.

This is not the complete 390-row protection check, not the full typed caller
scan and not execution of the nine readback source-mutation tests. Full source gates
and any native behavior tests must run on the subsequently frozen source.
The original e8 full-caller failure remains retained and valid.

Apply the prepared paths only when each base Git blob matches the manifest.
The Rust inputs are unchanged. Preserve the e8 historical blob-size allowlist
entries; this preparation deliberately does not edit that allowlist. After the
root integrator combines all accepted CALLERS changes, append the exact final
CALLERS SHA256 under the existing large-blob contract. The prepared CALLERS
identity in this manifest is intermediate if another reviewed edit is combined.

The signed positive-primary/negative-retention runtime branch remains unexecuted.
Source mutation rejection must not be described as behavioral branch coverage.

No refs, PR source, desktop worktree, original verifier or Cargo process were
modified or started by this preparation.
