# Actual SmallHCSN integration appendix

## Observed outcome

A new, independently identified study executed the real SmallHCSN probability and signed-content kernels on pocket4 at widths 8, 16, 32 and 64. It fitted a closed-form readout on frozen parent dynamics, compared the value/risk readout features with equal-dimensional ordinary tanh replacements, and resumed the complete physical state in four fresh Python processes.

All eight measurements completed, four cold replays had exactly zero recorded error, and the two feature controls had identical final population states during training feature extraction. Task performance was mixed: N16 and N64 remained near chance, and the analytic feature bank showed no demonstrated advantage over the ordinary feature control. Completion is an integration result, not full-network, learned-circuit, cross-user or production qualification.

The exact measured results are in `results/pocket4_run_v1/RESULT.json`. This appendix is separate from the NumPy proxy experiments and does not replace their results.

## Source and runtime identity

The upstream commit is `88414dda04443897def179754779aecdca6f0296` in `TrillionniumFoundation/hepta-private-ci`, observed on `research/hcsn-pft-fourstep-20261125`.

The actual imported model is `qualification.hcsn_smallnet_20261124.model.SmallHCSN`. The runtime capsule contains the required Python source, archived N8/N32/N64 parent checkpoints, provenance, and study entry point. Its SHA256 is:

`7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96`

The study SHA256 is:

`3007f64b548671f2f372ae9db4f48459d2795a68f0154fbeb1a6579994719678`

The research source differs from the extracted upstream source only by an explicit research-identity comment and adding N16 to the allowed-width tuple in model.py. A top-level qualification/__init__.py prevents accidental namespace imports from a live checkout. All 25 research Python source hashes and the actual imported module paths are checked during the main run and cold replay. Archived parent hashes are checked against the pinned extraction manifest.

This study created its own protocol, source IDs, freeze manifest, output directory and runtime. It never invokes or bypasses the old strict qualification gate and does not inherit its ledger or environment qualification. The local dependency attempt is retained as `results/local_dependency_check/RESULT.json` with BLOCKED_MISSING_DEPENDENCY; the successful run used a new isolated remote venv.

| Component | Observed run |
| --- | --- |
| Host and account | pocket4, alex |
| Dedicated directory | /home/alex/pft-six-actual-hcsn-20261125 |
| Python | 3.14.4 |
| NumPy | 2.5.5 |
| Torch | 2.15.0+cpu |
| Device and Torch threads | CPU, 1 |
| Dependencies | NumPy from PyPI; CPU Torch from the official PyTorch CPU index |
| Prior frozen environment inherited | false |

Full pip reports, their wheel URLs and hashes, installed-package versions, installation logs and remote process receipts are preserved.

## What was actually propagated

Each neuron has six active finite-volume cells, three Erlang refractory phases and one upper account. Probability and signed content occupy separate channels transported by the physical operator. A typical batch state has shape [8, N, 2, 10].

The continuation contract consists of density, boundary, drift, cost and message tensors, the absolute step, and the model configuration. dt is 0.25; controls are refreshed every two steps. The source implements threshold hits, reset/refractory flow and conservative remapping when the local boundary changes. This is a finite-state approximation to the underlying diffusion.

The local QVI boundary solves the source's frozen local reward condition, including its delay model. It is not a solution to the full classification task. The clocked content-write fraction is 0.5 per tick; this study does not certify continuous-time resampling invariance.

The ordinary control changes only the readout value/risk features to tanh(drive) and tanh(raw_mark). It preserves other readout features, message formation and physical dynamics. It is not an independently trained ordinary RNN. The actual physical parent tensors were checked unchanged for all eight candidate files.

## Data and freezing

The task reveals independent A and B, uniform on [-1, 1], at different times and asks for sign(A+B). The delayed B arrives at one of steps 4, 5 or 6. Inputs contain no target or future B. The exact pre-late Bayes accuracy is 75%; after both signals the Bayes accuracy is 100%. Finite sample scores may exceed or fall below the pre-late theoretical value.

The new deterministic task uses seed 731:

| Split | Source IDs | Count |
| --- | --- | ---: |
| Train | 91000, 91001, 91002, 91003 | 64 |
| Dev | 92000, 92001 | 32 |
| Test | 93000, 93001, 93002, 93003 | 96 |

Only train is used by the N16 bootstrap and ridge fit. Dev scores are recorded without model selection. Test source IDs and the generator seed are committed in the protocol; test data and labels are generated only after all eight candidate files have been hashed into GLOBAL_CANDIDATE_FREEZE.json. Every candidate hash is checked before the first test generation and again before evaluation.

Freeze time: 2026-11-25T08:55:26.368877+00:00. First test generation starts after: 2026-11-25T08:55:26.369473+00:00.

This is code-enforced temporal separation in one study process, not an adversarial sandbox or a real cross-user isolation guarantee. All data are synthetic.

## Measured accuracy

Each final score below uses the same 96 held-out episodes. No low-scoring width was omitted.

| Width | Feature dimension | Value/risk pre-late | Value/risk final | Tanh pre-late | Tanh final |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 20 | 77.083% | 93.750% | 77.083% | 93.750% |
| 16 | 40 | 46.875% | 46.875% | 46.875% | 46.875% |
| 32 | 80 | 62.500% | 90.625% | 67.708% | 91.667% |
| 64 | 160 | 50.000% | 46.875% | 48.958% | 46.875% |

