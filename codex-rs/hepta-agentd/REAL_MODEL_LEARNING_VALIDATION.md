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

## Subsequent actual external-artifact adoption and NoUpdate regression

The exact tested successor is edf03ecb8a814a0f5e86b1d6a752aeac80b1a978,
tree c7588a07d20310059d4016559fa550d397b7eb09. All 11,212 tracked
source files were verified before and after execution. This successor preserves
the v8 records above and uses two fresh operations with their own frozen profiles.
The five existing native actor controls and nine new material/filesystem primitives
passed with zero failures, skips and retries on this source. Runtime control job:
1a1bcf32e94-138b0-539. Original control JUnit SHA-256:
23c4a56ca437dae82e5c90e9fa85b6600c2254b29eb92303a720c37110544081.

The same Rust/Python source was compiled on rog and executed on ai395 using a
nextest archive with verified toolchain, binary, dynamic dependency and workspace
remapping identities. Archive SHA-256:
e3c169dac89c0330efe52ca8b2581b9d7bff64f368e9749051977370b2591b56.
The two real tests retain the original 60-second watchdog and zero retries.

| Actual operation | Original native result | Decision and next task |
| --- | --- | --- |
| learning-d9fb-native-no-update-v9 | PASS, 44.440 s; job 1a1bcf62479-138b0-545 | Ten fresh optimizer steps; parent 3/4 versus candidate 1/4; retain complete parent; new next answer yes; native hot/cold completion |
| learning-d9fb-native-adopt-v1 | PASS, 51.138 s; job 1a1bcf7983f-138b0-548 | Ten fresh optimizer steps; parent 1/4 versus candidate 2/4; adopt new candidate; new next answer no, incorrect; native hot/cold completion |

The positive candidate answers all four exposed frozen questions no. Its next
task asks whether 8517 is greater than 8516 and also receives no. The strict
four-question comparison passes, but numerical comparison capability, independent
evaluation, useful learning and generalization remain unqualified. Qualified in
the Python evaluation output denotes only that frozen finite comparison.

### Concrete research proposal owner

ResearchExternalTrainedArtifactV1 is a concrete private cfg(test, unix) owner.
Its create-only reservation, receipt and separate anchor bind actual complete
baseline/candidate bytes, trainer source closure, task, profile, budget and native
Training/Evaluation receipts. Real owner birth, native training admission, child
start and completion timestamps enforce the pre-training freeze. It verifies the
120 LoRA tensors and all eight original evaluation outputs, including full logits
and raw action-logit to Q32 conversion. Existing ordinary fixtures and production
compiled interfaces remain unchanged; no new dependency is introduced.

Proposal authentication uses the internal concrete owner call and durable record.
The original dispatcher does not automatically apply learning-phase signatures
to Proposal. Recovery therefore explicitly reopens and validates the same
proposal record and anchor before restoring the original learning snapshot.
This namespace does not reuse no-change authority or represent the external
PyTorch update as original Parameter V3 eligibility or Product OPE qualification.

The exact adopted candidate file SHA-256 is
56d88f2dda61db06f88a96ebed05d29e1a9e2e8d1d02e3f296a8544df743e45c,
933,544 bytes. Its selected bundle is
8c650b9ad74f5b8ec152d700ce184b30bf3cdf008a6b27b2eacbd0805d30f308.
Original updated selection, CURRENT publication, state cutover, generation actor,
ACK, nonce and original HEPLCP02 completed checkpoint all refer to this candidate.
The native generation owner and learning owner recover within the same daemon OS
process; Python workers restart with actual PIDs 227202 and 227232. Fresh original
worker ledger counters are 0 -> 1 hot and 1 -> 1 cold. Counter evidence is a
source-bound live-worker ledger delta, not hardware forward instrumentation.

The positive native completed checkpoint retains seven receipts, SHA-256
49687e0ece90dceb6409978616700c0b32ec342631a1941994ae3b7a886a7496.
The ACKed readback SHA-256 is
a11c43e68721199443ca265c35d5197f6883a732b04ae0f25e480cb9ce6adc5b.
The NoUpdate completed checkpoint retains six receipts, SHA-256
c890ca0ba1f5b5190e33bc93a0947c98a5cbfc4f77ad4f65ac8f428274ab222f;
its ACKed readback SHA-256 is
fdfc6d1bd390a2d6f37ac563d7fe49886e2ac0492b4dff47af95e32f403162a9.
The unchanged Chain reader passes the exact original 0/6/7 and 0/5/6 continuations.
Its native-origin, training, full-learning, signature, settlement and production
qualification flags stay false. ACK, model STOP and training completion remain
separate observed facts.

### Actual rejection evidence and retained source failures

On the legitimate four-receipt snapshot and unchanged prepared payload, replacing
one actual candidate byte and separately removing the actual training-start file
each caused a concrete material-owner rejection. The original files were retained,
restored exactly and freshly prepared again. Neither rejection advanced proposal
storage, Selection, CURRENT, checkpoint or nonce. Seven context alterations before
Proposal and eight during cold restoration also refused; some of these fail at the
original coordinator hash chain, unlike the two direct external material faults.
The original valid completed snapshot then reverified without reissuing a receipt.

