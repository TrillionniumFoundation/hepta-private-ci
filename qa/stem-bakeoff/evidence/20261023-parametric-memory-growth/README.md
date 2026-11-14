# Parameter memory: sequential arrival and cost-aware split rejection

## Outcome and acceptance status

The fixed sequential-arrival experiment completed on **2026-10-23 at
08:02:31 UTC**, exit 0, with **11/11 experiment gates passed**. An independent
audit of the actual weights, schedules, worker requests and raw outputs passed
**75/75 checks**, once, without changing its prepared checks or running models.
The continuation acquired all fifteen incoming shape assignments and preserved
all fifteen tested old color assignments. Splitting achieved the same quality
with twice the private parameter bytes, so the predeclared policy selected
**single continuation**.

This is a bounded, synthetic parameter-memory result. It establishes neither a
compression advantage nor beneficial autonomous division, learned routing,
general memory, statistical unlearning, or production readiness. Remote CI is
still queued/pending; **all blockers are not closed**.

Primary records:

- [Full experiment result](growth-confirmation-001/result.json)
- [Protocol fixed before training](growth-confirmation-001/protocol.json)
- [Selection saved before final reads](growth-confirmation-001/candidates/precommitted-selection.json)
- [Independent raw audit](engineering/review/growth-raw-audit.json)
- [Audit execution and witness hashes](engineering/review/growth-audit-execution.json)
- [Blocker register](blocker-register.json)

## Execution identity and lineage

The actual executed and published source commit was
`2b42a265e51ad2ac0d2127e8f6b81cc4fa4d1b3b`, tree
`78d3287f92f3abbca4843d746b975aed922c3d36`. Before/after source-content manifests
both equal `e27a70e290273ac321827e76c51143d59a4a869f655159c7fb2efa7a2041e3e9`.
The main process ran from 07:52:21.349143 to 08:02:31.890116 UTC,
**610.5409757 seconds**, with one model-run attempt and no tuning overrides.

The base was `HuggingFaceTB/SmolLM2-135M-Instruct`, revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`; its weights SHA-256 was
`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
The pinned CPU runtime used torch 2.5.1+cpu, transformers 4.57.1, peft 0.17.1,
numpy 1.26.4, accelerate 1.10.1 and safetensors 0.6.2.

The common parent was the prior lifecycle's actual clean `rebuilt-cell`:
manifest `c273d4555cc0dbb105fc38a674ac6963a43cf48c58d9fced6a38e373759c2e05`.
It contains fifteen retained sources, after Alice's two source versions were
withdrawn and Bob's corrected value was replayed. The retired original parent
was not reused. Every candidate inherits the clean parent's ancestry, including
the shape child whose new updates only train shapes. All inherited/new roots
were checked against the independently pinned epoch-1 revoked frontier.

This frontier is a local pinned snapshot, not a live authenticated external
authority. Disjoint lineage and blocked admission do not by themselves prove
that a model statistically forgot a deleted fact.

Before launch, all seventeen changed source blobs were verified against their
published Git objects. Exact copies of 122 files from the previous evidence
commit reappeared as untracked files during workspace synchronization. An
initial launcher guard stopped before any model run or output creation. Only
that verified, unchanged historical evidence directory was then allowed;
tracked source and execution HEAD stayed unchanged. This is recorded in
[launch preflight](engineering/main-launch-preflight.json),
[source reconciliation](engineering/source-reconciliation-before-run.json),
and [exit receipt](engineering/main-exit.json).

The previous experiment and its different source-attribution history remain
unchanged at [prior evidence commit 6edef799](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6edef799c9b90a3b768b3a8b1f21d84293ab041c/qa/stem-bakeoff/evidence/20261023-parametric-memory/README.md).

## Fixed task, selection, and actual outputs

Fifteen existing entities received a new `shape` relation. Values were assigned
once using seed 718203 from the registered vocabulary: circle, square,
triangle, oval, star, cube, sphere, cone. The decoder seed was 2718, LoRA rank
8 and learning rate 0.001. The vocabulary, templates, schedule and thresholds
were fixed before training. Training, source-selection and final question
wordings are distinct after tokenization. All facts were trained; this tests
recall under different wording, not unseen-fact generalization.

| Arm | New optimizer updates | Old final recall | New final recall | Total final recall | Private parameter bytes | Checkpoint bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nochange | 0 | 15/15 | 0/15 | 15/30 | 1,843,200 | 1,910,596 |
| Single continuation | 480 | 15/15 | 15/15 | 30/30 | 1,843,200 | 1,916,187 |
| Split | 240 + 240 | 15/15 | 15/15 | 30/30 | 3,686,400 | 3,805,650 |

