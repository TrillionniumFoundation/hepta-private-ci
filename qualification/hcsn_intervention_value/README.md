# When is a paid video view or another audio prefix worth its cost?

This follow-up to [#6985](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6985) uses real, unaltered audiovisual music recordings. Gallery, training, development, retention and final confirmation have disjoint recording and creator identities. The task includes piano and guitar. Segments from one work share a source and cost measurements must count that dependence. The original artist, author attribution, file identity, licence and immutable revision for each recording are in [the roster](media/sources.json).

**确认结果与新录制逐来源对照** · [中文研究报告](RESULTS.md) · [24 个原定查询的数值](evidence/summary.json) · [发布包明细及 SHA-256](evidence/archive_manifest.json)

## Physical decision

At any of six 0.48-second prefixes the controller may return its free audio answer, acquire the current camera view and terminate, or wait until the next prefix. First observed prefix is time zero. The reward for a correct answer is one, the paid view costs 0.30, the flow cost of waiting is 0.40 per second and the discount rate is 0.20. The control can read the current and past free observations. Reference material and precomputed outcomes allow an evaluator to score counterfactual trajectories.

Given calibrated information at a prefix, write the probabilities of a correct free or purchased answer as `p_free` and `p_read`. Immediate purchase improves on immediate free exit if `p_read - p_free > 0.30`. It must also improve on continuing. One WAIT has value `0.908464 × E[next optimal value] − 0.183072` in the current prefix's units. Even a guaranteed hit at the next prefix gives at most 0.725392 after waiting. A current free success probability above that value therefore dominates every one-step continuation. These statements concern conditional expected rewards; raw classifier softmax values need separate calibration.

## Experimental order

1. Freeze the recording roster, price, candidate frontend list and selection procedure. Extract prefix features from the named originals. Keep final source outcomes closed.
2. Fit a common source-balanced clean audio frontend. Predict the TRAIN scores of each creator using a frontend trained without that creator. Evaluate four camera matchers on TRAIN and DEV. The additional perfect-information value of paid video must be at least 0.03 in both populations, and at least two creators in each must benefit. Rank eligible cameras using a deployable DEV policy relative to a separately trained no-read rule and a locked immediate strategy.
3. Freeze the chosen camera, fit all prespecified policy heads and the outer BP controls, then publish the selection seal. The fallback within-instrument reference-retrieval workload is registered separately and runs only if the primary classifier task does not qualify. It has its own frontend and selection seals.
4. Open final source scores once. Evaluate the chosen models, matched no-read training, disabling the same model's READ action, and immediate-only alternatives. Report capability and causal timing separately, including per-source contrasts and actual purchases. Independently replay the conditional readouts, policy choices and returns.

The policy teacher uses a fitted continuation policy and a held-source realized future return. It does not grant an agent the ability to see the correct future answer during inference. Its recursive held-source guarantee is conditional on the fixed feature archive. TRAIN audio features are separately cross-fitted; a fully nested raw-audio/teacher estimator would also need to rebuild every intermediate audio frontend for each inner fold. Separate DEV, RETAIN and TEST productions supply the final generalization checks.

## Entry points

Requires Python, NumPy, SciPy, PyTorch, torchvision, Pillow, FFmpeg and FFprobe. Use the release evidence for the exact tested versions. Pin CPU numerical threads for comparable elapsed times.

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
pkg=qualification/hcsn_intervention_value
python "$pkg/media/verify_media.py"
python -m unittest qualification.hcsn_intervention_value.test_frontend qualification.hcsn_intervention_value.test_independent qualification.hcsn_intervention_value.test_policy qualification.hcsn_intervention_value.test_reference
python -m qualification.hcsn_intervention_value.discovery fit /path/to/raw/features /path/to/semantic /path/to/new/discovery
python -m qualification.hcsn_intervention_value.run fit /path/to/new/discovery /path/to/new/policies
python -m qualification.hcsn_intervention_value.verify_policy /path/to/new/discovery /path/to/new/policies --fit-only
```

The discovery procedure writes a negative decision when no camera passes. To check a positive decision, first verify and preserve the full roster of fitted models, then use those sealed paths for `discovery confirm --policy-seal .../selection_seal.json`, `run confirm` and `verify_policy`. The [data build](media/CORPUS.md), [primary protocol](protocol.json), [policy details](policy_protocol.json) and [conditional fallback](alternate_protocol.json) describe all inputs. The published inputs include derived summaries, output probabilities, per-episode receipts and recording hashes. Original video and sound are obtained from each publisher.

## Reproduce the published confirmation

From this commit's repository root, pass a **new** directory to the unpacker. The second command works offline on the derived features, both decision traces and the measured partial interval.

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m qualification.hcsn_intervention_value.replay qualification/hcsn_intervention_value/evidence /tmp/hepta-commons-confirm
python -m qualification.hcsn_intervention_value.verify_release /tmp/hepta-commons-confirm
python -m qualification.hcsn_intervention_value.verify_front_results /tmp/hepta-commons-confirm/primary/discovery
```

The archives hold all 24 semantic camera trajectories, 22 complete test trajectories and five original audio prefixes of a 23rd query. Reproducing raw decoding requires obtaining the licensed recordings listed in the roster. Archive verification, model decisions, finite-table opportunity enumeration and uncertainty calculations run without network access. Compare parsed JSON for the general interval report, whose object key order can vary between Python processes. The partial-prefix certificate records the new elapsed time on every run. The original budgets, source splits and model selection seals are preserved.
