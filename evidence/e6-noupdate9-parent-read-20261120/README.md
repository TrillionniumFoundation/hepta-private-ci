# NoUpdate9 independent parent-path review

**Confirmed stale refusal-owner namespace in two parent observer sites; corroborated by the actual retained Root record. The original NoUpdate9 result remains failed.**

This final package includes the original source-only analysis and the later independently verified physical addendum. No runtime/source gate, native experiment, model call or credential operation was performed by this review.

# Physical readback addendum

The earlier source-only report is retained unchanged. Subsequent local review of hia's actual retained Root readback corroborates its specific namespace diagnosis.

All five captured files were reopened and matched to `REFUSAL_CAPTURED_FILES.json` by byte length and SHA-256. The actual canonical refusal is 1,351 bytes, SHA-256 `57aed6a9ffe2b43d8362dae65853a58bd53e0e9520fb268efe0006bf28d90c6a`. It is a private Root-owned regular file with one link, and its retained state is `ready`, attempt `1`.

The actual initial digest is `deb14d53b909dba582deb90bb1bf8cec68d30dafd962215d05921a690a849786`. From the retained target and exact `scope_digest` and `Digest32` source, this review independently recomputed scope `545f8a5ac1359a3ce6cca2128aa25656419b0983e9c6354a8c50163b6ecb633d` and completed-learning slot `493210e270f3a11e448b4e2c1216efa900be428ea9f9912f27375455149b194d`. The resulting owner exactly matches the physical record's canonical envelope.

| Name derivation | Expected file | Actual retained directory |
| --- | --- | --- |
| Current product | `frontier-v1-de6c979fa4a455329efafc6951dae246aa18708611d57641c649744a2b553ab2.json` | Present, matching bytes and owner |
| Stale parent observer | `frontier-v1-a8e934e4b541f6f7e731a122668f199c67d99d2e61de4c2273d67e6e748d6339.json` | Absent from the complete specified authority-frontier listing |

Both are under the same actual backing directory, `/run/hepta-daemon-learning-root-e6-tail-stage-bfea526e-noupdate-9/source/ordinary-q24-fLbWxM/authority`. The absence statement is limited to that specific recorded directory listing. It does not claim the earlier global filesystem enumeration was complete: that first attempt hit its 4,096-entry limit and remains a retained failure.

The first-refusal state of Ready/1 is consistent with PREPARED startup registration, with acceptance not yet performed. No completed-learning acceptance owner appears in the specified authority listing. The product's final acceptance is still a separate missing result, not something supplied by this diagnosis. The original log did not capture the kernel open pathname; the mismatch and the physical state strongly corroborate this source-level explanation, without pretending to supply a missing syscall trace.

## Checkpoint data projection

The original checkpoint file is 4,415 bytes, SHA-256 `b6c8cbec8f8369078abe366552f12488b810daa6689501ca9d2bb179f30cbe1e`. Using the exact pinned persistence codec, a local read-only Python decoder consumed all 3,124 decoded bytes, with canonical unpadded base64 and the matching outer predecessor. Its header is `HEPLCP02` and its six receipt tags are:

1. Experience
2. Dataset
3. Training
4. Evaluation
5. Selection
6. RetainedModelNextUse

The final encoded head is `aef56df7e0a714f10f79fa78cd55d6182c5ee4685d73f16c296755cb00aa61e4`. This is a byte-layout projection of retained data. The Python decoder does not run the Rust coordinator, authenticate signatures, supply an authority capability or establish a whole-parent pass.

A separate source-level compatibility question was reported to root and chain for review: the same source's `read_original_completed_scoped` requires `MAX_RECEIPTS`, currently eight, while this validly decoded historical NoUpdate checkpoint contains six. That later acceptance path was not reached in NoUpdate9, so this is not claimed as its observed first failure and no guard was changed here.

No new host read or execution was performed by this peer; it reused the separately retained physical readback. No source, record, budget, model or native result was changed.

---

## Retained source-only analysis

# NoUpdate9 parent-path diagnosis

**Confirmed source defect: the parent observer uses an obsolete refusal-record owner name.** The currently frozen production source writes a different canonical name. The first failing parent read is therefore a strong, specific explanation of the bare `ENOENT` after the NextUse checkpoint. Physical readback of this run is being checked separately; this source review is not a syscall trace or a successful rerun.

## Exact scope

The actual failed parent is bound to source `bfea526e1cb9a2da718d835cd617e87c67181fe9`, tree `e047b5fc72284e25a98c0ebb4f2e69a2f6338e56`. The retained original result has one failed native parent case and command exit 100. Its trace contains every request ID from 1 through 61 once, including Selection 58–59 and NextUse 60–61. It contains no delivery-complete 62–63 or acceptance 64 request. The original `complete_native_NoUpdate`, `native_owner_adoption` and `fresh_C_and_cold_fresh_D` claims remain false.