Source-selection counts were also 15/30, 30/30 and 30/30. Every parent-correct
old item had to remain correct. Single needed at least one additional correct
answer over nochange; split needed at least two over the best eligible cheaper
arm. **Single was eligible; split was not.** Final scores were not used to
reselect, and the saved selection bytes remained unchanged. These thresholds
are explicit engineering policy, not a learned economic optimum.

Both trainable arms started from the same clean parent. They each consumed 480
updates and 26,736 input tokens, with sixteen visits per fact and four per
source/template. The experiment therefore performed **960 actual new updates
and 53,472 training input tokens** across all candidates. The comparison matches
updates and observed input tokens; it does not match private parameters or
prove equal FLOPs.

Four fresh reader processes consumed weights, provenance/scope metadata and
question strings. Their closed requests did not contain gold answers, fact
tables or an answer lexicon. Every worker ran within a local owner's validated
invocation and its journal was bound to the actual tensor state and admitted
version. Nochange's raw answers to incoming questions are unwritten-memory
diagnostics, not admitted knowledge claims. See the complete requests,
journals and [final result](growth-confirmation-001/final/result.json).

The split route was declared relation metadata: color to slot 0, shape to slot
1. It was not learned or discovered. A new relation acquired by one existing
architecture is also not a demonstrated new architectural cell type.

## Cost accounting and limits

| Cost | Actual observation |
| --- | ---: |
| Shared base on disk | 271,170,520 bytes |
| Loaded frozen base tensors | 538,060,032 bytes |
| Selected private parameters | 1,843,200 bytes |
| Selected complete checkpoint | 1,916,187 bytes |
| All three newly trained checkpoints | 5,721,837 bytes |
| Retained source ledger | 6,186 bytes |
| Actual SQLite exact-store baseline | 8,192 bytes; 30/30 correct |
| Local owner database | 28,672 bytes |
| Declared route metadata | 24 bytes |
| Single training | 255.0616 seconds |
| Combined split training | 250.1315 seconds |
| All new candidate training | 505.1931 seconds |
| Source-selection generation | 24.7615 seconds; 4,818 input tokens |
| Final fresh-process wall time: nochange / single / split | 16.6233 / 17.9976 / 25.5119 seconds |
| Parent-process peak RSS | 1,174,339,584 bytes |
| Maximum child-process peak RSS | 1,174,339,584 bytes |

The selected private tensors alone occupy **225 times** the measured SQLite
store, before counting the base, checkpoint metadata or retained replay
sources. Split private tensors occupy 450 times that baseline. There is no
measured storage advantage here. The SQLite timing (0.000214 seconds write,
0.003370 seconds read) is a tiny local benchmark, not a general performance
estimate. Parent and maximum-child RSS are not a simultaneous-process sum.

Historical costs were not reset to zero. The clean parent has 512 historical
updates, 28,480 input tokens and 267.7488 training seconds. Earlier original
and correction writes each had 512 updates, with 28,464 input tokens and
284.8945 / 272.4088 seconds respectively. The prior evolution research is
explicitly outside that upstream-write subtotal. The earlier full confirmation
and this run contain 2,048 + 960 updates, but that is not the entire project's
training expenditure.

The source ledger remains necessary for this implementation's correction,
withdrawal and clean replay. The experiment does not claim that parameter
memory can safely discard exact provenance or replace exact storage.

## Engineering defects closed and validation

| Defect | Actual before/after evidence | Resolution |
| --- | --- | --- |
| Continuation selected on a quality tie | [Failing regression](engineering/selection/tie-regression-before.txt), [passing regression](engineering/selection/evolution-regression-after.txt) | Require strict improvement; tie retains parent. |
| Peer withdrawal during checkpoint validation still entered callback | [Before](engineering/hardening/before.json), [after](engineering/hardening/after.json) | Recheck durable frontier/version after verification, immediately before callback in a short SQLite transaction. |
| FIFO could block bounded file reading | Same before/after receipts and [seven focused tests](engineering/hardening/focused-tests.log) | Require a bounded regular file; validate descriptor identity, conditional nofollow/nonblock flags and observable mutation. |
| Growth could use an obsolete parent without an exact pin | [Pinned protocol and provenance](growth-confirmation-001/parent-provenance.json) | Admit the actual clean replay and exact retained-source digest; reject revoked ancestry before training and reading. |
| RSS import/units were not portable | [Growth direct test log](growth-validation/test-growth-portability-direct.log) | Optional resource module, Linux KiB conversion, Darwin byte handling and explicit unavailable null elsewhere. |
| Execution source could be ambiguous | [Reconciliation](engineering/source-reconciliation-before-run.json), before/after source identities | Freeze the published HEAD and verify exact source bytes across the main run. |

The owner transaction supplies a **local admission linearization point**.
Changes after it may overlap an already admitted callback; postchecks reject
stale results. It does not claim atomic coordination with an external authority.
Filesystem protections that depend on operating-system flags are explicitly
conditional rather than a cross-platform atomic nofollow guarantee.

