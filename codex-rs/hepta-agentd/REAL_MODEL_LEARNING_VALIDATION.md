# Actual native model research validation, 2026-11-08

## Tested source

Commit 27849cbdcfc0d4afc69764d6c1742af22c41c293, tree
af50e58bf382891fb41861810cbf5425ca0da5a9, passed the actual
actual_smollm_training_no_update_native_next_use_and_cold_readback test on ai395
in 44.615 seconds. Runtime job: 1a1bcaf717a-138b0-409. Original watchdog:
60 seconds. Automatic retries: zero. All 11,207 tracked source files matched
their Git blobs and SHA-256/length/mode roster before and after execution.

The identical pinned Rust/Python source was compiled on rog and transferred as
a nextest archive with correct workspace remapping and verified dynamic
dependencies. Archive SHA-256:
e8af8b22e12c57366cb4f76621815483c39ad36f8e12bfd73d0968e051e6efa5.
The five existing generation-owner controls also passed on this exact source
(job 1a1bcade85a-138b0-3fc); they remain separate from actual model execution.

## Observed complete NoUpdate branch

A fresh operation learning-d9fb-native-v8 froze its four public evaluation rows,
strict-improvement rule, next-task input and real clock/deadline before its own
ten-step training and native coordinator dispatch. Parent score: 3/4. Candidate:
1/4. The actual source task, trainer, eight evaluation forwards and one new
retained-parent next-task forward were process-backed, using pinned real model
materials. Their original bytes, identities, ACK, model STOP and terminal
HEPLCP02 checkpoint belong to this one operation.

Completed checkpoint SHA-256:
f615357c44d865317a33a07ee1bc538468407f223e4f009df999cfe20e574263.
Original ACKed readback SHA-256:
662a5e0163701c7dccfc35dbc4ae559cc2e896b67aef0bac4c4afce36cd385ef.

The original Fleet lifecycle retired/restarted the native generation owner,
then opened and verified the completed learning owner. This occurred within the
same test OS process. Python worker PIDs changed from 203339 to 203366.
Fresh original-worker counters read hot 0 -> 1 and cold 1 -> 1; actual conflict
and FORWARD_BUDGET controls left the counter at 1. This is source-bound worker
ledger-delta evidence, not hardware instrumentation of forward invocations.
The original final-use nonce count stayed one. Native daemon OS restart is false.

## Earlier operations are preserved

v3 stopped before the model test because the archive extraction directory was
missing. v4 really trained/evaluated but the original FinalUse owner rejected a
600,000 ms grant over its unchanged 300,000 ms cap. CURRENT was prepared but not
published, with zero claim bytes. A later research source restricted the grant
to 90,000 ms. v5 rejected fresh-start config against a Running identity; v6
rejected a predecessor not retired; v7 rejected StateLocked prompt ownership.
v5-v7 had published their isolated CURRENT and consumed one nonce. v7 had already
completed checkpoint 6; its hot Chain join passed but the full cold native test
failed. None is relabeled as v8 or overwritten.

## Subsequent maintenance

After the exact-source tests, scoped just fix found a test-only guard held across
await. The research receipt-attestation method now clones the original actor
handle/request inside the guard and releases the guard before awaiting the same
owner reads. Import formatting and Python ruff formatting were also applied.
Python AST equivalence is checked separately. This is a different source from
27849c; the actual model PASS is not attributed to the maintenance bytes.

The first just fmt attempt failed because uv was absent; its original failure
is retained. An isolated verified PyPI uv installation supplied the original
frozen formatter workflow. Subsequent just fix -p codex-hepta-agentd --locked
--offline, strict Clippy with -D warnings, and just fmt all succeeded.
Tests were not rerun after fix/fmt, as required by AGENTS.md.

## Scope and continuation

All added process/trust/driver code is explicit opt-in research. Native helper
changes are cfg(test), with ordinary fixtures retaining their original behavior.
There is no production interface or dependency expansion, live activation,
independent operator, funding or Root/FinalUse capability qualification.
The four tasks and prior outcomes were exposed; quality independence and
generalization remain unqualified. The candidate was not adopted.

Public Chain evidence retains 517 original bounded records and the unchanged
completion reader's exact v7/v8 input/output, with all reader authority flags
still false. Private source/patches/compiled archive and full base model weights
remain outside public Chain evidence. A subsequent positive external-trained
artifact research admission must use a new explicit namespace and source and
must not be presented as original Parameter V3 or Product OPE qualification.
