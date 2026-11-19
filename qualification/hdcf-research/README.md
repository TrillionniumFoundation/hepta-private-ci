# HDCF shadow qualification: Stem economics, graph consistency and trained Cells

**Status: RESEARCH_ONLY / DENY_ALL / NO MODEL SELECTION / NO CODE EXECUTION.**

This standalone Python standard-library experiment changes no live Neuron,
NDU, CellSplit, CAS, CNS, TaskFlow, FinalUse, Agentd, GPU or OS effect owner.
It is a *separate* research layer, not a second runtime or production solver.

## Scope

1. `hdcf_gates.py`: weight-only shared-vs-replicated Stem accounting, and
   numeric forward/backward interface, terminal and budget checks in a finite
   topologically ordered reasoning graph. These checks are **not** a global
   stochastic FBSDE theorem, an NDU proof or a performance comparison.
2. `physical_bank.py`: actual CPU float64 SGD for two Cell-type-specific Heads
   under the same physical **2*(dimension+1)** parameter inventory.
   Frozen, equal-step shared-dense, equal-step/equal-touch shared-one-touch,
   split, and wrong-type-routing controls are predeclared. Shared and split
   use the same initial weights, training example ordering and update count.
   Per-arm actual CPU/wall nanoseconds and estimated parameter touches are
   recorded separately. **SGD steps do not imply equal FLOPs, tensor RAM,
   training power or full lifecycle cost.**
3. `physical_cli.py`: two-process training/review entrypoints. Training
   requires `fit` target labels, and rejects *any* target field in held rows.
   The review process alone reads blind held targets; exact case IDs,
   families, Cell types and prediction census must match. No model weights,
   source text, secret or privileged executable is written to research outputs.

## Reproduce standard-library regressions

```sh
cd qualification/hdcf-research
python3 -m py_compile hdcf_gates.py physical_bank.py physical_cli.py test_*.py
python3 -m unittest -v test_hdcf_gates test_physical_bank test_physical_cli
python3 -O -m unittest -v test_hdcf_gates test_physical_bank test_physical_cli
```

## Physical original-input protocol

Construct an original bounded `hepta.hdcf.frozen-feature-bank.v1` JSON file:

- `producer`: asserted SHA-256 identities for Encoder, preprocessing and
  original source; generation and principal. This is NOT a trusted signature.
- `types`: exactly two declared Cell categories; `dimension`: 1–256.
- `fit`: 8–2048 rows, each with unique `id`, `family`, declared `type`,
  finite float vector and binary `target`; each Cell type contains both labels.
- `held`: 4–1024 rows with unique `id`, `family`, `type` and finite vector,
  **without target**. Family identities must not intersect training families.
- Independently hold a second `hepta.hdcf.blind-targets.v1` JSON file with
  the same bundle digest and exactly all held `id/family/type/target` rows.

Run producer and reviewer as **different OS processes**, using distinct inputs:

```sh
python3 physical_cli.py train --features frozen-features.json --out trial.json
python3 physical_cli.py review --predictions trial.json --targets held-private.json --out review.json
```

Both inputs reject symbolic links and ambiguous JSON keys; outputs are
create-only regular files with 0600 permissions and fsync. This is not a
sandbox, cryptographic source custody or a durable production transaction.

## What the included synthetic fixture demonstrates—and does not

`test_physical_bank.original()` creates a **deliberately conflicting linear
classification problem**. Equal-parameter Cell-type-specialized linear Heads
are mathematically suited to that fixture. The observed local 32-case review
was **frozen 16/32, shared dense 16/32, shared one-touch 16/32, split 32/32,
wrong-type route 0/32**, under 256 actual training steps per trained arm.
This is deterministic CPU scalar mechanics and a useful negative routing
control, **not** genuine pretrained Encoder features, native Transformer
forwards, general semantic reasoning, independent out-of-family human task
results, future windows or statistically generalizable superiority.