This stage passed **46 distinct test methods**: parametric 27, hardening 7,
catalog 6 and growth 6. The four evolution tests are included in the 27 and are
not counted twice. The growth suite uses a real tiny decoder, real writes and
fresh readers. [Validation summary](engineering/validation-summary.json)
binds the direct logs to their hashes. Earlier preflight/growth-five records
are explicitly labeled tool-output transcripts; they are not misrepresented
as direct logs or added to the 46.

`just fmt` completed with exit 0 after code changes. All 33 Python ASTs were
equivalent across formatting, with nine byte-formatted files; test source
identity was reconciled to the preformat snapshot. Per repository instructions,
test suites were not rerun after formatting. No Rust code changed.

The independent auditor prepared its script and captured source/protocol and
parent witnesses while the main run was still in progress, before selection
and final outputs existed. It then parsed actual safetensors, recomputed
schedules, recall and policy choice, checked four worker/owner bindings and
verified source/parent immutability. The 75 audit checks are artifact-integrity
checks and are not added to the 46 test-method count. The earlier review's
then-pending RSS note remains unchanged; the later direct regression and
validation summary record its closure.

## Reviewable code and remote CI

Each new PR is a draft stage with fewer than 500 changed lines; the original
nine PR heads remain unchanged.

| PR | Scope | Commit |
| --- | --- | --- |
| [3430](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3430) | Admission/file hardening and tie rejection | `4cd9bd85131ea0d95e4d607ecad3e64ea11c5a5f` |
| [3431](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3431) | Budgeted arrival candidates | `4970fe9f17b12a067992f0703329d0c93ef389f1` |
| [3432](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3432) | Pinned lineage and fresh-reader admission | `125c73bd561be77f2566438a59c39d0b60aa9784` |
| [3433](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3433) | Fixed sequential-arrival experiment | `f9884819bbfb23a04cc319e8b6643eebaeac5e07` |
| [3434](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3434) | Regression coverage and branch-specific shadow CI | `2b42a265e51ad2ac0d2127e8f6b81cc4fa4d1b3b` |

The full fourteen-PR snapshot at 07:53:39 UTC found all expected heads, all
draft/open and mergeable, no conflicts; 49 runs comprised 46 queued, one pending
and two skipped. Of 95 jobs, 93 were queued and two skipped. None had an assigned
runner or executed steps. A skip is not a successful test.

The later **08:06:13–08:06:19 UTC** bounded refresh covered only five critical
runs and PR 3434, not the whole stack: four queued runs, one pending run, nine
queued jobs, zero assigned runners, zero steps and zero failures. PR 3434 still
had the frozen source HEAD and `mergeable=true`. Snapshots are retained
[for the full stack](engineering/ci/remote-ci-stack-075339Z.json) and
[for the later critical subset](engineering/ci/remote-ci-critical-080619Z.json).

The new [run 39920456698](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39920456698)
has not executed. Its workflow covers six suites totaling 82 planned methods,
including prior QA suites, and deliberately does not download the pretrained
model or claim execution of the full growth experiment. The 82 are planned
remote coverage, not additional passing tests. There is no failed job to
repair or rerun yet. Required checks have not been bypassed, unrelated runs
have not been cancelled, and no merge or production acceptance is claimed.

## Artifacts and remaining gates

[Checkpoint archive receipt](engineering/checkpoint-archive.json) identifies
the separately retained four-snapshot ZIP: clean parent, selected single, and
both unselected split children. Actual owner SQLite state is retained in that
archive for replaying admission audits. The base weights are excluded. Selection
is experimental and does not activate any snapshot in production.

[Copy inventory](copy-inventory.json) maps the unmodified raw records to their
source paths and SHA-256 hashes. Binary payloads omitted from this Git tree are
listed with their hashes. Copied Python receipt scripts have a `.py.txt` suffix
so that formatters cannot rewrite their historical source bytes.
[Artifact manifest](artifact-manifest.json) hashes every other evidence file;
its own hash is supplied by the immutable Git tree, avoiding self-reference.

To progress beyond this bounded result, the remaining empirical gates are:

1. Actual execution and success of the outstanding remote checks on the
   expected source heads.
2. Repeatable division benefit under controlled interference/capacity pressure,
   multiple independent seeds and retained-data splits; a learned partition
   must be evaluated separately from the declared color/shape route.
3. Net resource benefit against exact and retrieval stores at scale, counting
   shared-base amortization, source replay, all retained versions and training.
4. Heterogeneous episodic/procedural/factual memory, temporal updates,
   out-of-distribution queries and lifecycle behavior on a live authenticated
   authority. Production acceptance requires evidence beyond this experiment.

The present design therefore keeps a costed continuation/split decision and
strict lineage/admission around trainable cells. It does not force division
when measured quality gives it no benefit, and does not turn this successful
small recall experiment into a claim of a self-organizing general memory.