The final-minus-pre-late value/risk gains are +16.667, 0, +28.125 and -3.125 percentage points. These descriptive results show useful delayed information on two parents in this small task, not a general learned-circuit advantage.

N8/N32/N64 reuse three archived trained parents. N16 has no archived parent and received 24 new ordinary backpropagation updates, taking 4.052 wall seconds and 4.042 CPU seconds. It was explicitly not qualified as converged. The archived parents' previous training cost is excluded from this run. N64 also uses the uniformized backend; the other widths use dense propagation. Cross-width quality and cost comparisons are not controlled for training budget or backend.

## State integrity and actual parameter counts

Four fresh-process continuations matched uninterrupted evaluation with zero error in all five physical tensors, logits and features. Absolute steps matched. The maximum test probability-mass error was 1.732e-14, signed-content excess over probability was zero, and minimum probability was zero. These are the recorded batches and continuations, not an exhaustive numerical proof.

The post-freeze parameter inventory loaded the actual parent and candidate tensors. Recurrent activity is defined by nonzero entries of the fixed synaptic mask, not by learning graph topology.

| Width | Total allocated parameters | requires_grad parameters | Active masked trainable capacity | Recurrent allocated | Recurrent active | Readout parameters fitted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | 306 | 298 | 250 | 192 | 144 | 42 |
| 16 | 994 | 978 | 786 | 768 | 576 | 82 |
| 32 | 3,522 | 3,490 | 2,722 | 3,072 | 2,304 | 162 |
| 64 | 13,186 | 13,122 | 10,050 | 12,288 | 9,216 | 322 |

requires_grad is a capacity flag. Only the readout was updated when creating each candidate; the N16 parent bootstrap is a separately recorded full-model BP stage.

## Measured cost and limits

Dependency preparation took 297.011 wall seconds, including 20.873 seconds for NumPy installation and 271.671 seconds for CPU Torch. The isolated study subprocess took 18.524 wall seconds and 18.375 child CPU seconds. Its internal study clock recorded 17.344 seconds. Dependency preparation and post-freeze collection are excluded from that study clock and reported separately.

Per-candidate training feature propagation took 0.200–0.499 seconds; the analytic readout solve took 0.251–1.300 milliseconds. Feature propagation dominates these tiny solves. These measurements are not a matched comparison against full-network BP. Archive transfer, previous parent training, energy, production adoption and distributed consensus costs are not silently treated as zero.

The result leaves real cross-user transfer BLOCKED_SYNTHETIC_DATA, learned-circuit superiority NOT_TESTED, and N16 formal qualification NOT_INHERITED_NEW_RESEARCH_EXTENSION. It does not establish PFT inversion of all weights, universal avoidance of backpropagation, useful work validation, or decentralized consensus.

## Reproduction

Use Python 3.14.4 for the recorded environment. Create a fresh isolated venv and install the exact observed versions:

```bash
python3.14 -m venv /tmp/actual-hcsn-replay-venv
/tmp/actual-hcsn-replay-venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple numpy==2.5.5
/tmp/actual-hcsn-replay-venv/bin/python -m pip --isolated install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu
mkdir /tmp/actual-hcsn-replay-capsule
tar -xzf runtime_capsule.tar.gz -C /tmp/actual-hcsn-replay-capsule
/tmp/actual-hcsn-replay-venv/bin/python /tmp/actual-hcsn-replay-capsule/study.py run \
  --out /tmp/actual-hcsn-new-run \
  --widths 8,16,32,64 --data-seed 731 \
  --train-per-source 16 --dev-per-source 16 --test-per-source 24 \
  --bootstrap-steps 24 --bootstrap-cpu-seconds 30
```

The output directory must not already exist. Source and archived parent hashes are checked by study.py. Check runtime_capsule.tar.gz against the SHA above before extraction. A fresh run gets its own measured timings and protocol identity; do not replace the published run.

The full raw candidate and cold-replay files are retained by width in evidence_archives. Their member sizes and SHA256 values are in ARCHIVE_INDEX.json. Every downloaded chunk, complete archive and all 32 archived members were checked locally. The capsule's 30 payload members were independently checked against CAPSULE_MANIFEST.json.

## Publication set

PUBLISH_MANIFEST.json is the finite explicit publication list. The largest file is the 406,079-byte runtime capsule, within the repository's 512,000-byte per-blob limit. The five evidence bundles are 19,535, 32,944, 79,282, 214,849 and 45,566 bytes.

Do not publish the expanded downloaded archives, upstream copies, runtime source tree, parent directory or local bytecode caches a second time. Their required runtime contents are already in the verified capsule, with provenance retained.

## Recovery provenance

The shared local executor became unavailable after all measurements and byte-verification checks completed. Publication recovered the scientific files and archives from the previously captured tool results and the frozen pocket4 files, without rerunning training, evaluation or collection. Their SHA256 values were rechecked against the recorded identities. The 108-byte local missing-dependency result was reconstructed and matched its previously recorded SHA256 exactly. The local receipt wrappers were reconstructed from the original captured tool objects. This README was restored from the previously written text and this recovery note was added; PUBLISH_MANIFEST.json was regenerated to describe the recovered publication bytes. No scientific source, checkpoint, candidate, result or frozen protocol was rewritten.
