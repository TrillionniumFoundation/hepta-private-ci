# Explicit recovered origin for the existing SELECT question followthrough

Date: 2026-10-14. PR #1697. Parent:61e909b2b413661a412aba5714afdbe36c4435b6.
This change does not retrain a model, change a scientific comparison, admit a
Reader or turn the original cancelled run into a completed successful run.

## 1. Why an explicit bridge is needed

Original training38512395172/source644799a3 was cancelled. Its completed saved
arms can be reused, but the old SELECT entry point intentionally requires an
original successful full training report. Recovery61e909b2/run38518485794 instead
has its own manifest and result schema. Without an explicit new origin, the
old guard would continue blocking even after a valid recovery completed.

The existing select_question_relevance_trial.run now accepts ONLY an opt-in
recovery_source=61e909b2b413661a412aba5714afdbe36c4435b6. Its omitted default
still calls the unchanged validate_training and emits the original plan/result
schema. No recovery fallback is attempted when the old validation fails.

The new entry point changes execution provenance, not candidates or inference:
all four fixed arms, original SELECT recipients/donors, exact public input bytes,
2048/64 token limits, full-logits-v1, read-only adapter loading, free-generation
sealing, four-score diagnostics and missing-slot handling stay unchanged.
Only missing matched-question inputs are generated, once per unique input/model;
old mismatched answers are reused byte-for-byte, not counted as new model calls.
The previous upper bound remains12 new generations and48 likelihood forwards,
not an observed completed count. Wrong substantive answers can still pass the
behavioral pattern; semantic_accuracy remains null and no reviewer is invented.

## 2. Two explicit and independently checked provenance boundaries

select_recovery_origin.py accepts the exact recovery run/source/workflow and
repository metadata obtained through authenticated GitHub endpoints. It requires
completed/success, a unique named nonexpired artifact, run/source identity and
a complete metadata page. Its SHA is passed to the existing whole-ZIP/member
validator; archived Python is not imported. No latest-run lookup or older-model
substitution is permitted. Local metadata JSON cannot self-authenticate origin.

The canonical relevance_recovery.validate_completed remains mandatory. The new
bridge additionally verifies every old/restarted raw seal and fsynced journal
join, exact scientific plan and slot census, initial adapter identities, copied
historical versus restarted arm origins, retained partial optimizer journal,
and actual reported work. Unavailable slots are retained: registered complete
recovery has112 slots,108 successful generations across origins,81 reused and27
new. Recovery training's112 updates/864 forwards are UPSTREAM work, not new
SELECT optimizer work. These are validation requirements, not current results.

Old final in-memory integrity observations lost during cancellation are not
invented: reused arms explicitly identify a NEW saved-byte reload check. The
abandoned optimizer prefix and unknown in-flight tail remain separately charged.
Malformed source, missing files, wrong seals, failed recovery, grade/admission
claims, changed origin flags or zero-filled abandoned work fail before a Reader
loads. The wrapper does not repair/rewrite a report to pass the old validator.

Recovered SELECT plans/results have the distinct schema
hepta.reader.select-question-recovered-followthrough.v1 and bind a separate
upstream-recovery-origin.json. Original status remains cancelled, with exact
original and recovery source/run/archive lineage recorded. Training, provenance
verification, loads and extra scoring are not free or matched-TCO evidence.

## 3. Execution routing and honest deferral

The new hepta-select-recovered-question workflow first runs pure contracts and
resolves the fixed recovery metadata ONCE. Missing/in-progress/failed upstream
writes an explicit deferred receipt; it does not retrain, poll or download
pretrained material. Inherited official-model regression still runs. Actual
pretrained download and followthrough steps execute only if that dependency
was already completed/successful. execution-disposition.json distinguishes
successful tests from an actually completed model report. A green contract
job with deferred model steps is NOT an efficacy or model execution success.

Marked [recovered-select-only] commits route away from the redundant old
SELECT workflow, whose original upstream success guard is otherwise unchanged.
The new lane retains its required regressions. No recovery training workflow
or trainer file is modified, so this change does not launch a second reverse
training job. This invocation does not arrange background notifications.

## 4. Actual verification available before publication

Existing read-only inventory38517205670/job115698569294/source0ff45797 is now
completed/success. Complete logs were read. It passed19 supplement tests and
reverified the cancelled archive plus525 manifest members/526 files, reporting
112 completed updates/864 forwards for repeat_empty and nonempty_aligned;
reverse81 completed/624 known forwards,82 starts and no terminal receipt.
It invoked ZERO pretrained models or optimizers. Artifact11872633144 has
GitHub-reported SHA56d96c60779eb9f2596a8e8a8dcf0f3aa3b0fe3c84440876b29405de7ca62fe2,
12,385 bytes. No current local rehash of this output artifact is claimed.

Recovery38518485794/job115702558764 was directly observed progressing through
successful pure contracts, pinned dependencies, inherited official regression
and input artifact checks; one-arm recovery was IN_PROGRESS. No completed
recovery, reverse-arm quality or final four-arm result is asserted here.

New metadata/material/legacy-default tests are submitted, not yet claimed
passing. Current local container, private Python and visible Python probes all
returned ClientError, so there is no new local test count or model invocation.
The source is read/written through the connected GitHub actions; publication
is separate from observing CI success. Check the exact submitted workflow.

All prior raw evidence, failed projection tolerances, external Reader review,
22-arm/15-contrast plan,768-position matrix and Group/NDU state remain. The old
local recovery patch is not overlaid onto a different parallel implementation.
Independent semantic review/new task families, learned Group/NDU benefits,
shared-versus-replicated lifecycle cost and multimodal/split transfer remain
separate experiments rather than being replaced by this provenance bridge.
