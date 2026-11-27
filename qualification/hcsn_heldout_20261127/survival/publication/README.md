# Empirical first-passage forecasts at unseen time horizons

The registered 50-candidate comparison completed on the Beijing and Tetouan source cohorts from repository head cf5aa0c954e92fbecd3a53494ccefaa37a2bb7d0. The first-passage HCSN produced higher mean Brier loss at the held-out 3 h and 12 h horizons than the development-selected conventional comparator in both sources. Models had seen 1 h, 6 h, and 24 h event labels during training. Confirmation used one common 50-checkpoint seal.

| Evaluation | Examples | HCSN with Brownian head | Conventional selection | Conventional loss | Paired HCSN minus conventional, 95% interval |
|---|---:|---:|---|---:|---|
| Beijing, original four held-out stations | 2,750 | .134704 | GRU with Weibull head | .116558 | +.018146 [.015084, .021042] |
| Tetouan, original held-out zone | 266 | .146277 | Smooth gate with Weibull head | .112394 | +.033882 [.017896, .049343] |
| Beijing, eight other stations in the final year | 5,446 | .126880 | Same GRU | .107263 | +.019617 [.015618, .023723] |
| Tetouan, two other zones in the final quarter | 545 | .141473 | Same smooth gate | .100591 | +.040882 [.028899, .051980] |

Original intervals resample site-weeks within each site as registered. Additional intervals resample common calendar weeks across sites. The additional records have zero duplicate station/timestamp pairs with any original split. They reuse both cities and the original evaluation calendar. Each interval conditions on the observed sites and trained models. Brier losses are per-prediction squared error. Lower is better.

Holding the encoder fixed changes the interpretation. With the physical encoder, the Brownian head beat its Weibull alternative in Beijing (.134704 versus .153149) and underperformed it in Tetouan (.146277 versus .102898). With the GRU, Brownian-minus-Weibull held-out loss was +.007323 [.004197, .010430] in Beijing and +.011483 [−.001449, .023540] in Tetouan. All heads, calibration diagnostics, seed-specific checkpoints, row-level predictions and per-arm costs are retained.

The original executable raised UnboundLocalError before the first learned-model update because an empirical-branch local variable shadowed the file-level prediction function. The two-name correction in prediction_shadowing.patch leaves all candidate choices and equations intact. Fresh preprocessing of both UCI raw archives reproduced all six originally registered input hashes. A storage interruption preserved 34 completed fits. The runner validated their hashes and completed the remaining 16 before sealing and cold-scoring. The interruption is included in the archives; recorded per-arm times refer to completed model fit and cold test, with concurrent CPU contention and failed controller work recorded separately. On this host the physical versus selected conventional mean completed fit and cold test took 19.58 versus 6.74 seconds in Beijing and 17.04 versus 6.86 seconds in Tetouan.

## Independent verification

Execute python verify_archives.py with NumPy. It checks 468 original archive members, recomputes the validation-only conventional selections and scores 100 independent probability arrays. A separate fresh process loaded all 50 frozen tensors and reproduced every original score exactly before forecasting the supplemental records. The full primary report is PRIMARY_RESULTS.json. ALL_EVALUATIONS.json gives per-arm supplemental results, paired contrasts, raw score equivalence and checkpoint identities. EVIDENCE_INDEX.json binds the ten independently readable ZIPs, every member and every byte size.

For a new full CPU reproduction, copy the included scripts, ADDITIONAL_COHORT_PROTOCOL.md and SOURCE_CHECKSUMS.json to an empty directory and execute python recover_research.py with internet access to GitHub and UCI. Python 3.12, NumPy, pandas and CPU PyTorch are needed. The script reconstructs the source from the immutable research commit and both original UCI archives, checks the input hashes, applies the recorded local fix, trains the registered candidates, and scores the original and additional observations. The full recovered checkpoint bytes can depend on the installed library versions. Runtime versions used here are recorded in SOURCE_CHECKSUMS.json.

Source datasets are Beijing Multi-Site Air Quality (UCI DOI 10.24432/C5RK5G) and Power Consumption of Tetouan City (UCI DOI 10.24432/C5B034). The supplemental study's frozen design and its independently checked roster hashes are ADDITIONAL_COHORT_PROTOCOL.md and ADDITIONAL_ROSTERS.json.