The predecessor 6e0f0c8d1a7bd94a396a1532a537b32dd1843cf6 failed
compilation with original SignedArtifactSelectionV1 missing Serde. Its original
log and failure remain. The successor uses a research-only exact-field wire with
the original signature, original signing preimage, canonical round trip and
original load_selection verification. Production Serde and cold re-signing were
not added.

Public Chain evidence is evidence/hepta-real-native-adoption-20261108 at
280799323a28aeb6669526564c44699ddceed18c. Its 417 original files,
manifest, original reader inputs/outputs and bounded verifier preserve both
operations. Private source/patches/test archives and full base weights are absent.
The manifest SHA-256 is
09c7a6079af9497835062815b2a421b385969ad665139f1454cad25bb35be628.
The preceding 517-file v8 namespace is unchanged. New-candidate independent Cell
hosting, production FinalUse, funding, activation, Parameter V3 and Product OPE
qualification remain false; this actual research loop grants none of them.

### Maintenance after the exact edf03ec tests

The first scoped maintenance found two strict expect_used violations in the
new research material parser and its tensor fixture helper. The original
just fix exited 0 without changing source; strict Clippy exited 101. A second
maintenance retained an explicit four-element array after chunks_exact(4), which
preserves the exact finite-F32 acceptance set, but the fixture helper's replacement
unwrap was also correctly rejected by strict Clippy. Both original failures remain
in separate maintenance-v1 and maintenance-v2 directories.

The final maintenance makes the synthetic tensor fixture helper return Result and
propagates construction errors to its existing test. All original tensor rejection
assertions remain. This differs from the tested edf03ec bytes; no actual model PASS
is attributed to the maintenance source. Tests are not rerun after fix/fmt, following
AGENTS.md. Exact formatter/lint results and the tested-to-maintained file hashes
are retained in REAL_MODEL_ADOPTION_MAINTENANCE.json.

## Fresh OS-process owner replay (2026-11-09)

The follow-up at tested source `968430a3180baa3e64b7c275831595ae38c013c9`
(tree `2b0530ef5d0bbcdd1d2dbb2e3badd7d543a5e255`) completed two new
actual model operations through the original research paths. The exact nextest
archive SHA-256 is
`6901d46102d57a1aee8bee2ec51eafd922e62a3ada61b819a968eb271ab58d78`.
All 11,215 tracked source entries were checked against their original bytes before
and after each run. Fourteen existing actor and research-owner controls passed on
the same tested source.

| Operation | Original native test time | Restored receipts | Retained owner files |
| --- | ---: | ---: | ---: |
| `learning-5176-native-no-update-v2` | 45.729 s | 6 | 20 |
| `learning-5176-native-adopt-v1` | 51.789 s | 7 | 35 |

Each operation performed ten optimizer steps, eight evaluation forwards, one
source-task forward and one next-task forward. It retained the original
60-second nextest watchdog, zero automatic retries, 600-second research window,
four-core CPU quota and 8 GiB memory limit. The positive adoption remains a result
on the frozen four-prompt research comparison; it is not independent evaluation or
a general model-quality qualification.

After the original native actors stopped, three distinct native child processes
reopened the actual owner files. The completed probe read the original CURRENT,
guarded generation journal, exact next-task receipt, drained ACK state and
completed learning checkpoint. The two negative probes required refusal of a
different learning operation and a foreign CURRENT operation ID. All six child
processes across the two operations passed. The adoption probe also reopened the
concrete external-artifact owner and its retained sibling anchor.

The IPC context is bound to the original create-only `next-use-owner.json`
record. Constructing that context does not call `handle.step` again. Each child
checks the original request, receipt, nonce count and record digest before
comparing the original receipt with the reopened journal. Generation owner
files, and the external proposal/anchor files when present, must be byte-for-byte
unchanged around every probe. The original expiry is checked without renewal.

This is fresh-process owner readback under the research test owner. The native
parent remains alive to supervise its children. It does not launch or crash and
restart the full daemon, recreate production Root custody, authorize a new
dispatch or establish independent operation. `native_daemon_os_restart`,
`production_root_capability`, `production_final_use`, `production_activation`,
Parameter V3 and Product OPE qualification remain false; qualification remains
`HOLD_NO_GO`.

Retained unsuccessful attempts include the initial test-IPC digest serialization
compile error at `aaec9de151d1a7b2d459e830ed2f105fa83c8c26`, and the first
NoUpdate packaging attempt that exited before extraction because its destination
directory did not exist. That packaging attempt executed no native test or model
operation. Its original wrapper's `model_test_started` field meant only command
launch; an additional diagnosis preserves that distinction without rewriting the
failed record. Subsequent attempts use distinct operation directories.

Post-test scoped fix, strict Clippy and formatting are maintenance. Their source
delta is retained separately, and these native passes belong to the tested
commit above. Tests are not rerun after that maintenance.
