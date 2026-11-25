# Actual SmallHCSN v2: completed matched-budget study

## What was completed

All **168 formal training arms completed 96 updates**, and all 168 frozen candidates were evaluated once on the new independent test split. There were no formal training failures, budget-censored arms, or evaluation failures. The four censored N64 pilot runs remain in the evidence.

The strongest supported improvement is **training-only feature standardization before the analytic readout**. Across 72 distinct initial feature conditions, using the same ridge coefficient increased held-out accuracy by a mean **20.226 percentage points**. Subsequent backpropagation did not provide a stable average test gain. Learning recurrent connection values also did not provide a stable average advantage.

This is a new synthetic study of the actual SmallHCSN probability/content model. It supplies real execution evidence for a local analytic readout and a bounded comparison of feature/message choices. It does not establish reconstruction of all LLM weights, universal avoidance of backpropagation, real cross-user benefit, learned graph topology, or production adoption.

See [DESIGN.md](DESIGN.md) for the diagnostic reasoning, mathematical penalty convention, precise ablations, and data boundary. Full measurements are in [FINAL_SUMMARY.json](FINAL_SUMMARY.json), [ANALYSIS.json](ANALYSIS.json), and the [independent test result](results/formal_v2_test/RESULT.json).

## Frozen identities and label ordering

| Item | Identity |
| --- | --- |
| Physical runtime capsule | SHA256 `7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96` |
| Source and formal v2 protocol Git anchor | `221c4fb6a6ece0fba3d0052a66c9beeca7d1dcd3` |
| Executed protocol | [FORMAL_PROTOCOL_v2.json](FORMAL_PROTOCOL_v2.json), SHA256 `aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8` |
| Complete candidate seal Git anchor | `7dfd1deb8b70867a7875ef1fc99cd1a6b20f4953` |
| Candidate seal | [GLOBAL_CANDIDATE_SEAL.json](GLOBAL_CANDIDATE_SEAL.json), SHA256 `a447b724f6459625b0e9c5e15e9dca5bbaad439af5c433391c7b34e9a9df88ee` |
| Seal timestamp on execution host | 2026-11-25 11:09:28.889801 UTC |
| Test generation allowed after | 2026-11-25 11:11:20.645206 UTC |
| Test result SHA256 | `5cc51ea9d99f061214822429131d97662f8295c250055e266c3d55c8d978b0a8` |

The initial single-worker FORMAL_PROTOCOL.json is retained as a superseded design. Its Git anchor is `d1461abdf87fe8f5059670c7a99fac552fac58d8`; it was never used for formal training or test. The executed four-worker revision is explicitly named **FORMAL_PROTOCOL_v2.json** throughout the launch receipts.

The source/protocol anchor was published before training. After all 168 training slots terminated, the evaluator verified every candidate and selection history and created the global seal. The orchestrator independently published and read back the candidate Git anchor before launching the test process. [OPEN_RECEIPT.json](results/formal_v2_test/OPEN_RECEIPT.json) records all 168 preflighted candidates. Test labels were never used to tune or select the weights in this study.

This ordering is a code/process and evidence boundary. It does not protect against a hostile administrator with control over the runtime.

## The comparison that repaired the low-score interpretation

The previous N16/N64 chance-level results could not identify an absent physical signal because the readout objective strongly penalized small-scale feature directions. In a new train/dev-only diagnosis using the same old parent weights, the raw-to-standardized comparison at a fixed coefficient changed value/risk dev accuracy from 43.750% to 73.438% at N16, and from 42.188% to 64.063% at N64. Those observations did not reuse the old test data.

The formal study initialized every parent afresh. It used a single globally selected ridge coefficient, 1e-6, for both feature banks and every arm. The following table shows the full-message, learned-recurrent condition, averaged over its three initialization seeds. The analytic heads use exactly the same initial features; the selected model is chosen using dev cross entropy.

