# Exploratory long-delay training followup

15/15 fresh fully trained models, plus unchanged original-checkpoint replays on the same new evaluation contract. Original30jobs and eight primary gates remain unchanged.

The original training included gaps0/8/32 but selected checkpoints on gap0. This supplement trains gaps32/96 and selects on their mean validation CE. Donors are different recordings from the same actor, and the original target segment has an explicit tag.

| Model | Full | Recall32 | Recall96 | Target zero | Old checkpoint, same Recall96 | New minus old95%CI | Complete CPU s |
|---|---:|---:|---:|---:|---:|---|---:|
| ordinary | 0.1562 | 0.1684 | 0.1667 | 0.1667 | 0.1979 | -0.0312 [-0.1094, +0.0208] | 12.651 |
| matched_c1 | 0.1753 | 0.1823 | 0.1806 | 0.1788 | 0.1736 | +0.0069 [-0.0399, +0.0521] | 12.745 |
| analytic | 0.1458 | 0.1562 | 0.1580 | 0.1580 | 0.1580 | -0.0000 [-0.0382, +0.0348] | 12.754 |
| cfc_matched | 0.1788 | 0.1649 | 0.1649 | 0.1649 | 0.1736 | -0.0087 [-0.0417, +0.0208] | 12.691 |
| cfc_same_width | 0.1667 | 0.1632 | 0.1632 | 0.1632 | 0.1684 | -0.0052 [-0.0365, +0.0226] | 12.724 |

## Does the retained target matter?

| Model | Recall96 minus target-zero |95%crossed-bootstrap CI|
|---|---:|---|
| ordinary | +0.0000 | [+0.0000, +0.0000] |
| matched_c1 | +0.0017 | [+0.0000, +0.0087] |
| analytic | +0.0000 | [+0.0000, +0.0000] |
| cfc_matched | +0.0000 | [+0.0000, +0.0000] |
| cfc_same_width | +0.0000 | [+0.0000, +0.0000] |

## Analytic versus controls on Recall96

| Control | Gain |95%CI|Adjusted lower|Exploratory pass|
|---|---:|---|---:|---|
| ordinary | -0.0087 | [-0.0503, +0.0399] | -0.0573 | False |
| matched_c1 | -0.0226 | [-0.0590, +0.0087] | -0.0660 | False |
| cfc_matched | -0.0069 | [-0.0295, +0.0260] | -0.0330 | False |
| cfc_same_width | -0.0052 | [-0.0382, +0.0278] | -0.0451 | False |

## Interpretation limits

- Three paired initialization seeds and eight actors give approximate, descriptive uncertainty; the historical test cohort has already been used. This is a new exploratory supplement, not an independent confirmation or a revision of original gates.
- Same-actor donors keep all test dependencies inside the actor cluster. Random derangements are fixed without using emotion labels. Original checkpoints are evaluated without any training or reselection on this identical test contract.
- Training packages differ in delay distribution, donor construction, modality-drop augmentation and checkpoint criterion. New-versus-old effects measure that package, not validation criterion alone.
- Target-zero removes the target recording's media, availability and elapsed-time information. A positive effect shows dependence on target information, not independently proven semantic understanding.
- Equal accuracy is not proof of strictly zero retained information. A separate posthoc inspection in TARGET_SENSITIVITY.json records class and logit changes: analytic changes one of576 class predictions with zero net accuracy effect; its mean absolute logit change is about0.000187. No useful retention benefit is established here.
- Recall96 repeats a different real recording's32feature steps three times. This remains an artificial tagged recall contract on offline full-clip-resampled features, not natural long-video memory or online causal perception.
- Analytic is a freshly parameterized per-step Brownian gate, not full HX or a renewal process. CfC uses official default equations with the documented NumPy initialization/runtime differences.
- Full CPU measures startup, data loads, training, validation, test and evidence writes; training12seconds is nested. Replay/audit costs are separate. No GPU, measured energy or foundation-scale conclusion.
