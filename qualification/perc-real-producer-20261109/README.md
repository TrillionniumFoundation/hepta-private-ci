# PERC real-producer qualification evidence — 2026-11-09

## Decision

**Engineering execution and recomputation PASS. Scientific qualification and
learned-policy adoption remain HOLD.** For this task, where the requested image
rectangle is already public, retain direct-ROI fixed OCR acquisition.

The learned global policy matched the strong fixed baseline's 24/32 terminal
correctness outcomes but used 2.711327 times its online proxy cost. Dense-active
returned 23/32 and cost 2.762103 times the baseline. Active acquisition improved on
a frozen catalog-order schedule, but neither learned policy improved utility over
the direct-ROI baseline. Dense had no positive terminal increment.

The frozen experiment was executed once; no held-out policy tuning or retry was
performed. It completed all 224 task executions with no collector failure. The
observed negative adoption result is preserved. See [GATE_DECISION.json](GATE_DECISION.json)
and the complete [PILOT_REPORT.json](PILOT_REPORT.json).

## Exact scope and identity

| Item | Executed configuration |
| --- | --- |
| Frozen source | `5ab776748e5c31dc2dd59189fab6183a88fc418a` |
| Integrated Cell base | `81da60b349e32d89d0e4c4674a517a66af7e5eee` |
| Real source | Official FUNSD scanned forms; 64 train, 16 dev, 32 original-test documents |
| Grouping | Original-document SHA; no exact capture content crossing splits |
| Task | Exact transcription of one explicitly located word after controlled initial downsampling |
| Backbone | Actual frozen torchvision MobileNetV3-small features, official pinned checkpoint |
| Learned projection | Eight-dimensional PCA, fit only on 64 training initial captures / 256 crop vectors |
| Representations | Global mean crop features before projection; dense four spatially located vectors |
| Acquisition | Separate deterministic global/dense ridge gain-and-cost heads from actual paired continuations |
| Terminal decoder | Frozen Tesseract OCR; latent affects acquisition, not semantic text decoding |
| Budget | Uniform 4,000,000 microcredit cap; 2,000,000 read reservation; at most one extra observation |
| Controls | Initial OCR, public-coordinate direct ROI, same-cap random extra read |
| Held-out execution | Per-document public-ID-seeded shuffled condition order; 32 × 7 = 224 |
| Runtime | CPU, Python 3.12.14, Torch 2.15.0+cpu, torchvision 0.29.2+cpu, NumPy 2.3.5, Pillow 13.0.0 |
| OCR identity | Tesseract 5.5.0; executable, English traineddata, TSV config and full invocation pinned |

The original FUNSD archive SHA-256 is
`c31735649e4f441bcbb4fd0f379574f7520b42286e80b01d80b445649d54761f`.
The checkpoint SHA-256 is
`047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`.
The prepared dataset identity is
`ad7e07138cefdb16e33a819f8aebef4402572acc22c51cefce0df19a9c54502b`.
The frozen execution-pins identity is
`1b8b90fc58bea0b31afdd6dbdb3ff0003ec4888ec89ab474b1687d27795b36c4`.

Exact source hashes and the actual launch are in [EXECUTION_SOURCE.json](EXECUTION_SOURCE.json).
Model, preprocessing, solver and OCR pins are in [EXECUTION_PINS.json](EXECUTION_PINS.json).
[MANIFEST.json](MANIFEST.json) retains one training campaign receipt and unchanged
formal prerequisites. The source stayed unchanged during the complete pilot.

## Terminal results and cost

The cost unit combines one microcredit per measured microsecond and one per
serialized communication byte. **It is not dollars, energy or pure latency.**
The frozen rule is `utility = exact_success - 0.0000005 * proxy_cost`.

