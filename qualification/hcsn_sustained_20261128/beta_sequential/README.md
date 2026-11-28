# A 2026 sequential weight editor on trained HCSN encoders

We applied BetaEdit's published projected matrix-write equation to the shared audiovisual/text output head of three trained HCSN encoders. The target, protected anchors, ordering and test are identical to the existing head-level RLSEdit and cross-entropy BP arms. Features come from the complete native-resolution CREMA-D parent training (4,984 train, 1,147 development and 1,311 actor-held clips). The original author method on language models optimizes desired latent vectors; our HCSN adaptation supplies original prompt target directions. The parent models were previously fully trained by BP. This trial evaluates post-training editing.

Each six-stage sequence shifts emotion labels within one more sentence and preserves the remaining six protected sentences. Stage six contains 96 current, 640 previous-edit and 575 protected held clips, clustered by 16 actors. The joint gate requires the current edit to improve NLL by ≥0.10, previous edits by ≥0.05, protected NLL degradation ≤0.10, and protected top-1 loss ≤0.02. A seed qualifies only if development and held gates both pass.

| Fixed unscaled head after six edits | Current NLL | Previous-edits NLL | Protected NLL | Joint passing seeds, stages 1–6 |
|---|---:|---:|---:|---|
| Parent | 4.55060 | 4.79634 | 3.24744 | 0, 0, 0, 0, 0, 0 |
| BetaEdit matrix update | 4.13990 | 4.15698 | 3.56528 | 1, 0, 0, 0, 0, 0 |
| BetaEdit, frozen projection | 4.13985 | 4.15690 | 3.56535 | 1, 0, 0, 0, 0, 0 |
| Refreshed projection, omit leakage penalty | 4.09262 | 4.09499 | 3.74693 | 0, 0, 0, 0, 0, 0 |
| Frozen projection, omit leakage penalty | 4.09271 | 4.09495 | 3.74706 | 0, 0, 0, 0, 0, 0 |
| RLSEdit, μ=32 | 4.44022 | 4.61990 | 3.25725 | 0, 3, 3, 0, 1, 2 |
| Same-head downstream BP, μ=32 | 3.51356 | 3.12232 | 3.52928 | 3, 0, 0, 0, 0, 0 |

The new solver was compared directly to the full author-form projected linear system, with maximum difference 2.85e−16 on a numerical fixture. Projection subspace dimensions were 59, 56, 56 across the three parents. Each stream refreshed twice using the accumulated prior requests. Removing the leakage penalty increased protected NLL. Refreshing the projection had little effect in these six stages.

## Development-chosen deployment gain

A single gain per method, fixed across all three seeds and all six stages, could also be chosen from 0.25, 0.5, 0.75 and 1 using development only. It interpolates toward the original parent after training; every later stage still advances the unscaled writing algorithm. The chosen gains were 0.25 for BetaEdit, its three ablations and downstream BP, and 1 for RLSEdit. The unchanged parent has identical predictions at all gains.

| Method with development-selected gain | Current NLL | Previous-edits NLL | Protected NLL | Joint passing seeds, stages 1–6 |
|---|---:|---:|---:|---|
| BetaEdit matrix update | 4.41640 | 4.59737 | 3.27632 | 3, 3, 3, 1, 2, 2 |
| Frozen projection, retain leakage penalty | 4.41639 | 4.59734 | 3.27632 | 3, 3, 3, 1, 2, 2 |
| Refreshed projection, omit leakage penalty | 4.38919 | 4.56132 | 3.29159 | 3, 3, 3, 2, 1, 2 |
| Frozen projection, omit leakage penalty | 4.38922 | 4.56129 | 3.29159 | 3, 3, 3, 2, 1, 2 |
| RLSEdit, μ=32 | 4.44022 | 4.61990 | 3.25725 | 0, 3, 3, 0, 1, 2 |
| Same-head downstream BP, μ=32 | 4.25717 | 4.30557 | 3.27812 | 3, 3, 3, 3, 3, 3 |

After six stages, adjusted BetaEdit minus adjusted downstream BP NLL was +0.15923 [0.13870, 0.17842] on current edits, +0.29180 [0.26794, 0.31339] on previous edits and −0.00180 [−0.01864, 0.01535] on protected examples. The 95% intervals resample held actors jointly across the same three seeds. Under this deployment rule, BP passed all 18 seed/stage cells, BetaEdit passed 14 and RLSEdit passed nine. This actor cohort has been studied before. These are task-specific quality results. The archived BP control reuses its original 128-iteration cumulative optimizer while BetaEdit streams each new block. A separate fixed-gain timing experiment below compares the two passing procedures at their common third-stage endpoint.

An independent NumPy program recomputed the downstream scores, development and held gates, actor-cluster intervals and raw final logits across 44,597,952 scalar scores and 504 gate checks. Maximum metric difference was 1.15e−6, maximum interval difference 4.67e−7. Every decision reproduced. See [complete protocol](PROTOCOL.md), [development freeze](development_seal.json), [complete terminal](terminal.json), [independent verification](verified.json), and [the 42 original head and prediction identities](index.json).


## Fresh-process time at a matched three-edit quality gate

After the main comparison, the third intervention and the already chosen 0.25 deployment gain were fixed for both BetaEdit and downstream BP. This is the last stage where both methods met the joint gate on all three seeds. We then reran the two complete procedures twice per seed in counterbalanced order. The quality data had already been studied. This experiment estimates the elapsed cost of the passing, fixed algorithms on reused parents. It does not determine the earliest possible time to the threshold.

Every native single-CPU-thread process freshly imported Torch, verified the full input hashes, loaded the source data and the correct trained HCSN parent, generated all training and development keys, ran sequential editing through stage three, and extracted the held keys and scored all 1,311 held clips. The endpoint includes launch through process exit. OS file caches were not flushed, and other workloads shared the host. The second-stage selection of the deployment gain and the historical cost of training the parent remained outside these new clocks. The genuine downstream BP implementation reran 128 cumulative-task Adam iterations at each stage. Its outputs and the BetaEdit outputs reproduced the archived stage-three heads bit for bit in all 12 processes.

| Fixed editing procedure | Matched development and held gate | Launch-to-exit median (6 processes) | Three-stage pure fitting median |
|---|---:|---:|---:|
| BetaEdit matrix update, gain 0.25 | 6/6 | 5.98776 s | 0.02122 s |
| Same-head downstream BP, gain 0.25 | 6/6 | 8.37231 s | 2.07873 s |

The ratio of launch-to-exit medians is 1.3982× in favor of BetaEdit. Six paired ratios range from 1.2643× to 1.6046×, with median 1.4399×. This positive result applies to three sequential changes of 24,576 parameters in an already trained 731,168-parameter audiovisual model. The final six-edit endpoint still has only two passing BetaEdit parents and three passing BP parents. End-to-end speed for the six-edit three-parent gate remains unresolved.

[Complete timed runs and gate metrics](timing_complete.json) · [Fresh-process timing implementation](timing.py)