| Width | Bank | Raw, old-equivalent coefficient .02 | Raw, common coefficient 1e-6 | Standardized analytic head | Dev-selected candidate |
| --- | --- | ---: | ---: | ---: | ---: |
| 8 | value/risk | 53.125% | 57.292% | 79.167% | 79.948% |
| 8 | tanh | 53.125% | 57.552% | 83.073% | 82.292% |
| 16 | value/risk | 53.125% | 61.198% | 88.802% | 88.281% |
| 16 | tanh | 53.125% | 62.760% | 88.281% | 89.844% |
| 32 | value/risk | 53.125% | 72.396% | 89.323% | 90.104% |
| 32 | tanh | 53.125% | 69.792% | 85.156% | 82.292% |
| 64 | value/risk | 53.125% | 78.385% | 85.417% | 85.417% |
| 64 | tanh | 53.125% | 76.042% | 76.562% | 76.562% |

The .02 convention follows the documented conversion from the old objective's X-transpose-X/(2n) convention. The raw and scaled comparisons in this study both use centering and an unpenalized bias; they are not a byte-for-byte rerun of the previous readout implementation.

**The same numerical ridge coefficient does not mean the same function-space regularization.** Let the centered original features be U, and let D contain the train-fitted feature standard deviations with the registered floor. Fitting V to U D^-1 with penalty lambda times the squared norm of V is equivalent, under W = D^-1 V, to fitting U W with penalty lambda times the squared norm of D W. The raw arm instead penalizes the squared norm of W. Standardization therefore changes the penalty metric in the original physical coordinates. Mapping the centered fit back to raw inputs also changes its affine intercept through the fitted W, although both arms use the same centering convention and an unpenalized bias.

The observed gain combines feature-coordinate scaling and this regularization change. It is not evidence for a gain caused purely by floating-point numerical stability. A control preserving the original penalty would use the squared norm of D^-1 V in normalized coordinates; this study did not register that additional control.

Across the 72 distinct initial feature conditions, the same-coefficient scaling gain ranges from **-4.688 to +35.938 percentage points**, with median **+21.094**. The 144-row factorial contains duplicate initial baselines for learned/fixed recurrent flags; the 72-condition analysis counts each initial representation once.

These results support a substantial scaling/regularization contribution to the low-score problem. They do not establish that scaling explains every deficit or makes every width equally effective.

## Feature banks, messages, and connection learning

The factorial has 4 widths × 3 initialization seeds × 2 feature banks × 3 message modes × 2 recurrent training flags = **144 arms**. Every arm uses the same dense physical backend, float64 precision, fresh initialization mechanism, 64 training examples, 64 dev examples, batch size 8, and a maximum of 96 updates within a 90 CPU-second / 240 wall-second optimization envelope.

The ordinary control substitutes tanh features for value/risk at the readout while retaining equal feature dimension inside the actual SmallHCSN model. Boundary/flow/full describe message-channel ablations; the local QVI boundary law remains active. The recurrent mask stays fixed. Learning connection values does not learn graph topology.

| Paired comparison | Mean accuracy difference | Median | Win / tie / loss |
| --- | ---: | ---: | ---: |
| value/risk minus tanh, 72 pairs | +1.931 pp | +2.344 pp | 46 / 4 / 22 |
| Learned minus fixed recurrent values, 72 pairs | -0.087 pp | -0.391 pp | 29 / 7 / 36 |
| Dev-selected candidate minus initial standardized head, 144 main arms | -0.206 pp | 0 pp | Complete per-arm values retained |

The feature-bank differences range from -15.625 to +14.844 pp. These are descriptive paired measurements on a shared held-out set. They are not 72 independent task replications, and three initialization seeds do not establish a universal feature advantage.

Message marginals average over widths, seeds and recurrent flags:

| Feature bank | Boundary messages | Flow messages | Full messages |
| --- | ---: | ---: | ---: |
| value/risk | 80.078% | 84.896% | 85.514% |
| tanh | 77.865% | 83.496% | 83.333% |

The full-message learned comparison is nonmonotonic in width. Its value/risk test means are 79.948%, 88.281%, 90.104%, and 85.417% for widths 8/16/32/64. The corresponding tanh means are 82.292%, 89.844%, 82.292%, and 76.562%.