To qualify a real Stem, export features from a physically executed and
immutable approved pretrained Encoder, preserve real source/publisher and
case family IDs, isolate held labels in a different owner, and compare
same-source, same-Reader complete task outcomes with authentic cost receipts.
See original public Encoder research PR #1825 and follow-up provenance
boundary #2462. Full Encoder work, training, reading, evaluation, cache reuse,
optimizer state, resident memory and rollback must all enter real TCO.

## Hard nonclaims and future owners

No automatic Cell Split; no System2 reasoning efficacy; no general FBSDE
existence/uniqueness; no 10T equivalence; no multiple-modal generator; no
native executable memory, GPU launch, OS UI action, FinalUse or effect grant.
Never treat a `True` field, task score, model hash or graph continuity result
as independently signed source truth or task authorization. Unverified
source provenance stays `false`; production and external effect authority
always stay `false`.

The authoritative repository boundaries are `docs/DEVELOPMENT.md`,
`docs/learning/NDU_FBSDE_SPEC.md`, `docs/cns/TECHNICAL.md` and
`docs/hnmf/TECHNICAL.md`. Subsequent real deployments belong inside
existing owners, not this research folder.

## Original pretrained ModernBERT byte-level continuation (V3)

`original_canary_audit.py` **independently opened the actual GitHub Actions artifact**
`11877613315` (run `38523539731`), exact ZIP SHA-256
`fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a`.
Its immutable upstream execution HEAD is `758205d3de23ccbf76649b1446c271101dc917b0`.
The archived original public checkpoint revision is
`8949b909ec900327062f0ebf497f51aef5e6f0c8`, using the original
BANKING77 source commit `57ec275d8078af65b7731c2a98be812d844a6d6b`.

The validator rechecks all original ZIP member names and bytes, SHA-linked
terminal records, public-input census, model receipt, physical safetensors
header/data geometry and **all original FP32 Head tensor bytes**. It independently
recomputes the 395,776-parameter trained state digests for both original banks,
not just their self-reported hashes. The original reported heldout accuracies
are Dense16 23/32 and Sparse Top-2 17/32; *the raw private heldout labels are
absent from the original archive*, so this new audit **does not** independently
rescore accuracy. Original trained tensor validity does not imply full model
publisher authentication or permission to use a model in production.

The source-only tests include adversarial duplicate-key/NaN, tensor overlap,
missing ZIP member, changed original ZIP bytes and exact original archive tests
when `HDCF_ORIGINAL_CANARY_ZIP` is provided. **Unprovided original bytes cause
explicit skips rather than a fabricated successful physical model audit.**
A read-only workflow downloads the fixed original artifact, checks its exact
SHA, and reruns the audit before attempting a new model inference.

## V3 new pretrained feature producer: deliberately separate trial

`modernbert_feature_bridge.py` is a new **real-Encoder execution adapter**,
not an assertion that the old archive contained reusable features. It binds the
original source code commit, original model/checkpoint digests and original
BANKING77 64-fit/32-official-test inputs. All 96 samples require new physical
pretrained Encoder forwards (plus the upstream three-case probe). The stages
are separate GitHub Actions jobs:

1. Acquire the exact original public source; stage label-free held text in a
   **public-input artifact** and held targets in a separate reviewer-only
   artifact. The initial source-owning stage sees labels; this is not a
   cryptographically blind publisher or secure data enclave.
2. Load only the pinned original, complete ModernBERT checkpoint using the
   *unchanged upstream loader*. Export all 96 L2-normalized 768D actual
   feature vectors, token counts, CPU/wall clocks, RSS and a content digest.
   No held targets are passed into this producer or uploaded with its output.
3. Run the existing five-arm physical CPU HeadBank on those frozen features.
   Its reported `encoder_forward_count=0` means **zero additional forwards in
   Head training**, not zero original upstream Encoder work.
4. In another OS process, join the prior source-owner held targets to the
   terminal five-arm predictions. Reject source, ID, train labels, Cell-type,
   model, generation, projection or prediction drift.