| Condition | Correct | Success / field fidelity | Mean online cost, millions | Online utility | Utility after setup, N=32 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Global + fixed catalog | 8/32 | 25.000% | 0.485783 | 0.007108 | -0.164097 |
| Dense + fixed catalog | 8/32 | 25.000% | 0.494112 | 0.002944 | -0.168262 |
| Global + active | 24/32 | 75.000% | 0.484135 | 0.507933 | -0.553603 |
| Dense + active | 23/32 | 71.875% | 0.493202 | 0.472149 | -0.663386 |
| Initial OCR only | 0/32 | 0.000% | 0.187182 | -0.093591 | -0.095424 |
| Direct requested ROI, OCR only | 24/32 | 75.000% | 0.178560 | 0.660720 | 0.658887 |
| Random extra read, global | 14/32 | 43.750% | 0.472847 | 0.201077 | 0.029871 |

Field fidelity is equality of the same `selected_word` string, so it is not an
independent second success metric. Case, digits, punctuation and internal text
are scored exactly; OCR is retained as an unverified transcription, not truth.

Global-active and direct-ROI agree on all 32 correctness outcomes: 24 both right,
8 both wrong. Global-active always takes two observations; direct ROI takes one
and executes no encoder. Dense-active has one early STOP, losing one additional
case. The direct-ROI control can exploit the public rectangle without learning.

Exploratory source-paired 95% bootstrap intervals, conditional on this one fitted
campaign and without multiple-comparison correction:

| Contrast | Estimate | 95% interval |
| --- | ---: | --- |
| Active main effect, success | +48.4375 percentage points | [+29.6875, +65.625] |
| Dense main effect, success | −1.5625 percentage points | [−4.6875, 0] |
| Dense × active interaction, success | −3.125 percentage points | [−9.375, 0] |
| Global-active minus direct-ROI, online utility | −0.152787391 | [−0.164876516, −0.139805672] |
| Dense-active minus direct-ROI, online utility | −0.188570703 | [−0.248944266, −0.153018875] |

The observed zero accuracy difference between global-active and direct ROI is
not a population-equivalence proof. These data do not isolate a causal benefit
of the latent channel from the public geometry available to the policy.

### One-time costs and amortization

The report charges each alternative deployment its own required components:
neural fixed/random uses projection, model load and collector startup; active
also uses its representation's train/dev collection, labels and head fit;
OCR-only controls use OCR initialization and pay no unused neural setup.

| Policy | One-time proxy cost | Utility, N=1 | Utility, N=32 | Utility, N=1,000 |
| --- | ---: | ---: | ---: | ---: |
| Global-active | 67,938,269 | −33.461202 | −0.553603 | 0.473963 |
| Dense-active | 72,674,250 | −35.864976 | −0.663386 | 0.435812 |
| Direct ROI | 117,295 | 0.602072 | 0.658887 | 0.660661 |

Even infinite amortization does not reverse this comparison under the frozen
proxy: active already has lower online utility. Controlled collection dominates
head fitting: global collection costs 56,944,786 versus head fitting 31,479;
dense collection costs 61,655,482 versus fitting 54,249.

The actual seven-condition campaign cost is 221,553,492 proxy units including
measured training, initialization, finalization and evaluation once. The internal
report wall time is 207.035212051 seconds; the complete launched process took
209.531251463 seconds. Dataset preparation lies outside this campaign meter.
Provider billing, energy and the real future reuse horizon remain unknown.

## What is now supported by real execution

| Evidence | Result | Record |
| --- | --- | --- |
| Original-image reconstruction | 336/336 registered captures from 112 original scans match byte for byte | [SOURCE_AUDIT.json](SOURCE_AUDIT.json) |
| Final collector | 863 observations: 480 train/dev and 383 held-out; no failure | [ARTIFACT_INVENTORY.json](ARTIFACT_INVENTORY.json) |
| Actually observed capture IDs | 329/336, across all 112 document groups | Full private collector index |
| Actual neural observations | 799: global 432, dense 367; 64 other observations are OCR-only | [NATIVE_BATCH.json](NATIVE_BATCH.json) |
| Native interoperability | 799/799 decode/validate/encode passes with exact wire round trips | [NATIVE_BATCH.json](NATIVE_BATCH.json) |
| Fresh-process recomputation | 649 actual model calls cover all 799 neural receipts; 0 mismatches | [RECOMPUTATION.json](RECOMPUTATION.json) |
| Input uniqueness | 652 source/representation pairs map to 649 unique pixel/region/representation keys | [RECOMPUTATION.json](RECOMPUTATION.json) |
| Main-arm structural traces | 128 validated; additional 96 comparator executions | [PILOT_REPORT.json](PILOT_REPORT.json) |
| Python validation | 60 distinct passing tests across recorded component/follow-up/integration phases | [TEST_SUMMARY.json](TEST_SUMMARY.json) |
| Repository formatting | Required `just fmt` passed; tested Python ASTs preserved | [FORMAT.json](FORMAT.json) |