This review only reads local retained evidence and exact-commit GitHub source. It does not start a host process, replay native work, call a model, change a source file, mint a credential or change a budget.

## The mismatched names

The production `authority_host_data_refusal.rs::binding` computes the completed-learning slot as:

```text
slot = Digest32::of_parts([
    b"hepta.root.initial-data-refusal.completed-learning.v1\0",
    scope_digest(target.scope()).as_array(),
    initial.as_array(),
])
owner = "initial-data-refusal/completed-learning/" + slot
```

The parent `ordinary_q24_cold_acceptance_data_tests.rs` instead constructs this older name in both the live wait and the later exited-process observation:

```text
owner = "initial-data-refusal/completed-learning/" + initial + "/" + scope
```

These are different owner strings: 104 bytes for the current form and 169 for the old form, with canonical 64-character digest displays. The production source explicitly explains that the former two-digest key exceeded the existing 128-byte owner bound. Both observer implementations derive the filename from the owner digest, so the mismatch selects a different file. Even an accidental filename collision would not satisfy the strict owner-ID comparison inside the canonical envelope.

The problem affects the first wait and the post-retirement `OriginalColdAcceptanceData::observe` path. Correcting just one occurrence would leave the second path broken.

## Why a normal publication wait is not the remedy

`CompletedLearningRuntime::retain_original` registers the canonical refusal during startup in `CompletedMode::Accept`, while the historical state must still be `PREPARED` and completed input files are empty. Registration writes the independent refusal as Armed and completes it to Ready only after the real startup checks return. The refusal should therefore already exist when the parent enters its final acceptance wait.

The later Accept64 operation uses this registered refusal. It advances Ready to Armed, performs the actual completion checks, initializes and reads back the first immutable acceptance record, and only then restores Ready. The first acceptance file may legitimately not exist yet when the terminal checkpoint becomes observable; the independent refusal record has a different lifecycle.

The parent already treats absence of the *acceptance* file as pending. However, it first calls `observe_original_record::<Refusal>(..., refusal_owner, ...)?` on the obsolete name. That helper strictly opens the file with `O_NOFOLLOW | O_CLOEXEC`, and propagates a missing-file error directly. Its `Option::None` represents a validated immutable atomic replacement, not a missing file. The later acceptance-file existence check cannot protect the preceding wrong-path read.

An earlier hypothesis that the refusal merely had not yet been created was rejected after reading the actual PREPARED registration path. A blanket `NotFound -> pending` change would hide the wrong owner name and could run until the deadline. It is not supported by these sources.

## Ordering and the observed error

The parent publishes C inputs, waits for a Root checkpoint whose final receipt is NextUse and whose coordinator has no next stage, and then enters the acceptance wait. Explicit successful shutdown is after that wait. In the product, the terminal checkpoint is committed inside the real NextUse operation; completion of the surrounding operation, delivery-complete and acceptance still follow. Consequently a terminal checkpoint alone does not establish delivery or acceptance.

This explains how the parent can see terminal checkpoint data while the product trace has not reached request 62. The parent may then return the bare file-open error and drop the live children. The cleanup SIGKILL is recorded after the processing failure and is not evidence that B independently failed first. Likewise there is no trace of a 65th request in this run.

The original parent log lacks the failing pathname or a syscall stack. The source defect and its reachable error propagation are proven by the pinned code; attributing the exact kernel failure to this open remains an inference until matched with retained physical state. No result is upgraded to success on the strength of this diagnosis.

## Minimal correction and required checks

Only the parent observer's two stale name constructions need to follow the production canonical owner derivation. A single test-only data helper can keep the two observer sites consistent. Production namespace, store bound, Root policy, leases, read cap, controller authorization and completion semantics must remain unchanged.

The correction must keep strict missing, malformed, symlink, wrong-owner and wrong-target failures; monotonic attempts; Ready with at least two attempts; the immutable first fact; actual daemon ACK identity, scope, terminal-head, acceptance and data-cut checks; and final unchanged observations. It must not fabricate the record or infer acceptance from the terminal checkpoint.

Meaningful validation should compare the observer name to an actual original registered refusal, show that the legacy owner is not accepted, preserve the negative states and ACK mismatch refusals, then run the unchanged original project gates and original bounded parent. These validations have not been run by this read-only review.

Exact source hashes, Git blob identities, numbered excerpts and original failure files are retained alongside this report. Physical follow-up, if received, will be recorded as a separate addendum rather than altering the old failed experiment.