The Cell `type` is predeclared as parity of a domain-separated SHA-256 over
original case IDs; it is **not** inferred from the test label or fitted on
held outcomes. For this exploratory binary task the four original intent
labels become `original_label % 2`. Its scores are **not** comparable to the
historic 4-class Dense16/Sparse accuracy and do not show learned semantic
Cell differentiation. The `family` field is a train-vs-test **partition**;
both partitions still belong to the same BANKING77 publisher/dataset family.
`source_family_independence_verified` remains false.

The exact-head hosted workflow is
`.github/workflows/hepta-hdcf-modernbert-original.yml`. Running it requires
actual network acquisition and CPU inference on GitHub Actions; source-only
unit tests or local mock tensor tests are not substitutes for its completed
physical model/Head/independent-review receipts. It never installs artifacts,
performs hardware effects, activates NDU, changes production model selection or
bypasses `blocking-ci`.


## V4 independent historical public-label scoring (no new model claims)

The original GitHub Actions ZIP has no raw BANKING77 test-label CSV, so the
existing ZIP-only `original_canary_audit.py` correctly reports that it **cannot**
independently score the reported accuracies. The new *separate*
`public_source_recount.py` explicitly obtains the **original fixed publisher**
train/test CSV bytes at commit `57ec275d8078af65b7731c2a98be812d844a6d6b`,
requires exact SHA-256 for both files, independently reconstructs original
case selection/normalization and IDs, and scores the **unaltered** archival
per-case logits (both before and after training). It checks accuracy, NLL,
multiclass Brier and per-class accuracy against the old report and fails closed
on any discrepancy, missing prediction, source mismatch or numerical error.
This retrospective scorer is an audit process, **not** an Encoder/Head worker;
no raw publisher CSV, test labels, or selected source text are committed or
uploaded with the new HDCF model-training artifacts. It outputs aggregate
measures only.

Run against original files in an isolated review environment:

```sh
python3 public_source_recount.py \
  --train /private/verified-original/train.csv \
  --test /private/verified-original/test.csv \
  --archive /private/11877613315.zip \
  --out /new/independent-historical-review.json
```

Verified original public source SHA-256: train
`b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`,
test `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`.
The historic 32 heldout case IDs were reconstructed from the actual published
CSV bytes and matched one by one to the exact source-selected IDs from the
archived producer. Recomputing metrics directly from the archive predicts:

| Historical arm | Before | After | After mean NLL | After multiclass Brier |
| --- | ---: | ---: | ---: | ---: |
| Dense16 | 8/32 | 23/32 | 0.6915541568258448 | 0.3820432498685225 |
| Sparse Top-2 | 9/32 | 17/32 | 1.0150894535640618 | 0.5770228329211649 |

These numbers are **historical retrospective on the same public dataset**;
there is one publisher/family and no prospective future source. They do not
establish independent model publishing/signatures, real HDCF V3 five-arm benefit,
production eligibility, head-selection advantage at matched total cost, or
NDU/System2 effectiveness. The exact-source GitHub Actions job executes the
full raw-CSV-to-archived-prediction verification on current research source.

## V5 independently replayed physical Head updates and source-preflight fence

`independent_head_replay.py` is a separate scalar implementation of the
existing original five-arm mathematical training procedure. It receives only
one immutable, source-identified feature bundle, the producer's terminal trial
JSON and an **externally preregistered** `{steps=256, seed=7347, lr=0.05}`
training profile. It independently reconstructs actual float64 initial weights,
training example order, each scalar SGD update, final physical parameter bytes
and all 160 held-case probabilities. A changed parameter digest, wrong example,
forged prediction, altered budget, inconsistent train CPU counters or missing
arm is rejected. The `independent-blind-review` task now requires this replay
**before** releasing blind aggregate scores. The sample replay itself does not
authenticate original model features, physical host, process duration, end-to-end
cost or future-task generalization.

