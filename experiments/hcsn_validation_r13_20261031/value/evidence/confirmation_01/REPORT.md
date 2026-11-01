# R13 public-state SKIP-tail confirmation

Three pre-existing fit seeds, six fixed backbone checkpoints; four task configurations are conditions. Report every seed, fixed-condition mean and observed seed range, not confidence intervals or significance. No natural-media, full financial-HX propagation, content-learning, GPU or foundation-network claim.

All original and transformed controllers are retained. Critic scores are unchanged; calibration uses each executed policy's actual Qpi.

| Core / controller | Return | Correctness | READ | SKIP | Below initial STOP | Actor CPU ms |
|---|---:|---:|---:|---:|---:|---:|
| ordinary/lightweight | 0.457970269 | 0.819894 | 2.748384 | 0.000000 | 3/12 | 0.254954 |
| ordinary/lightweight_tailstop | 0.457970269 | 0.819894 | 2.748384 | 0.000000 | 3/12 | 0.241858 |
| ordinary/matched_qstar | 0.586004388 | 0.700668 | 1.610209 | 2.615862 | 3/12 | 0.361757 |
| ordinary/matched_qstar_tailstop | 0.591627131 | 0.700668 | 1.610209 | 1.288208 | 0/12 | 0.413327 |
| ordinary/original_qstar | 0.402900977 | 0.817561 | 2.964489 | 2.189347 | 5/12 | 0.429883 |
| ordinary/original_qstar_tailstop | 0.411636170 | 0.817561 | 2.964489 | 0.598190 | 5/12 | 0.411702 |
| ordinary/qpi_selected | 0.671372744 | 0.756472 | 1.318571 | 1.362856 | 3/12 | 0.247241 |
| ordinary/qpi_selected_tailstop | 0.677001434 | 0.756472 | 1.318571 | 0.033962 | 0/12 | 0.226026 |
| analytic/lightweight | 0.453641573 | 0.823009 | 2.774255 | 0.000000 | 3/12 | 1.641365 |
| analytic/lightweight_tailstop | 0.453641573 | 0.823009 | 2.774255 | 0.000000 | 3/12 | 1.608028 |
| analytic/matched_qstar | 0.593399906 | 0.706960 | 1.595381 | 2.611617 | 3/12 | 1.610488 |
| analytic/matched_qstar_tailstop | 0.599002271 | 0.706960 | 1.595381 | 1.288208 | 0/12 | 1.714145 |
| analytic/original_qstar | 0.420211698 | 0.821580 | 2.869281 | 2.292466 | 4/12 | 2.111211 |
| analytic/original_qstar_tailstop | 0.430272940 | 0.821580 | 2.869281 | 0.500951 | 4/12 | 2.075970 |
| analytic/qpi_selected | 0.605868425 | 0.733462 | 1.620467 | 1.146640 | 4/12 | 1.152831 |
| analytic/qpi_selected_tailstop | 0.609451917 | 0.733462 | 1.620467 | 0.295912 | 2/12 | 1.155164 |

## Every factorial effect

| Value policy | Effect | Mean | Min / max of three fit means |
|---|---|---:|---|
| qpi_selected | A | +0.457970269 | [+0.453565013, +0.463921141] |
| qpi_selected | B | +0.671372744 | [+0.627245502, +0.694459073] |
| qpi_selected | C | +0.453641573 | [+0.450157141, +0.455644800] |
| qpi_selected | D | +0.605868425 | [+0.551863448, +0.638496324] |
| qpi_selected | B-A | +0.213402475 | [+0.173680489, +0.235989004] |
| qpi_selected | D-C | +0.152226852 | [+0.101706307, +0.182851524] |
| qpi_selected | C-A | -0.004328696 | [-0.008276341, +0.001557766] |
| qpi_selected | D-B | -0.065504320 | [-0.140550210, +0.000000000] |
| qpi_selected | interaction | -0.061175624 | [-0.134282697, -0.001557766] |
| qpi_selected_tailstop | A | +0.457970269 | [+0.453565013, +0.463921141] |
| qpi_selected_tailstop | B | +0.677001434 | [+0.632495502, +0.699709073] |
| qpi_selected_tailstop | C | +0.453641573 | [+0.450157141, +0.455644800] |
| qpi_selected_tailstop | D | +0.609451917 | [+0.552113925, +0.643746324] |
| qpi_selected_tailstop | B-A | +0.219031165 | [+0.178930489, +0.242375074] |
| qpi_selected_tailstop | D-C | +0.155810344 | [+0.101956785, +0.188101524] |
| qpi_selected_tailstop | C-A | -0.004328696 | [-0.008276341, +0.001557766] |
| qpi_selected_tailstop | D-B | -0.067549517 | [-0.146685802, +0.000000000] |
| qpi_selected_tailstop | interaction | -0.063220821 | [-0.140418290, -0.001557766] |
| matched_qstar | A | +0.457970269 | [+0.453565013, +0.463921141] |
| matched_qstar | B | +0.586004388 | [+0.585409445, +0.586920780] |
| matched_qstar | C | +0.453641573 | [+0.450157141, +0.455644800] |
| matched_qstar | D | +0.593399906 | [+0.586981913, +0.596892442] |
| matched_qstar | B-A | +0.128034119 | [+0.121761799, +0.131844432] |
| matched_qstar | D-C | +0.139758333 | [+0.136824772, +0.141769663] |
| matched_qstar | C-A | -0.004328696 | [-0.008276341, +0.001557766] |
| matched_qstar | D-B | +0.007395518 | [+0.000061133, +0.011482997] |
| matched_qstar | interaction | +0.011724214 | [+0.006328645, +0.018918766] |
| matched_qstar_tailstop | A | +0.457970269 | [+0.453565013, +0.463921141] |
| matched_qstar_tailstop | B | +0.591627131 | [+0.591038135, +0.592665788] |
| matched_qstar_tailstop | C | +0.453641573 | [+0.450157141, +0.455644800] |
| matched_qstar_tailstop | D | +0.599002271 | [+0.592665788, +0.602643397] |
| matched_qstar_tailstop | B-A | +0.133656862 | [+0.127256329, +0.137473122] |
| matched_qstar_tailstop | D-C | +0.145360698 | [+0.142508647, +0.147520618] |
| matched_qstar_tailstop | C-A | -0.004328696 | [-0.008276341, +0.001557766] |
| matched_qstar_tailstop | D-B | +0.007375141 | [+0.000000000, +0.011605262] |
| matched_qstar_tailstop | interaction | +0.011703836 | [+0.006267513, +0.018796501] |

These ranges are descriptive, not confidence intervals. Compare guarded matched-Qstar as well as Qpi, and retain CPU and residual STOP failures.

The complete child-process receipt includes all state enumeration, actual execution, extra wrapper calls, evidence I/O and startup/exit. It must not be added to its nested actor times. Device energy remains unmeasured.
