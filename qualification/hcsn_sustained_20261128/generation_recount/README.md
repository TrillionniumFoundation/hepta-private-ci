# Open-ended RSICD captions from six-layer HCSN encoders

The registered four-model, three-seed experiment reached all 12 fixed 900-active-second training endpoints. Every model generated held captions token by token from its raw image and a start token, with a 16-word maximum. The dataset contains 964 held images and five original-author references per image. The first endpoint selects a checkpoint solely on teacher-forced development NLL. The second uses the fixed last checkpoint. Each model used its own six temporal layers with the tied output vocabulary head.

| Checkpoint | Six-layer encoder | BLEU-4 | ROUGE-L | CIDEr-D | Teacher-forced NLL |
|---|---|---:|---:|---:|---:|
| Development-selected | Literal HCSN | 0.07218 | 0.28510 | 0.17512 | 3.17594 |
| Development-selected | Smooth matched control | 0.09733 | 0.28738 | 0.19419 | 3.15768 |
| Development-selected | Surrogate LIF | 0.09567 | 0.28181 | 0.16712 | 3.14014 |
| Development-selected | Causal attention | 0.08633 | 0.29024 | 0.20337 | 3.19665 |
| Fixed 900 s | Literal HCSN | 0.10247 | 0.29958 | 0.19330 | 3.27432 |
| Fixed 900 s | Smooth matched control | 0.09892 | 0.29567 | 0.21586 | 3.23840 |
| Fixed 900 s | Surrogate LIF | 0.09889 | 0.30235 | 0.18167 | 3.17723 |
| Fixed 900 s | Causal attention | 0.10372 | 0.30493 | 0.23040 | 3.30903 |

At the development-selected checkpoints HCSN minus attention was −0.02825 CIDEr-D, with paired 95% image-resampling interval [−0.04139, −0.01538]. At 900 active seconds it was −0.03710 [−0.05246, −0.02163]. Against LIF the corresponding effects were +0.00800 [−0.00341, 0.01889] and +0.01163 [−0.00493, 0.02791]. Development-selected HCSN minus smooth was −0.01906 [−0.03265, −0.00505]. Cyclically misaligning images and captions changed the selected HCSN CIDEr-D by +0.00168 for correct alignment [−0.00862, 0.01192]. The captions are real free generations. Their visual grounding is weak under this particular cyclic control. Held imagery comes from one remote-sensing corpus; this test does not measure general multimodal reasoning.

The independent evaluator reads the 24 native token arrays, the original natural reference JSON (SHA-256 `5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede`), and the sealed vocabulary. It recomputes per-image CIDEr-D including clipped term-frequency and corpus IDF, plus multi-reference ROUGE-L via a separate bit-parallel longest-common-subsequence routine. It also recounts BLEU-4 from archived clipped counts and teacher-forced NLL from the original 11,756 test token losses per checkpoint. The maximum per-image or aggregate discrepancy was 8.88e−16. Recomputing the paired 4,000-image bootstrap intervals across all arms and both endpoints changed a reported number by at most 1.39e−17. The raw token arrays occupied 370,176 padded slots across 24 model evaluations. Protocol, independent source, selection, original terminal and numerical receipt are linked below.

[Original protocol](../generation/PROTOCOL.md) · [Independent implementation](verify.py) · [Original selection](selection.json) · [Original terminal](generation_terminal.json) · [Independently verified results](verified.json)