The original pretrained Bridge also verifies the immutable historical
BANKING77 selection ID `95dc97bd0700165b431d140e77c35500713bc95dd3f6c31b6dabb9e021d26fad`
and original train/test CSV SHA, recomputes the original input content digest,
and verifies both binary labels are represented in each preregistered Cell type.
For the **real CLI only**, these checks reject wrong source bytes before actual
model work; mock tests retain an explicitly non-authorizing source seam. This
preflight never searches for a better source partition or retunes Cell routing.

Local regression scope (not a GitHub workflow-pass claim): the 52 available V3/V4/V5
CPU/bridge/archive tests passed normally and with Python `-O`, including the
original pinned 2.9 MiB archive without skips when its environment path was
supplied. The first V1 `test_hdcf_gates.py` suite is a separate retained CI
source test and was not mounted in this isolated local checkout. Hosted
exact-head HDCF, source-plus-merge architecture, and blocking CI must all
complete before scoped source qualification. Production stays **DENY_ALL**.


## V6: independent paired-science and paid-work HOLD_NO_GO gate

`paired_utility_gate.py` is now on the authentic retrospective-Encoder
`review_original` path after exact feature/input and blind target admission. It
independently replays all three actually *trained* strategies (256 scalar SGD
updates each, or 768 total); Frozen and swapped-route are 0-update
comparators. It checks source IDs, the original 32 paired test opportunities,
all 160 terminal predictions, every Head-state digest, exact normalized unit
probabilities, original target identities, and reported head cost inventories.
It computes descriptive paired wins/losses/ties and exact McNemar conditional
case-level probabilities against Frozen. Even a small p-value on 32 correlated
items from one dataset family does not qualify as an independently sourced
longitudinal improvement.

The explicit disposition is `HOLD_NO_GO`: independent external publisher
sources = 0, independently observed prospective future windows = 0, verified
full Encoder+Head+Reader+evaluation lifecycle TCO = `null`, self-reported
CPU duration is unattested, and **NDU System 2 improvement is unverified**.
A numerical score cannot change `production_authorized=false`, cannot
self-authorize model promotion, cannot emit executable machine code, and
cannot activate physical Cell Split. Real future sources plus independent
task/effect reviews and full measured cost are needed before any stronger
assertion. This is a *science gate*, not a new permanent data owner.

Run the added test in standard and Python optimized mode:

```sh
python3 -m unittest -v test_paired_utility_gate
python3 -O -m unittest -v test_paired_utility_gate
```

## V7 staged-only reviewer-source correction (non-authorizing)

Previous V6 `review_original` checked the 32 blind-row identities/types and
binary target envelope but **did not independently recompute each target value
from the pinned original publisher test CSV**. A different binary label under
an unchanged source ID could therefore be accepted as a task outcome. This is
an evidence-authenticity blocker, not merely a lower accuracy value.

`held_target_source_revalidation.py` repairs this by independently parsing the
precommitted original BANKING77 train/test CSV byte streams after training,
reconstructing the exact 64+32 source selection and original four-class labels,
checking every training label, checking all 32 blind binary labels, and checking
the label-blind type route separately. Any changed source byte, target, type,
row order, omitted record or source ancestry fails closed. The review CLI now
requires `--publisher-train` and `--publisher-test`: unlike training or the
model producer, only the reviewer can read these source labels.

A small dedicated source-only GitHub workflow executes the exact publisher
source preparation, then re-fetches both fixed source files in a reviewer-only
step and checks this new no-model reviewer. No pretrained forward is claimed
by the source-only workflow. The pending original **V6 heavyweight physical
Encoder run is deliberately not cancelled or mutated**: this repair is staged
as an independent child PR. Reconcile the child through normal source/merge
checks before the next physical training candidate.

The new result confirms only exact source **byte agreement** against known
Git/SHA values and correct reconstruction. It does not cryptographically
authenticate the publisher, prove genuine independent/future dataset efficacy,
attest CPU/GPU timings, or authorize any effect, new Cell, or production model.
No reviewer signature is invented. All output is `DENY_ALL`.