All 18 N64 learned-recurrent main arms selected their initial standardized head: their selected physical and recurrent update counts are zero, even though their last-state weights reflect 96 actual BP updates. No BP-updated checkpoint was selected by the dev criterion under this budget. The final and selected weights are both archived.

Across the entire 168-arm study, **47 candidates selected step 0**, and **36 selected step 96**. Completing the budget is not a convergence claim. The preregistered 85% test-accuracy threshold was reached by **68/168 arms**, including **67/144 main arms**. Every quality miss remains published.

The task is sign(A+B), with B arriving later. Its pre-late Bayes accuracy is 75%; a fully informed predictor can reach 100%. The final-decision-trained readout's observed pre-late accuracy in the tabled conditions had three-seed means of approximately 48.4–55.5%. That readout is not optimized to attain the pre-late Bayes bound. The measurements show useful late information and do not prove a globally optimal stopping policy.

## Actual label-budget comparison

The additional 24 arms train nested source-balanced 16- and 32-example subsets at widths 16 and 32, full messages and learned recurrent values. Their 64-example partners come from the main factorial. All labels used by the initial analytic fit are included in these counts. Every arm still receives 96 updates of batch size 8; the number of epochs therefore differs with subset size.

| Width | Bank | 16 distinct labels | 32 distinct labels | 64 distinct labels |
| --- | --- | ---: | ---: | ---: |
| 16 | value/risk | 68.229% | 75.781% | 88.281% |
| 16 | tanh | 65.885% | 73.958% | 89.844% |
| 32 | value/risk | 73.958% | 76.042% | 90.104% |
| 32 | tanh | 71.354% | 69.531% | 82.292% |

These are actual separately fitted candidates, with three seeds per cell. The small-label arms mostly miss the quality threshold. The N32 tanh means are not monotonic between 16 and 32 labels. No general claim of superior sample efficiency follows from this one synthetic task family.

## Parameter and state accounting

All 12 width/seed initialization groups passed exact physical-tensor hash equality across their paired arms. Allocated parameter count varies across widths. Within a width, the feature-bank controls retain equal parameter allocation. Freezing recurrent values intentionally changes the trainable count.

| Width | Allocated parameters | Trainable, recurrent fixed | Trainable, recurrent learned | Active recurrent mask entries | Five state tensors per episode |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 306 | 106 | 298 | 144 | 1,664 B |
| 16 | 994 | 210 | 978 | 576 | 3,328 B |
| 32 | 3,522 | 418 | 3,490 | 2,304 | 6,656 B |
| 64 | 13,186 | 834 | 13,122 | 9,216 | 13,312 B |

Recurrent allocation is 3N², with the fixed mask admitting three quarters of those entries. Actual changed elements are recorded separately for selected and last weights. The state total covers density, boundary, drift, cost, and message tensors; it excludes step/config metadata, optimizer state, and the autograd tape.

Maximum held-out probability-mass error was **2.220446049250313e-14**. Maximum signed-mark excess was **0**. The train-only dense-operator cache check covered 24 width/bank/message cases: state, logits and features matched exactly, and maximum gradient difference was 2.776e-17. The underlying physical source and QVI/reset/remap definitions were unchanged.

## Measured costs

The runtime was Python 3.14.4, NumPy 2.5.5, and Torch 2.15.0+cpu in the existing isolated environment. All four formal workers were independent single-threaded processes. They each requested one CPU quota and a 2 GiB memory cap. They shared pocket4, which reported 24 logical CPUs; external host contention can affect wall measurements.

| Scope | Measurement |
| --- | ---: |
| Formal training, sum of child CPU | 3,587.521 s / 59.792 min |
| Formal training, campaign wall span with up to four workers | 995.179 s / 16.586 min |
| Formal training, sum of case wall times | 3,590.356 s |
| Formal optimization alone, sum of CPU | 2,956.777 s |
| Training feature propagation, sum of wall | 69.278 s |
| Initial dev propagation, sum of wall | 75.873 s |
| Subsequent dev selection propagation, sum of wall | 463.131 s |
| Feature diagnostics, sum of wall | 0.136 s |
| Normalization, all three solves and baseline metrics, sum of wall | 0.264 s |
| Candidate serialization, sum of wall | 0.253 s |
| File deserialization and byte/state verification, sum of wall | 0.457 s |
| Postload state validation, sum of wall | 10.293 s |
| Independent test process, wall / child CPU | 320.040 s / 317.737 s |
| Postprocessing and lossless archiving, wall / child CPU | 8.445 s / 8.233 s |

