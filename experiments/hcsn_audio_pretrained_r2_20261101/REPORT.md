# Frozen official speech frontend: historical audio gate passes

The prospectively frozen speech candidate classifies **69/72 clips (95.8333%)** on the original six-actor development panel, passing its predeclared 90% audio gate. Actor-crossfit train accuracy was **275/288 (95.4861%)**. All seven fixed C=1 head fits succeeded. This closes the audio threshold for this historical panel; it does not close video, independent-population, live decoding or multimodal adoption requirements.

| Frozen comparison | Accuracy | Brier |
| --- | ---: | ---: |
| Anew + unchanged R1T, clean AT | 80.0926% | 0.1423606735 |
| Anew + unchanged R1V/T, AVT | 80.0926% | 0.1431074714 |
| AVT minus AT | 0.0000 percentage points | +0.0007467979 |

The actor-block 95% accuracy interval is [0, 0] percentage points; the Brier-difference interval is [-0.0004417894, +0.0019035014]. The 288 relation episodes therefore provide no accuracy increment from fixed R1 video. The separate Anew + Vpretrained + R1T result is recorded in `../hcsn_joint_pretrained_av_r2_20261101/REPORT.md`; it does not replace the original V-only attribution.

## Implementation and frozen sequence

Official TorchAudio 2.6.0 CPU WAV2VEC2_ASR_BASE_960H remains in evaluation mode with all 94,393,245 parameters frozen. The exact native PCM one-second presentation crop precedes 16 kHz resampling. Only this crop enters the encoder. The fixed 1652-dimensional hidden/CTC descriptor, four 18-fit/6-held actor folds, fit-only normalization and C=1 logistic objective were declared before target fitting. DFA/IOM sentence labels were independently checked; inherited emotion labels are never the target.

Source/protocol publication: `6c3eabfcab18dd9feda400a7b470f4c646230084`. All-head publication: `21663ea761d1f8deefc99f3a3872c1984527df46`. Both preceded development extraction. Source, model, manifest, cache, OOF and head identities remain unchanged. Exact 72-clip validation filtering rejects extra or missing clips. The final preflight passed 14/14 checks, including official forward equivalence, future-PCM isolation, crop-before-resample and prefix stability. Initial preflight sources and the failed output-collision run are retained in `PREFLIGHT_HISTORY.json`; no development-based repair or selection occurred.

## Independent review and scope

`INDEPENDENT_REVIEW_REFERENCES.json` binds independent audits that recompute all seven fits' normalization/predictions, binary targets, 1152 training mappings, unchanged R1 modalities, final frozen-head outputs and actor bootstrap. OOF sigmoid differences were at most 1.11e-16. The cross-lane audit confirms identical new-audio and clean-AT probabilities in the joint component.

The six actors were historically exposed development, not fresh population confirmation. The official checkpoint's LibriSpeech pretraining, MIT weight notice and upstream identity are documented in `README.md` and `CHECKPOINT.json`; arbitrary actor exclusion and pretraining cost are unknown. Offline FLV decoding does not establish live packet availability. There is no analytical-core attribution, GPU/energy result, production activation or all-blockers-closed claim.

## Measured cost and reproduction

Eight outer receipts, including the failed preflight invocation, sum to **161.391499 CPU seconds**. Train extraction used 107.396369, all seven head fits with startup 2.514809, validation extraction 34.236987, and frozen-head evaluation 3.016065 CPU seconds. The remaining measured acquisition/preflight costs are itemized in `COST_LEDGER.json`. The 180.960325-second sum of invocation walls is not a concurrent campaign elapsed time or steady inference latency. Nested body/fit timers are already contained. Unmetered installation, source preparation/freezing/finalization, shared raw acquisition and upstream training costs remain unknown. GPU and joules remain null.

`README.md` supplies portable extraction with an explicit sibling checkpoint override; the external 377,664,473-byte model is not redistributed in this component. Cached features suffice for fixed-head reproduction. Keep the original outputs and use fresh paths for new extraction. `results/run001/VALIDATION_OUTPUTS.npz` retains per-clip and per-episode probabilities, targets, actors and weights; `ARTIFACT_MANIFEST.json` binds all retained component artifacts.