Native validation compiled 23 unchanged Rust source files from the repository.
Every observation has four evidence regions; global has 8 latent scalars and
dense 32. Maximum observed native wire size is 25,543 bytes and evidence RGB
size is 5,406 bytes, within the existing 65,536 / 8,192 limits.

Recomputation compares actual crop RGB, normalized tensors, backbone float
features and every Q24 latent value using the exact checkpoint/projection and
runtime. It is separate from independent hardware attestation or proof of past
execution time, bills or energy. It does not rerun OCR or head training. The
64 projection-training feature executions were also linked read-only to the
already-recomputed retained input values.

The historical 190 native tests are not represented as rerun here. The isolated
native probe checks observation contracts, not full Cell daemon admission or
capture/budget ownership. Earlier real-capture examples use a different TRAIN-only
development projection and are separately labeled in [NATIVE_REAL_CAPTURE.json](NATIVE_REAL_CAPTURE.json).

## Gate and scope limits

The unchanged complete protocol rejects this campaign with
`at least two distinct training seed receipts required`. Changing a seed for this
deterministic PCA/ridge pipeline does not create independent training repeats.
This is one controlled explicit-rectangle word-transcription panel, not the
complete four-family PERC confirmation matrix. Template, organization and live
operator independence remain unverified. There are no preregistered confirmatory
thresholds or complete commercial cost observations.

The frozen encoder plus PCA is a learned compression candidate. This experiment
shows actual inference and task-level acquisition effects against a weak schedule;
it does not establish a new encoder's marginal task benefit or a learned semantic
decoder. Production source/budget owners are not connected. Existing defaults
remain unchanged and no main-branch merge or production rollout occurred.

## Development history and portability

- An initial dataset preparation was rejected because exact distractor pixels
  crossed splits; the final panel rejects such content overlap.
- A first test invocation omitted the checkpoint environment binding and skipped
  five producer checks. The recorded final component phase ran 50 tests with zero
  skips; follow-up phases ran 10 acquisition, 3 actor and 6 report tests with zero
  skips. Nine acquisition tests overlap the initial phase, giving 60 distinct tests.
- A temporary early 1M-reservation smoke exceeded its quote. Its raw receipt was
  cleaned with the temporary directory; only the session error survives. No lost
  receipt was reconstructed. The uniform 2M reservation / 4M cap was fixed using
  development observations before held-out execution. Durable later TRAIN smoke
  evidence is retained. See [PREFLIGHT_HISTORY.json](PREFLIGHT_HISTORY.json) and
  [DEVELOPMENT_NOTES.json](DEVELOPMENT_NOTES.json).
- After the successful frozen replay, a small portability fix removed numeric
  PID equality as a rejection gate. PIDs can repeat across time or namespaces;
  separate CLI invocation remains a caller obligation. All value checks remain
  unchanged. The actual experiment/replay source stays pinned to `5ab7767`;
  the post-run fix is separately identified in [REPLAY_PORTABILITY_FIX.json](REPLAY_PORTABILITY_FIX.json).

Cloud readiness remained UNKNOWN after controller read timeouts and an admitted
capacity error. No cloud allocation or GPU execution was requested. The bounded
experiment completed on local CPU. See [COMPUTE_READINESS.json](COMPUTE_READINESS.json).

## Reproduce

Use the exact frozen source and runtime versions. The private evidence archive
contains the original inputs, model artifacts, all receipts and verification
outputs; repository-backed source code remains in GitHub. Choose fresh output
paths, because commands preserve earlier attempts.

