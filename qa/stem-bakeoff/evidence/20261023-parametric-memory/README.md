# Parametric memory: completed local confirmation and review evidence

The real SmolLM2 local confirmation completed with **17/17 mechanism gates true**.
The [original result](confirmation-001/result.json) records
`mechanism_gate_passed=true`, while `production_accepted=false`,
`compression_advantage_proven=false` and `general_memory_proven=false` remain
explicit. This is a bounded parameter-memory experiment, not deployment acceptance.

## Completed confirmation results

The [predeclared protocol](confirmation-001/protocol.json) uses 16 source facts,
cohort seed 95873, rank 8, model seed 2718, 512 source-training steps and learning
rate 0.001. Training templates, selection wording, final query wording and quality
thresholds are recorded separately. The value vocabulary was fixed before source sampling;
readers generated raw full-vocabulary answers without receiving source values or
an answer lexicon.

| Check | Observed result | Original report |
| --- | --- | --- |
| Trained adapter, fresh-process held-out wording | 16/16 exact matches | [Adapter journal](confirmation-001/adapter.journal.json) |
| Same questions, adapter disabled | 0/16 | [Base journal](confirmation-001/base.journal.json) |
| Same questions, shuffled adapter tensors | 0/16 | [Shuffled journal](confirmation-001/shuffled.journal.json) |
| Executed SQLite key/value baseline | 16/16; 16 actual SQL reads | [Baseline](confirmation-001/key-value-baseline.json) |
| Training-template recall | 16/16 | [Raw generations](confirmation-001/training-template-generation.json) |
| Nochange / continue / split routed networks | 16/16 for each; chosen arm `continue` | [Network result](confirmation-001/network/result.json) |
| Correction | Revised facts 2/2; retained facts 14/14 | [Lifecycle result](confirmation-001/lifecycle/result.json) |
| Clean-base replay after deletion | Remaining facts 15/15 | [Replay receipt](confirmation-001/lifecycle/clean-replay-write.json) |
| Withdrawal enforcement | Five rejected cell invocations; zero model forwards | [Lifecycle result](confirmation-001/lifecycle/result.json) |

All three network arms also scored 16/16 during source-derived selection. The
predeclared rule selected `continue` before final scoring. Continue and split each
used two private adapters, 256 total optimizer steps and 14,232 input tokens; the
saved parent remained unchanged. **This experiment observed no accuracy benefit
from division, or from continuation over the unchanged parent.** The ceiling on
this small cohort does not establish whether splitting helps larger workloads.
Both candidate arms and their search costs remain in the
[evolution report](confirmation-001/evolution/evolution.json).

The 17 gates cover source exposure, frozen-base integrity, exact fresh-process
reload, matched prompts, no inference writes, recall and control differences,
correction/retention, clean replay, descendant withdrawal, matched split budgets,
selected-network recall and preservation, and unchanged Python source bytes. Their
individual booleans are preserved in `result.json`; none were replaced by a summary
pass flag.

### Binding measurement and unresolved forgetting behavior

The post-generation [binding measurement](confirmation-001/binding-specificity.json)
used 32 real full-vocabulary decoder forwards and eight distinct-source pairs.
Mean symmetric swapped-value margin rose from **-0.285686** with the adapter
disabled to **10.097099** with it enabled, a delta of **10.382785**. Both per-question
margins were positive in 0/8 pairs before and 8/8 afterward. The measurement made no
generation or training calls, changed no weights, and had no selection authority.

Warm-start children retained every inherited source root. Withdrawal rejected the
corrected memory slot and all four learned descendants before their callbacks
could execute a model forward. Owner restart also rejected an older withdrawal
frontier. Recovery reset to the frozen base, inherited no old adapter roots and
replayed exactly the 15 remaining facts.

The direct raw decoder diagnostic after recovery still returned **`orange`** for
the deleted Alice query and **`blue`** for the unknown Zelda query; see its
[original request](confirmation-001/lifecycle/unknown-diagnostic.request.json) and
[raw journal](confirmation-001/lifecycle/unknown-diagnostic.journal.json). Those
answers are not abstentions. This diagnostic is separate from the owner path that
rejects a query carrying a withdrawn root. Clean-base replay and provenance
rejection therefore must not be described as certified parameter unlearning or
reliable unknown-answer behavior.

## Measured storage and work

| Item | Actual bytes |
| --- | ---: |
| One cell's private trainable parameters | 1,843,200 (1.8432 MB) |
| Saved parent checkpoint, including metadata | 1,910,870 |
| Optimizer tensors during its write | 3,686,880 |
| Shared base model directory | 271,170,520 |
| Loaded frozen base tensors | 538,060,032 |
| Original source JSON file | 3,300 |
| Executed SQLite database image | 8,192 (8 KiB) |

