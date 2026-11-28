# All 24 RAVDESS actors in zero-shot transfer from CREMA-D

The independent scorer revalidated every source weight, every score archive and the exact external feature package for the first two complete prespecified model groups. It reconstructed the six-emotion logits from the 72 original CREMA-D gallery logits for every audiovisual trial. All 24 actors contributed 44 trials each (1,056 clips). The six classes have 192, 192, 192, 192, 96 and 192 examples. Every coefficient remains frozen from CREMA-D. The actor-resampled 95% interval uses the same 4,000 resamples across compared models, conditional on the three fitted seeds.

| Source method and budget | Six-emotion NLL | Accuracy | Balanced accuracy |
|---|---:|---:|---:|
| Forward seven-matrix write, full-data source | 2.06478 | 18.47% | 20.34% |
| Same seven matrices, BP | 1.79097 | 24.78% | 23.78% |
| Full-parameter BP | 1.86628 | 28.91% | 26.53% |
| Fixed analytic HCSN, one pass | 1.66786 | 28.38% | 26.01% |
| Learned-contract analytic HCSN, one pass | 1.65984 | 28.82% | 26.42% |
| Causal attention, one pass | 1.76920 | 28.31% | 25.95% |
| Fixed analytic HCSN, 60 s | 1.77955 | 27.90% | 26.30% |
| Learned-contract analytic HCSN, 60 s | 1.71514 | 29.26% | 26.82% |
| Linear moving-boundary HCSN, 60 s | 1.69775 | 28.47% | 26.10% |
| Causal attention, 60 s | 1.97846 | 29.70% | 27.31% |
| Fixed CREMA-D class prior | 1.78164 | 18.18% | 16.67% |
| Uniform | 1.79176 | 18.18% | 16.67% |

At the equal-update one-pass endpoint, exact HCSN minus attention had NLL −0.10134 [−0.11195, −0.09100] and accuracy +0.06 percentage points [−0.95, +1.14]. At the 60-second source-training endpoint the NLL difference was −0.19891 [−0.25908, −0.14392] and accuracy difference −1.80 points [−3.63, +0.06]. The direction of the NLL result supports a probability-scoring advantage for these source-frozen analytic models on this external corpus. The uncertainty in accuracy covers zero.

The full-data direct-writing arm transferred worse than BP at the same writable sites. The direct-minus-BP NLL difference was +0.27381 [0.23509, 0.31303], with accuracy −6.31 points [−7.48, −5.05]. A favorable analytic architecture transfer is compatible with poor transfer of an update rule on the same architecture.

The native score panel contains nine full-data editing models and 30 analytic-model checkpoints. Independent verification covered 2,965,248 full-gallery logits and checked the emitted scores, source weights, original clip ordering, controls, group aggregates and actor bootstrap. The maximum numerical discrepancy was 5.33e−15. The third preregistered group is eligible only after the separate 12-cell sustained source experiment freezes all its checkpoints.

[External protocol](../ravdess/PROTOCOL.md) · [Verified metrics and paired intervals](verified.json) · [Independent scorer](verify.py) · [Completed input corpus](prepared.json) · [Nine source-edit endpoints](scores-full/terminal.json) · [Thirty analytic endpoints](scores-analytic/terminal.json)
