# V13: trained semantic memory cells and structural qualification

## Result and scope

This research run implements all five experimental mechanisms: a genuinely pretrained
shared encoder and trainable cell, strong same-information controls, fixed cell
cooperation, learned sparse routing and split candidates, and complete adapter
continuation across workers. The scientific acceptance gates remain separate from
having executable code.

**The current experiments do not establish an economically superior general memory
system or beneficial self-division.** A small parametric cell learns new project
bindings and answers authored unseen wording, but it forgets some original skills.
Ordinary classifiers, retrieval, and exact project storage remain strong alternatives.

The learned function selects one of twelve existing standard-library operations or
maps a project name to its current operation. The supplied Python executors perform
the actual Unicode, JSON, CSV, sorting, counting, and deduplication algorithms.
This is a feature-space residual adapter on MiniLM embeddings, not Transformer LoRA
or an open-ended generative language model. The research code lives in this
qualification directory; native Hepta production authority is not activated.

| Requested gate | Executed result | Acceptance |
| --- | --- | --- |
| Real semantic/skill cell, updates and retention | Unseen wording 59/61/61 correct out of 72; new bindings learned; final old skills 52/55/48 | Parametric learning demonstrated; retention requirement remains open |
| Strong baselines and complete cost advantage | Ridge 61/72; exact project KV 12/12; actual query encoder costs and stored bytes measured | No task with an established complete-cost advantage found |
| Fixed typed cooperation and interpretable intervention | 288 intervention traces repeated in a second process; all semantic traces identical | Functional dependency and reproducibility demonstrated; exclusive specialization advantage absent |
| Learned routing and useful splitting | Gradient-conflict candidates 52/56/56; continue 59/61/61; fixed groups 59/59/59 | Beneficial split not demonstrated |
| Cross-node continuation and positive network economics | Three real VM jobs restore the backend and reproduce complete 90/97-step states under a checked numerical profile; the earlier strict failure is retained | Exact continuation passed under that profile; network economic advantage not demonstrated |

## Frozen experiment