These values come from the [trial costs](confirmation-001/result.json),
[write receipt](confirmation-001/write.json) and executed SQLite report. The private
parameters alone occupy **225 times** the SQLite database bytes on this cohort.
The SQLite database has two actual 4096-byte pages; this is database image size,
not process RSS or a disk-durability measurement. Its compact source JSON encoding
is 2,722 bytes, distinct from the original indented 3,300-byte source file.

The source write performed 512 optimizer steps, consumed 28,464 input tokens and
1,024 supervised tokens, and took 284.894 seconds in this run. SQLite wrote 16 rows
in 0.000535 seconds and parsed/read all 16 questions in 0.001474 seconds. These are
single-run timings with their respective scopes, not a repeated performance
benchmark. The system must additionally retain and charge for the source ledger,
provenance, owner state, router, inactive versions, replay data, candidate search
and runtime memory. **No compression advantage was demonstrated.**

The cohort has 16 entity/color assignments from eight predefined single-token
values, at most 48 bits of value-assignment entropy before cohort constraints.
Entities, scope and provenance cost additional storage. Held-out query wording
tests recall of written facts; it does not demonstrate unseen-fact acquisition,
independent natural memory tasks or a general memory system. The network ran on
one physical host without distributed consensus. Fresh interpreters and closed
JSON inputs are not OS sandboxes, and the local owner does not authenticate its
host-provided source authority.

## Preserved records and integrity

| Directory | Original evidence retained |
| --- | --- |
| `confirmation-001/` | All 77 UTF-8 JSON/text/Markdown files, including protocol, source facts, identities, reconciliation, receipts, closed requests, raw journals, nested configuration and lineage |
| `development-recovery-001/` | Actual recovery result, all three closed worker requests, raw adapter/base/shuffled journals, stderr and recovery source identity |
| `development-original/` | Original write receipt, protocol, source facts, initial identity, in-memory/training-template generations, interruption stderr and checkpoint lineage/configuration |
| `independent-review/` | Original review summary, observed integration output, review manifest and preserved integration script |
| `catalog-admission-001/` | Actual real-checkpoint admission result, raw reader request/journal, metadata-only catalogs, source identities, integration script and pre-format source snapshot |
| `runtime/` | Actual pinned model acquisition receipt and local Python package inventory |
| `remote-ci/` | Separate timestamped GitHub run/runner observations, including queued states |

[copy-inventory.json](copy-inventory.json) records each original path, copied path,
byte count and SHA-256. The 116 copied files total **1,129,508 bytes**; the largest
is **77,281 bytes**, below the 500 KB per-file limit. Original and copied bytes and
all recorded hashes were checked. The 77 confirmation files contribute 850,359
bytes. Binary base/adapter checkpoints, SQLite databases and bytecode caches are
excluded. Checkpoint directories here contain metadata, not reloadable tensor
artifacts. Absolute paths within archived requests, manifests and scripts remain
unchanged historical execution records.

The copied confirmation parent lineage hashes to
`c22b8bb5ee8fc94062818d8e8442d185511c7bdd7bb7554d92c8319a92c22d2a`,
matching the result's checkpoint identity. No tests or experiments were rerun while
assembling this bundle. This README reports local confirmation only; it makes no
remote-CI-pass claim. Catalog evidence and later CI observations are separate
additions, not changes to these raw run files.

## Confirmation source identity reconciliation

The untouched [start identity](confirmation-001/source-identity.json) records HEAD
`7aac712474b850858d4d72b46419e39a3315d200`; the untouched
[end identity](confirmation-001/source-identity-after.json) records
`1e12dbb8187a007134b83928cfc25e663899ac9a`. Their 24 Python file hashes and aggregate
source manifest are identical. Before launch, those file bytes had already been
checked against the published latter commit. An initial Git index refresh needed
a promisor-object fetch; HEAD/index refresh completed later without changing the
working Python files.

The separate [source reconciliation](confirmation-001/source-reconciliation.json)
retains both commit identities and per-file SHA-256/Git blob identities. Its file
hashes match both original identity records. It records
`source_files_changed=false` and
`all_executed_python_bytes_already_matched_published_commit=true`. No recipe change
or score-driven tuning occurred during this reconciliation. The original HEAD
record was not retroactively edited. This attestation applies to confirmation;
it does not relabel development as a frozen-source experiment.

## Earlier development and independent review

