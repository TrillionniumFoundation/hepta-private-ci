# AV prefix-refinement oracle diagnostic — research only

## Negative result

On eight already-used TRAIN recordings from four actor groups, every exact
forward-call budget from 0 through 6 has **zero dynamic-selection headroom**:
the truth-looking per-recording oracle and the best fixed audio/video prefix
choose the same action. Stop complex-router development on this material.

Video refinement reduces reconstruction error, but its oracle always chooses
round 3, adding no value over fixed round 3. Audio round 2 worsens seven of eight
recordings. Under an *at-most* six-call cap, aggregate joint MSE headroom is only
1.33497787e-6, approximately 0.0128%, while oracle calls average 4.75 versus 6.
Those selected-prefix costs are clairvoyant lower bounds, not measured runtime
savings: the diagnostic actually evaluates all 48 forwards first.

The joint diagnostic averages raw audio and video MSE; it is not a perceptual
metric and video's larger error scale dominates it. Per-modality aggregate
results are retained. Matrix MACs exclude feature creation, nonlinearities,
scoring, control, decoding and I/O. Equal calls are not generally equal physical
cost. Both oracle and best-fixed selection use TRAIN truth, not a heldout set.

This does not overturn v5 seed-29/tail-loss regressions, its zero-REFINE finding,
the original support thresholds, the cold-solver gate, or any production gate.
The pilot's learned signal transforms are not v5's arithmetic REFINE action.
Zero REFINE may be rational when a task's marginal gain cannot pay for its cost;
forcing a positive action rate would not demonstrate scientific contribution.

## Data-free checks

From this directory:

```sh
python -m unittest -v test_oracle
python -m compileall -q oracle.py replay_private.py test_oracle.py
```

The **six stdlib-only tests** cover oracle bounds, a heterogeneous counterexample,
paid prefix dependencies, exact versus capped cost, invalid numerical inputs,
and aggregate-only/nonmutating output. Their artificial scalar losses test
algebra, not neural quality. They require no dataset, model, FFmpeg, download,
credential or network. These are not the private signal-replay tests.

## Optional private replay and what is not distributed

`AGGREGATE_RESULT.json` is a reported development observation, not a self-contained
data artifact. **This package does not contain media, reconstruction arrays,
per-recording score tables, identities, trained weights, or a derived database.**
The original private replay verified 64 recorded stage losses within 1e-15 and
16 final float32 signal arrays byte-exactly, with one frozen training seed. This
portable replay additionally reproduced all 14 original aggregate budget rows.

To repeat that replay, obtain the original frozen pilot bundle from its research
custodian through an authorized private transfer. `SOURCE_LOCK.json` lists the
required metadata/source/protocol/weight file digests. The bundle also needs the
eight decoded-array and final-reconstruction archives referenced by its pinned
receipts. Raw dataset access alone does **not** provide these trained weights or
receipts; hashes alone cannot reconstruct them. If that private bundle is not
available, only the data-free checks are reproducible from this repository.
Do not create a replacement bundle and describe it as exact reproduction.

With NumPy already available and the hash-matching bundle held locally:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python replay_private.py --bundle /path/to/private-bundle
```

This reads only local pinned TRAIN inputs, performs no training, and prints an
aggregate report. It never obtains media or exports a controller. The observed
replay used Python 3.12.14 and NumPy 2.3.5. Matching
numerical-library/runtime behavior may be necessary for byte-exact array parity;
a mismatch must fail rather than silently relaxing the tolerance.

Original recordings are from [CREMA-D](https://github.com/CheyneyComputerScience/CREMA-D),
pinned at `1658cd342dff90010aa843eaeebd53610a08b1dc`.
Its [license](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/LICENSE.txt)
separates ODbL database rights from DbCL content rights. Any independent acquisition
or private-bundle transfer must respect applicable licenses and rights; this
package does not grant media, derivative-database, or weight redistribution rights.

## Next development gate, not confirmation

Use fresh source-group development material with observable heterogeneous
information gaps and genuine trainable refinement actions. Establish useful
oracle headroom at declared cost/coverage before fitting even a small router.
Only then freeze a new training-by-inference factorial experiment with separate
development/calibration/confirmation groups, independent training seeds and
external terminal assessment. Never relabel these eight TRAIN recordings or
their frames as unseen validation. All real-model generalization, natural
four-modal generation, independent semantic truth, physical-energy and production
claims remain unqualified. **RESEARCH_ONLY / HOLD_NO_GO.**