The shared backend is `sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. All eight downloaded official files
have pinned byte identities. The ONNX weights occupy 90,405,214 bytes and have
SHA-256 `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452`.
The complete encoder/configuration/runtime identity is
`8b8d070f392fd30181f217daa4de166dfe785897b5d4d64f2244bc6fcb5f42aa`.

The encoder performs real CPU inference, attention-masked mean pooling, and L2
normalization. It returns 384-dimensional vectors. There is no hash-vector fallback.
The cell has `h = x + tanh(x A) B`, followed by a trained classifier, with rank 8
and 10,764 trainable float64 parameters. A/B/W/b all receive real gradients. The
reference intentionally keeps numerical state explicit; this is not an optimized
serving implementation.

`EXPERIMENT_PROTOCOL.json`, `TASK_PROTOCOL.json`, and
`evidence/inputs/EXECUTED_SOURCE/` contain the pre-execution method and source
snapshot. The independent hand-authored splits contain 120 training requests,
48 calibration requests, and 72 held requests. There are twelve fixed operations,
twelve public-decomposed two-step compositions, and three projects evaluated at
four version frontiers. Three optimization seeds rerun the same tasks.

Post-run wording audit found zero exact normalized train/test matches; the maximum
token Jaccard was 0.3846. This audit neither selected examples nor proves population
independence. Payload fixtures repeat, and project snapshots are related. The
benchmark is small, authored, and not production traffic.
"Unseen" here means absent from this supervised training split; overlap with the
pretrained encoder's original corpus has not been audited.

## 1. Single-cell learning, updates, and source ownership

| Method | Seed 713 | Seed 971 | Seed 1237 |
| --- | ---: | ---: | ---: |
| Single adapter | 59 | 61 | 61 |
| Continue same adapter | 59 | 61 | 61 |
| Ridge on identical frozen features | 61 | 61 | 61 |
| Class centroid on identical features | 60 | 60 | 60 |
| Nearest training example | 58 | 58 | 58 |
| BM25 over identical training requests | 42 | 42 | 42 |
| Exact normalized request dictionary | 0 | 0 | 0 |

Counts are successful execution outputs out of 72. Exact-request lookup rejects
all unseen addresses, so its low latency is not an effective semantic baseline.
The separate project KV control is strong: it reads the legal current operation
using the project name present in the public query, and gets every project case
right.

Project learning queries contain the project name and payload, without a live
policy or operation ID. The source events supply supervised training labels.
All final replay models answer 12/12 project held requests. The earlier amber
correction produces 11/12 for seeds 713 and 971, and 12/12 for seed 1237. Frozen
pre-update models answer only 0–4/12 across these versions, confirming that the
new bindings require an actual update.

| Original-skill retention at the final frontier | Seed 713 | Seed 971 | Seed 1237 |
| --- | ---: | ---: | ---: |
| Frozen parent | 59 | 61 | 61 |
| Update with all currently valid skill replay | 52 | 55 | 48 |
| Update without original-skill replay | 9 | 9 | 11 |

Replay and no-replay have the same number of updates, but not the same example
presentations; the latter sees 18 project examples instead of 138 combined rows.
Per-question losses and gains, by operation, are retained in
`evidence/analysis/ANALYSIS.json`. Source lineage identifies fitted dependencies;
it does not provide a causal explanation of each parameter or a precise factual
citation for every answer.

`provenance_run.py` separately trains from source-owned snapshots. It does not
relabel an already trained checkpoint. The source cut includes revision and body
hashes, and the adapter's source identity is updated by actual training. Immutable
artifacts include parameters, Adam, RNG, sampler, and dependencies. Publication
uses a transaction, expected epoch, freshness check, and executable validator.

Frontiers 0/3/4 publish at epochs 1/2/3. Frontiers 5/6 are rejected because original
skill calibration is 39/48 and 38/48, below the required 40. Their old release is
already stale, so both stages have zero valid reads out of the 84 evaluated
requests. Successful calibration at frontiers 3/4 still allowed held retention
to fall from 59 to 52/53. Source integrity and calibration therefore do not imply
good held performance or uninterrupted availability.

The final revocation occurs after the release is already stale. Its receipt
correctly says `isolated_readable_to_blocked=false`; it is not an extra active
revocation success. Independent lifecycle tests cover correction/revocation and
two genuine SIGKILL publication boundaries. Revocation fences serving; it is not
machine unlearning or erasure of historical weights.

## 2. Baselines and costs

The fixed seed-713 end-to-end profiler performs 1,296 timed requests, including
864 real independent encoder calls. Each of 72 requests is measured three times
in rotated method order. Timing repeats do not increase the task sample size.

| Method | Correct / 72 | Warm wall p50 ms | Warm wall p95 ms |
| --- | ---: | ---: | ---: |
| Ridge | 61 | 6.2409 | 7.9176 |
| Centroid | 60 | 6.2753 | 8.0193 |
| Single adapter | 59 | 6.2984 | 7.7742 |
| Nearest example | 58 | 6.2589 | 8.0031 |
| BM25 | 42 | 0.5082 | 0.8131 |

The separate exact-project workload gets 12/12 with zero encoder calls and a
0.01538 ms median. It is a distinct set of related project/version snapshots,
so its timing is not a paired speedup estimate against the 72 skill requests.

Adapter parameters occupy 86,112 bytes, Adam m/v another 172,224, and its complete
initial compressed checkpoint 250,047. Ridge has 36,960 numerical bytes, versus
369,600 for the actual float64 nearest index. The full training-row file, including
evaluation metadata, occupies 59,692 bytes. The adapter is smaller than that
dense index, but larger than the simpler classifier and even the full authored
source file. Compression of the original evidence is not demonstrated.

The shared base, 470,038 bytes of other model assets/manifest, dedicated runtime,
source files, indexes, optimizer, and every failed candidate checkpoint are
separately accounted. Model loading and feature construction are not free:
encoder load/identity checking was 0.4433 s, encoding 120 training requests 0.5832 s,
initial adapter fitting 0.0638 s, and ridge fitting 0.000984 s. These measurements
come from explicit stages; they are not a whole-system dollar cost.

`evidence/analysis/COST_SCENARIOS.json` gives read-horizon component totals for
100/1,000/10,000/100,000 reads, with omitted lifecycle and infrastructure costs
explicit. Isolated per-method RAM, energy, queuing, ingestion, and general hardware
costs remain unmeasured. Small tail-latency differences do not establish a speed
advantage. The complete-cost positive-task gate is **not passed**.
The warm profiler calls resident models directly. Its latency does not include
`SourceOwner.read` reloading and validating an immutable checkpoint for each read;
the source-owned integration receipts report their own preencoded read costs.

## 3. Cooperation and interventions

The hybrid profile path is current source memory → semantic selector → exact
procedure execution. Its memory component reads a journal; it is not the pure
parametric project cell tested above. The composition path uses fixed sequence,
text, and serialization experts through a learned top-2 router. Public step
decomposition is supplied; the system does not learn an autonomous plan.

| Intervention | Correct / 12 |
| --- | ---: |
| Full profile hybrid | 10 |
| Remove memory | 0 |
| Stale memory | 6 |
| Substitute current exact project KV | 12 |
| Full fixed-expert compositions | 11 |
| Disable sequence / text / serialization expert | 5 / 8 / 5 |
| Substitute nearest-example semantic selection | 12 |

Replacing typed procedure cells with the same generic exact executor preserves
all outputs and execution statuses in both families. The disable results identify
dependencies; they do not prove that learned biological-style specialization is
necessary. Two independently launched cooperation runs produce identical full
semantic traces for all 288 family/arm/case records, after removing only clocks.

## 4. Learned routing and split candidates

The experiment trains a ridge router and invokes only two selected experts per
request. Candidates include fixed semantic grouping, random grouping, balanced
training-feature prototype grouping, and a gradient-conflict split. The last
measures each class's A/B gradient and searches all 5,775 balanced 3×4 partitions
for minimum within-group negative cosine. All proposed groups use training data.

| Structure | Seed 713 | Seed 971 | Seed 1237 |
| --- | ---: | ---: | ---: |
| Continue | 59 | 61 | 61 |
| Widen | 54 | 55 | 55 |
| Fixed groups | 59 | 59 | 59 |
| Prototype-learned groups | 57 | 60 | 58 |
| Gradient-conflict groups | 52 | 56 | 56 |
| Random groups | 54 | 52 | 50 |

Wide and the combined three children each have 23,052 body/head parameters.
The sparse systems additionally pay 1,155 router parameters: total 24,207.
Every continuing/growing arm gets 7,200 additional sample presentations. This
matches parameter capacity and exposure, not FLOPs, optimizer allocation, or cost.

Selection is durably recorded on calibration before any held scoring. It chooses
single/single/random. For seed 1237, random scores 41/48 on calibration versus
single's 39/48, but falls to 50/72 held versus single's 61/72. Selection is only
within the parametric family; it excludes the centroid control, which scored
42/48 calibration in all seeds. It is not a globally optimal memory policy.

Post-run oracle routing diagnostics use the true class to pick an expert. For
gradient grouping this yields 69/69/68 correct, versus achieved 52/56/56. These
are unavailable-information diagnostics, not deployable results or additional
acceptance successes. True expert top-2 coverage is 68/67/70; cross-expert scoring
and routing remain material sources of loss. Gradient separation is a candidate
heuristic, not a sufficient split rule.

## 5. Training-state and runtime migration

`migration.py` exports actual frozen train features, source/base identities,
parameters, every Adam moment, step, RNG, sampler permutation/cursor, and code
dependencies. A 35-step prefix is resumed for 55 steps and compared to a separately
trained uninterrupted 90-step reference; both then undergo seven further steps.

The local three-process run passes full state and future-training checks. A
negative control changes one Adam moment and reseals the NPZ file hash. Current
predictions remain identical, while complete state and future continuation fail.
Three local processes are not three network nodes.

The GitHub workflow uses three independent Ubuntu VM jobs: prepare, resume, and
verify. The second VM receives no uninterrupted reference weights. It also
reconstructs the exact shared pretrained backend from official pinned files,
encodes the actual training texts, and verifies prediction/state continuity.
Only embedding reproduction permits declared `rtol=1e-6, atol=1e-7`; adapter,
Adam, RNG, sampler, and future training comparisons remain bit exact.

The first actual three-VM run, [41205095256](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41205095256),
failed exact state equality despite identical class predictions. The maximum
90-step parameter difference was `3.3306690738754696e-16`. This failure remains
part of the evidence. Its receipts do not establish the exact CPU/kernel cause.

The second run, [41206138368](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41206138368),
passed all thirteen original strict checks. The workflow now disables NumPy
dispatch above the wheel baseline and independently records actual float64
kernels, NumPy/OpenBLAS binary identities, flags, Python/libc, code, and run
identity on every VM. Profiles must match before the unchanged state verifier
runs. The seven original scientific source/dependency files and all acceptance
thresholds are unchanged. Prepare/verify ran on AMD EPYC 9V74 and resume on AMD
EPYC 7763, with three distinct boot IDs. An independent downloaded-NPZ audit
confirmed raw-byte equality of every parameter, Adam moment, sampler array,
and metadata field at both 90 and 97 updates. This qualifies the recorded profile;
it does not promise exact continuation on arbitrary hardware or runtimes.

The successful run transferred at least 94,852,964 bytes of known CI payload,
including the 90,873,127-byte cold backend download. Runtime restoration took
4.637609 s, excluding interpreter/import and pip; three job wall times totalled
68 s, with 89 s from run start to the last job completion. Package downloads,
checkout, actions, logs, and wire overhead are additional. No network economic
advantage has been demonstrated. The first failed run's costs are retained
separately rather than hidden or pooled into a success-only estimate.

See `MIGRATION_RESULTS.md`, `evidence/migration-ci/SUMMARY.json`, and both run
directories for boot identities, original ZIPs, full checkpoints, logs, independent
audits, and network/dependency restoration accounting.

## Evidence and reproduction

- `evidence/INVENTORY.json`: byte lengths and SHA-256 identities for the complete
  checked-in qualification package, excluding the inventory itself. Original CI
  logs and API payloads preserve their downloaded whitespace and byte identities.
- `evidence/publication/`: verified Git tree equivalence and checkpoint blob
  identities for the source/evidence publication history.
- `evidence/inputs/`: source freeze, actual embeddings, original train/cal/test rows.
- `evidence/run/`: every selected and rejected model, source/optimizer state,
  per-query outputs, selection receipts, chronological updates, and latency ledger.
- `evidence/cooperation/` and `evidence/cooperation-repeat/`: complete intervention traces.
- `evidence/provenance/`: immutable learned releases, source database, rejected candidates.
- `evidence/migration-local/` and `evidence/migration-ci/`: continuation and negative controls.
- `evidence/analysis/`, `evidence/AUDIT_COST.md`, `evidence/AUDIT_METHOD.md`: post-run analysis
  and independent critiques; none was used to retune the frozen models.
- `evidence/checks/`: 24 scoped tests, numerical gradient checks elsewhere in
  `evidence/backend/`, and raw profiler logs. The repository formatter reports no
  owned changed files for these qualification Python files; no Ruff coverage is implied.

Install `requirements-runtime.txt` into an isolated Python 3.12 environment and
set `PYTHONDONTWRITEBYTECODE=1`, `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`,
`MKL_NUM_THREADS=1`, and `OPENBLAS_CORETYPE=NEHALEM` on compatible x86 workers.
Use fresh output directories; the experiment refuses to overwrite its inputs/results.
For bit-exact cross-VM continuation, use the complete pinned numerical environment
and capture/compare steps in `.github/workflows/memory-cell-v13-research.yml`;
setting the BLAS core alone was insufficient in the first observed CI run.

```bash
python download_model.py /tmp/v13-base
python prepare_inputs.py --model-dir /tmp/v13-base --output /tmp/v13-inputs
python experiment.py --inputs /tmp/v13-inputs --output /tmp/v13-run
python latency_cost.py --model-dir /tmp/v13-base --inputs /tmp/v13-inputs --results /tmp/v13-run
python cooperation.py --model-dir /tmp/v13-base --inputs /tmp/v13-inputs --results /tmp/v13-run --output /tmp/v13-cooperation
python provenance_run.py --inputs /tmp/v13-inputs --output /tmp/v13-provenance
```

Future changes should first resolve the observed limitations: retention and valid
fallback after rejected updates, calibration that represents future use, selection
over strong nonparametric alternatives, and route/score calibration. A new isolated
held set is needed for any claimed improvement after inspecting these failures.