Mean main-arm total training wall time was 8.000, 12.820, 23.761, and 42.756 seconds at widths 8/16/32/64. These totals include feature extraction, diagnostics, all attempted optimization, selection, serialization and readback. [TRAINING_SUMMARY.json](TRAINING_SUMMARY.json) and [ANALYSIS.json](ANALYSIS.json) retain distributions and individual phase scopes.

The independent test stage includes fresh model construction/loading, both initial and selected feature propagation, baseline metrics and prediction serialization. Per-case test wall totals sum to 316.560 seconds; the 320.040-second supervisor total also includes startup and orchestration.

The analytic heads share one initial feature extraction per arm, and the study always executes the subsequent optimization budget. A tiny marginal solve cost is therefore not a measured standalone end-to-end speedup over BP. No production adoption was performed. The reused dependency installation is documented in the preceding actual_hcsn appendix; its cost is not silently counted as a new zero-cost install.

## Evidence and independent verification

[evidence_archives/ARCHIVE_INDEX.json](evidence_archives/ARCHIVE_INDEX.json) binds **190 lossless tar.xz archives**, totaling **19,180,320 bytes**, with **981 members**. Each member has its original SHA256 and byte count. The largest archive is **228,124 bytes**, below the 512,000-byte repository policy. The archives retain every pilot/formal checkpoint, selected and last weights, histories, predictions, logs, protocols and required source identities.

An independent read-only audit checked all 168 × 4 candidate/RESULT/HISTORY/prediction artifacts, all five scientific source files, the 25 physical source files and their provenance, and the test artifact. A second independent audit checked all archive/member hashes against the retained original files. Neither audit called Torch, regenerated data, or reran the experiment. Their receipts are maintained in the sibling adoption_closure_v2 evidence directory.

The operator start response for the postprocessing job timed out. The original job was later identified read-only from its persisted request and confirmed successful as `1a2126f6973-ffbe-3fa2`, with exit code 0, durable complete output and terminal publication. It was not rerun with a new key.

Use [verify_evidence.py](verify_evidence.py) for a local byte/binding audit without Torch:

```bash
python verify_evidence.py --root . --capsule ../actual_hcsn/runtime_capsule.tar.gz --out BYTE_VERIFY_REPLAY.json
```

This verifies local archive bytes and receipt bindings. Independent Git commit existence/readback is an orchestrator responsibility and is stated separately.

## Numerical replay

Use an environment with the exact Python/NumPy/Torch versions in FORMAL_PROTOCOL_v2.json. Extract the pinned physical capsule into a new directory, set PFT_HCSN_CAPSULE to that absolute directory, and run the frozen source files from this directory. The original isolated interpreter was:

```text
/home/alex/pft-six-actual-hcsn-20261125/venv/bin/python
```

For a complete numerical replay in a new output directory:

```bash
export PFT_HCSN_CAPSULE=/absolute/path/to/extracted/capsule
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export HCSN_V2_REPLAY=/absolute/path/to/new/replay
mkdir -p "$HCSN_V2_REPLAY"
for shard in 0 1 2 3; do
  python runner.py --protocol FORMAL_PROTOCOL_v2.json --out "$HCSN_V2_REPLAY" --shard-index "$shard" --shard-count 4 > "$HCSN_V2_REPLAY/worker-$shard.log" 2>&1 &
done
wait
```

The original worker launcher and test launcher retain exact commands and external anchors in their receipts. A replay seal can be constructed with evaluate.py seal after every assigned slot terminates. New confirmatory work requires a new test descriptor and a newly published candidate seal; the historical test data in this evidence package are now public to repository readers.

The scientific source hashes are immutable for this run. New optimization rules, feature scalers, masks or task generators belong to a separately identified experiment.
