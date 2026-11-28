# Native paired-record identity: prospective stage 1

Base source: `abcb9b20385d0588d0342529906af658b3012711`.
This stage connects the existing owned FreshRead material type to a bounded,
typed identity projection. It creates no dataset, permission, target, candidate,
or training run. The existing TerminalCell remains the constant-state terminal
value profile whose actions and values come from authenticated owner events.

## Fixed native boundary

Consume FreshRead(PairedTrainingMaterials), the original preparation request,
and independent frozen full-record digest pins. Unknown and RetainedReadOnly
cannot supply a fresh identity. Recheck exact raw file sizes, SHA256 values and
the original material commitment before parsing. Retain both complete byte
vectors without rewriting or trimming them. A successful identity object is
not deserializable and cannot be manufactured from metadata alone.

Canonical identity uses the complete parsed record, including all extra fields:
the Python data.record_digest definition (UTF-8, sorted object keys, compact
separators, ensure_ascii=False, allow_nan=False). Stage 1 supports an explicit
integer-only JSON subprofile: null, booleans, Unicode strings, arrays, objects,
signed i64 and unsigned u64 integers. Reject every JSON floating-point number,
nonfinite number, out-of-range integer, duplicate key, invalid UTF-8, excessive
nesting and trailing value. Do not floatcast, quantize, exclude a self-digest
field or silently claim general Python/Rust numeric equivalence.

Project only the declared record/task/lineage/project/source identities,
train/evaluation flags, timestamps and verified-outcome references. Require
distinct attempts for the same task, lineage, project, source issuer and task
body, chronological failure then correction, train split, explicit affirmative
training/evaluation declarations, failure=false and correction=true. Source
payload hashes may differ between the two attempts. These structural conditions
do not authenticate the declarations, reopen original source paths, validate
retained semantic receipts or replace the full Python record validator.

In particular, no existing contract makes Outcome.support_digest equal the
Python record digest. This stage must not assume that association. A subsequent
stage requires an explicit owner binding, real signed inputs, authorized
DatasetSnapshotReceiptV3 and current Memory Replay permission before native fit.

## Fixtures and fixed controls

After registering this protocol and fixture-generation script, call the existing
test_paired_source.capture helper exactly twice: development failure answer 0,
correction answer 1, the fixed seed-700 task and existing json_artifact verifier.
This performs actual local create-only artifact writes/readback. It has zero
human participants and creates no user trace. Preserve all generated originals,
the two full record files and Python-calculated raw/canonical SHA256 identities.
Also retain Python canonical conformance cases with Unicode, control characters,
integer limits and an included record_sha256 field. No model code is invoked.

Freeze implementation and exact generated fixtures before the first native gate.
Run only the eight new paired_record_identity controls: owned fresh projection;
independent raw and canonical identities under whitespace changes; unknown and
retained refusal; duplicate/malformed JSON refusal; integer/Unicode canonical
conformance and numeric refusals; full-record pin and extra-field binding;
task/source/time/split/declaration mismatches; original request purpose/material
commitment and byte bounds. Reject count drift, skips, filtering to zero, or any
failed control. Keep the first compile/test result and any correction separately.

Native execution belongs to the existing exclusive engineering owner at
/home/qian-qi/hepta-intake-native-6523704f97df/cli-repo and its existing shared
3600-second cumulative cap. Queue this filter in its next combined native gate;
do not start parallel Cargo, restart the budget, or repeat the old 61 controls.
Use the official just test entrypoint. Update Bazel compile_data for included
fixtures. Run official just fmt after tests, preserve executed source plus
format evidence, and do not rerun tests only because of formatting.

No original train cache, DEV/final data, E1-E6 experiment, artificial signature
presented as production, or human consent is generated. Report local fixture and
native gate outcomes separately. No source authenticity, training usefulness,
model quality, useful-work reward, or adoption follows from typed identity.
