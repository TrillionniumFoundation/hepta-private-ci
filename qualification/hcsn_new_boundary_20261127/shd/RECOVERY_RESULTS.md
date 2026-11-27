# SHD: constructive two-layer learning and a 512-synapse language update

This checkpoint preserves measured results, source identities and the independent verification receipt for the CPU run on 2026-11-27. The original evidence directory contained 37 publication files including 14 independently restorable ZIPs (240 original members). All archives restored successfully; the independent replay output compared byte-for-byte to the original. The execution environment disconnected before those files transferred. This commit includes only the present recovery summary. The model tensors, probabilities, archive members and original source files must be recovered before claiming remote reproducibility. No retraining is represented by this commit.

## Corpus, dynamics and blind confirmation

The public Spiking Heidelberg Digits corpus has 20 English/German digit labels. The original authors provide the HDF5 data and compressed MD5s at https://zenkelab.org/datasets/. SHA-256 of training HDF5: `2bddb4bd46732f09982b7d1631b7c29c19853c73d3d240e3eb32bba909bdd6c1`. SHA-256 of test HDF5: `47d8621a092cb483bea9448a93c0a3375a6726d370045090c2f7a77f70f95df3`. Exactly 8,156 official training records contained 63,993,588 original events; 2,264 test records contained 18,631,462. Train/development had 6,645/1,511 records, with entire speakers 3 and 10 held out for development. Speakers 4 and 5 were absent from all official training. Conditional intervals use 10,000 paired speaker bootstrap replicates, seeds averaged before resampling. Two new speakers limit extrapolation.

Each time-stamped input event contributed to 28 frequency groups and exponential states with 35 or 100 ms decay. Twelve observations retained the last event. An independent brute force comparison on prespecified training samples agreed within 5.12e-13. Two trainable hidden matrices drove the stationary literal He–Xiong equity/finite-horizon passage receiver twice, followed by six chronological pooled bins and a task head. The original coefficients and frozen reference are from cf5aa0c954e92fbecd3a53494ccefaa37a2bb7d0, qualification/hcsn_research_20261127/literal/cell.py. The observation architecture does not include a full moving-boundary regenerative population or a hardware sparse event engine.

The preregistration SHA-256 was `d9777115671187a57149bb60299f3f00996869155238eaab170d8f605739e1c8`. The shared 33-checkpoint seal SHA-256, computed before official label access for scoring, was `87073c02b02ca368c7861f60576a2bbac0a7dbea302850e70832ba08c6eaaf60`. The complete lower and upper matrices of the constructive models were fitted in blocks of four from whitened features and current supervised output residuals, followed by a ridge task head. Same-architecture BP and two-layer temporal convolution were optimized with AdamW using two learning rates, 384 steps and three seeds. The cheap ridge baseline received the identical flattened leaky features.

## Constructive 20-class result

| Network / representation | Recording accuracy | Equal-speaker accuracy | Mean of two unseen speakers |
|---|---:|---:|---:|
| Forward-only two physical hidden layers | 63.47% | 70.86% | 61.25% |
| Forward-only two ordinary matched smooth layers | 65.02% | 73.68% | 62.42% |
| Ridge on untransformed normalized leaky traces | 71.69% | 77.74% | 69.77% |
| Temporal convolution selected by development, three seeds | 74.15% | 80.24% | 72.28% |

The physical construction improved on equal-width randomly fixed physical layers by +23.20 percentage points (95% paired interval +20.56 to +26.03), and on within-speaker shuffled residual construction by +13.40 points (+10.68 to +16.00). It underperformed the development-selected convolution by 9.39 points (interval −12.96 to −5.75), with a loss of 11.03 points for the two new speakers. Its accuracy difference from trained identical-architecture physical BP was −0.07 point (−5.14 to +4.20); the unseen difference was −7.09 points. The specified −2-point noninferiority requirement failed. A positive true hidden-learning mechanism and a negative architecture/replacement gate coexisted.

## English-parent to German-digit hidden editing

Newly fit three independent English-only ten-digit parents. Freeze first-layer, hidden bias and task readout. Each edit can modify the 32×16 second-layer matrix (512 synapses). The direct arm used 12 or 32 orthonormal forward perturbation directions, two-sided nonlinear output differences, supervised local quadratic new-task loss, old-logit change penalty, development-selected scale and KEEP. Same-site Adam and rank-4 LoRA each used 3 learning rates and 12/48/96-step development candidates and could select KEEP. A within-training-speaker shuffled-label arm tested the direct method.

| Method | New German speaker-balanced change | Old English speaker-balanced change | New speakers' German / English changes |
|---|---:|---:|---:|
| Direct forward-only | +1.75 pp [0.70, 2.71] | −1.48 pp [−2.65, −0.48] | +2.64 / −0.33 pp |
| Label-shuffled | +0.44 pp [−0.57, 1.33] | −1.07 pp [−2.15, −0.04] | +1.30 / +0.34 pp |
| Rank-4 LoRA | +9.72 pp [7.80, 11.97] | −10.63 pp [−13.72, −7.00] | +9.39 / −10.97 pp |
| Same-site Adam | +9.46 pp [7.57, 11.47] | −5.84 pp [−9.89, −1.53] | +9.69 / −5.08 pp |

For the two previously unseen speakers, direct edits at seeds 137/251/389 changed German accuracy by +2.66/+4.02/+1.24 pp and English by +0.05/−0.37/−0.67 pp. Thus two parents passed both point thresholds and the all-parent gate failed. On the wider official speaker population parent 389 also lost 3.16 pp on old English.

## Costs and independent readback

The measured preparation stage accounted for 5.69 s of CPU host wall (data preparation plus table creation, excluding Python startup). The original source acquisition previously took 28.253 s. CPU single-thread constructive fit/search and independent cold test 1.64 s; the shallow feature ridge took 1.38 s. Same-architecture BP took 7.59 s per seed averaged across three including recorded interrupted attempts. Temporal convolution took 6.55 s. Three parents' combined post-training incremental wall was 6.67 s direct, 10.57 s LoRA, 13.16 s Adam. Their common English parent fitting/verification totaled 15.36 s. Every successful method searched on development; cheap fits, failed processes, cold confirmation and common costs are separate. The measured quality/retention tradeoffs prevent interpreting method-time ratios as equal-quality acceleration.

The independent procedure checked every model and all 1,086,720 saved logits for 51 combinations of model and task, recalculating class decisions, equal-speaker and recording accuracy. An independent FP64 implementation of (A7) and the first-passage formula bypassed the interpolation tables and replayed both layers on 43 pre-fixed examples in each of 28 physical networks. Max absolute logit difference was 0.000052521956825479776, with zero changed decisions over these sampled paths. This was a real CPU execution and local archive replay. The frozen protocol, raw checkpoints, cold scores and arrays are still needed to reproduce it from this branch.
