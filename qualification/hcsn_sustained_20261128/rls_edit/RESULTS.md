# Sequential editing of three trained HCSN heads

The experiment fits the single-layer quadratic from Wang et al., IJCAI 2026, to pre-head activations from the audiovisual and text branches of an already trained six-layer HCSN. Each parent has 731,168 parameters. The shared 256-by-96 matrix contains 24,576 editable entries. The original full-network BP fits took 66.63, 65.68 and 66.26 seconds. Both text-gallery directions and clip embeddings are recomputed after changing this common matrix.

The six interventions cycle the six emotion labels within each of the first six script lines, one line at a time. Every comparison preserves the labels of the other six protected script lines. The last-stage panel contains 96 held clips belonging to the newest edit, 640 belonging to the five previous edits and 575 permanently protected clips. The original actor split contributes 16 held actors. Selection and the 306 candidate states across 162 seed/method/stage records were frozen before the first held intervention scoring.

| Method after six edits | Latest NLL | Past NLL | Protected NLL | Protected top-1 | Six editing computations |
|---|---:|---:|---:|---:|---:|
| Trained parent | 4.551 | 4.796 | 3.247 | 19.88% | — |
| Recursive Eq. 3, μ=1 | 3.453 | 3.200 | 4.228 | 7.88% | 0.020 s |
| Recursive Eq. 3, μ=4 | 3.482 | 3.281 | 3.881 | 11.59% | 0.016 s |
| Latest-only solve, μ=4 | 3.520 | 4.850 | 3.336 | 17.68% | 0.010 s |
| Same quadratic, Adam, μ=4 | 3.571 | 3.263 | 3.789 | 12.64% | 0.169 s |
| Task cross-entropy, same head, Adam, μ=4 | 2.584 | 2.260 | 5.979 | 2.32% | 4.191 s |

At μ=4 the recursive solution improved the last and previous edits by 1.069 and 1.516 NLL relative to the parent. The corresponding 95% paired actor intervals for the signed changes were [−1.309, −0.836] and [−1.664, −1.362]. Protected NLL increased by 0.634 [+0.550, +0.715]. Against the latest-only μ=4 control, recursive editing reduced previous-edit NLL by 1.569 [1.432, 1.695], with protected NLL higher by 0.545 [0.456, 0.635]. The task-trained head achieved the lowest NLL on the requested changes and the highest NLL on protected material.

The preregistered matched-quality rule included current adherence, retention of older edits and protection of never-edited material. All enrolled fixed methods were censored for the three-seed rule after the sixth edit. The numerical editing-time savings in the table cannot identify an equal-quality end-to-end speedup. The fixed comparison's first stage was an exception for the μ=4 quadratic-gradient control, where three seeds met the joint gate, with a 7.89-second end-to-end qualification upper bound.

NumPy reconstructed all 306 deployed head score states. The maximum independent FP64 cumulative-batch versus Woodbury weight difference was 1.21×10⁻¹². The maximum FP64 replay difference from the FP32 deployed logits was 1.23×10⁻⁵. Reconstructed paired actor confidence interval endpoints agreed within 6.7×10⁻¹⁶. All 27 method/seed bundles, the three exact parent checkpoints and the raw held predictions can be reconstructed from the release.

## Follow-up on stronger protection

After the primary cold results, one single coefficient for all seeds and stages was selected entirely on development, using the separately specified grid 8, 16, 32, 64, 128, 256 and 512. The new selection chose μ=32 before making its confirmation predictions. The same three-seed gates were met by 0, 3, 3, 0, 1 and 2 seeds, respectively, over the six stages. The last-stage changes relative to the parent were −0.1104 NLL on the current edit [−0.1459, −0.0733], −0.1764 on past edits [−0.2008, −0.1548] and +0.0098 on protected material [−0.0051, +0.0231]. Protected top-1 changed by −0.058 percentage points. Seed 137 improved the current edit by 0.0555, below the required 0.10. The two successful intermediate three-seed stages provide a bounded example of useful editing with preservation. This cohort had previously been examined, so an independent dataset remains necessary for an external confirmation.

All three 200-by-96 anchor matrices had numerical rank 96 under the FP64 tolerance. At the FP32 tolerance the ranks were 95, 95 and 96. The corresponding fractions of edit-key energy outside the anchor row space were 1.33×10⁻⁹, 1.66×10⁻¹² and 1.85×10⁻³⁰. If all original anchor output vectors are preserved exactly and the anchor matrix has full column rank, K₀ΔW=0 forces ΔW=0. The experiment's softer distribution and accuracy constraints allow measurable changes along those directions.

The primary development seal is `deea9b35799c5cdc1a9c2c787be6494f4a098d07ef60060567b18383351b5eba`; primary terminal SHA-256 is `6d2a8b9a748970912222ae0c3d38873ba86802b16c18e62ba8fc2b85018b4aac`. The separate follow-up seal is `77c511996a1fdf5782d2f628af19c4fbb6f883ae7d194fe7b2bb0d609890053c` and its terminal SHA-256 is `8969b09c938cd9298fe0c47f6405a3c3112b286f3510463c843a138daa7ab7ba`.

## Gradient controls at the locked stronger coefficient

Applying the already fixed μ=32 to the same architecture, same edit targets, same protected anchors and same gradient budgets produced 144 further held head-score arrays. Cumulative RLS met the joint three-seed gate at stages two and three, taking 7.865 and 7.900 seconds through qualification respectively under the recorded upper-bound accounting. The latest-only, same-objective Adam and downstream cross-entropy Adam controls were each censored for all-three-seed qualification at both stages. The downstream gradient control did qualify at stage one in 8.037 seconds, where the RLS arm was censored. No common passing stage supports a matched-quality speed ratio. After stage six, current/past/protected NLL for downstream gradient editing was 3.514/3.122/3.529 versus 4.440/4.620/3.257 for RLS. The additional result's selection and terminal hashes are `daf667f1a3837e2e544c19dc83278eb0c1052a4e38cab0411301536ce05af4e6` and `02233855f6a08fb465335d9099f59895f55e587a6b943b0b04a79f83304e5fe8`.