The [development recovery result](development-recovery-001/result.json) separately
records 16/16 adapter recall against 0/16 base and shuffled controls. An environment
interruption happened after training. Recovery reused the saved checkpoint with
`training_repeated=false`; its manifest digest
`00cf0b82fb117a5e01a0d57e7c9d6673883f97db860e53a8e2dea0d7c80ad57a`
matches the copied original development lineage. Development happened while code
was changing, and its original training/recovery identities remain separate.
There is no separate original development `save.json`; lineage and the write
receipt are the retained save-related metadata. The confirmation result does not
retroactively remove these development limitations.

[review_summary.md](independent-review/review_summary.md) distinguishes actual
reviewer executions from root-reported results. Its
[review_manifest.json](independent-review/review_manifest.json) hashes the summary,
integration script and observed output; all three hashes match. The review labels
source-hash capture as after execution, not evidence of a frozen run. It used a
real tiny decoder and fresh worker processes to exercise ownership, routed arms,
correction, withdrawal, restart rejection and clean replay. Temporary models and
journals were removed at normal exit. Its preserved text is a historical review,
not a retained checkpoint bundle or a SmolLM2 accuracy result.


## Typed admission follow-up

The raw unknown guesses above motivated the separate metadata catalog in
[catalog PR #3417](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3417),
commit `cbd139ad7cfeaf0be226688f2475cdeb364aa3e1`. The new API binds a typed
entity/relation key and source digest to an independently pinned active checkpoint.
Its catalog contains no answer values, gold labels, source text or answer lexicon.

The [actual admission result](catalog-admission-001/result.json) reused the clean
replay checkpoint at generation 2. A single fresh decoder process returned Bob's
raw `orange` exactly. Never-written Zelda and deleted Alice returned `unknown`
without a model callback. A stale catalog was rejected; a separately activated old
checkpoint with a matching catalog was also rejected by the withdrawal frontier.
The four blocked cases made zero model callbacks, and this follow-up performed
zero optimizer updates. The [closed worker request](catalog-admission-001/known.request.json)
and [raw journal](catalog-admission-001/known.journal.json) are retained unchanged.
This is service admission evidence, not model-intrinsic abstention or unlearning.

The [validation summary](validation-summary.json) records 69 passing local test
methods: 27 parametric, 22 prior evolution, 14 prior process and six new catalog
tests. The catalog unit execution was reported by its delegated implementation
agent; the real-checkpoint follow-up was executed by the root agent. Both catalog
Python files were tested before required `just fmt`, then checked for identical
ASTs after formatting. The pre-format source is retained for that comparison.
No tests were rerun after formatting. The full core confirmation ran on the earlier
frozen Python bytes; it is not relabeled as a full trial on the new catalog commit.

## Checkpoint download record

The accompanying `hepta-parametric-memory-checkpoints-20261023.zip` contains all
seven actual LoRA snapshots with config/lineage files and a per-file index. The
[archive receipt](checkpoint-archive.json) records 12,065,470 bytes and SHA-256
`83826b60109fc4ccaaaff045b10345a7f1ccea9d5e593661e957f205e49f3e1b`.
All internal hashes and ZIP CRCs were checked. The base model is excluded.
Only `lifecycle/rebuilt-cell` has no withdrawn ancestry under the final frontier;
six retired snapshots are retained for research/audit and must not be served under
that frontier. Retaining them explicitly rules out a physical-erasure claim.

## Review stack and remaining external gate

| Stage | Pull request |
| --- | --- |
| QA withdrawal-frontier regression fix | [#3401](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3401) |
| Mechanical dependency foundation | [#3402](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3402) |
| Decoder-only source writer and tests | [#3403](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3403) |
| Durable local version owner | [#3404](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3404) |
| Matched-budget evolution | [#3405](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3405) |
| Closed transport and measurements | [#3406](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3406) |
| Routed network and lifecycle | [#3407](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3407) |
| Full confirmation protocol and shadow CI | [#3408](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3408) |
| Typed metadata admission | [#3417](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3417) |

At **2026-10-23 07:11:35 UTC**, the exact-source full-confirmation
[push run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39912356783)
and the new
[catalog run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39916012060)
were queued. The [latest status snapshot](remote-ci/status-071135Z.json) explicitly
distinguishes current run observations from older job metadata. The earlier
[runner snapshot](remote-ci/snapshot-064709Z.json) records the wider queue context.
Observed lack of assigned runners is consistent with shared backlog; no exact
quota or root cause has been established. Local success is not remote CI success.
The PRs remain drafts. No production gate was relaxed, status fabricated, or other
contributors' jobs cancelled to hide that external blocker.