```bash
PYTHONPATH=scripts python -m perc1.document_data \
  --dataset-root "$PERC_ORIGINAL_DATA_DIR" --output "$PERC_PANEL_DIR" \
  --train 64 --dev 16 --test 32

PYTHONPATH=scripts python -m perc1.document_pilot \
  --dataset-dir "$PERC_PANEL_DIR" \
  --weights "$PERC_WEIGHTS" \
  --weights-sha256 047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f \
  --output "$PERC_NEW_PILOT_DIR"

PYTHONPATH=scripts python scripts/perc1_recompute.py \
  --dataset "$PERC_PANEL_DIR/dataset.json" \
  --weights "$PERC_WEIGHTS" \
  --projection "$PERC_RETAINED_PILOT_DIR/projection.json" \
  --execution-pins "$PERC_RETAINED_PILOT_DIR/EXECUTION_PINS.json" \
  --collector-root "$PERC_RETAINED_PILOT_DIR/collector" \
  --output "$PERC_NEW_REPLAY_DIR" --device cpu

PYTHONPATH=scripts python scripts/perc1_native_batch.py \
  --dataset "$PERC_PANEL_DIR/dataset.json" \
  --projection "$PERC_RETAINED_PILOT_DIR/projection.json" \
  --execution-pins "$PERC_RETAINED_PILOT_DIR/EXECUTION_PINS.json" \
  --collector-root "$PERC_RETAINED_PILOT_DIR/collector" \
  --probe "$PERC_NATIVE_PROBE" --build-record "$PERC_NATIVE_BUILD_RECORD" \
  --output "$PERC_NEW_NATIVE_DIR"
```

Rebuild a compatible probe with `scripts/perc1_native_probe.py --repo ... --build-dir ...`.
The actual build used Rust 1.96.0 and the retained dependency lock. A repeated full
pilot has new measured timing labels and must be reported as a new campaign;
it must not overwrite or relabel these results.

## Reviewable source series and hosted CI

| Stage | PR | Scope |
| --- | --- | --- |
| 1 | [#5484](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5484) | PERC 1/3: export actual RGB crops through the bounded native wire |
| 2 | [#5485](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5485) | PERC 2/3: run pinned pretrained inference and retain recomputable provenance |
| 3 | [#5486](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5486) | PERC 3/3: learn advisory acquisition value from controlled terminal pairs |
| 4 | [#5494](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5494) | freeze real-document panel and comparator accounting |
| 5 | [#5510](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5510) | audit original captures and unchanged native readback |
| 6 | [#5513](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5513) | recompute neural outputs from pinned image and model artifacts |
| 7 | [#5526](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5526) | collect real OCR and neural receipts with settled persistence costs |
| 8 | [#5527](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5527) | execute bounded four-arm acquisition and honest OCR controls |
| 9 | [#5528](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5528) | evaluate terminal outcomes with source checks and explicit full-cost horizons |
| 10 | [#5529](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5529) | freeze and run the real-document training and held-out pilot |
| 11 | [#5536](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5536) | avoid false replay rejection from reused or namespaced PIDs |

This directory is the evidence companion. [HOSTED_CI.json](HOSTED_CI.json) records
workflow states for exact source heads at the stated observation time. Hosted
checks were still queued/running; no complete hosted-green gate is claimed.
All PRs remain draft and unmerged.

## Complete private evidence

Archive: `perc-real-producer-20261109-evidence.zip`.
SHA-256: `298af86ccf9005fe3d78727ecf30d807904eeb3cfa31af318ef6de5a08142b52`.
Size: 45364253 bytes; 8161 files, CRC verified.

The archive was supplied privately with this work. It includes source image and
OCR payloads, evaluator targets, trained private projection/heads, complete
collector/native/recompute artifacts and a file-level hash manifest. Those raw
payloads are not redistributed in this public repository. FUNSD's noncommercial
research terms remain applicable. Public motivation/source links are in
[PROTOCOL.md](PROTOCOL.md); neither cited paper is evidence of this pilot's efficacy.
