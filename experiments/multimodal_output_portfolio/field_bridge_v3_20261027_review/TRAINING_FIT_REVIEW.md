# V3 training-fit independent review

## Disposition

**PASS for implementation, artifact integrity and the registered fitting procedure.** All three completed fits can proceed to the preregistered full-rollout development stage. This review is not a claim that the learned H12 policy improves training.

The independent audit used the already-published `training_fit_audit.py`, SHA256 `d76b84d7eb8023aa8b3bf676862e7ae3e4a0787a3ec70490741379d386c4b20b`, and the published `FIT_FREEZE.json`, SHA256 `1a87d3b246e6582f271f89411a0309b07661a45a98a65d95b68f3e71a832af1c`. It read completed bank/fit artifacts only. It loaded no source roles, performed no gradient updates, changed no controller and generated no new scientific model output.

## What was independently reconstructed

Each seed has four representation families, three predeclared ridge values, four whole-trajectory validation folds and one full-bank fit for each candidate: 48 fold heads plus 12 full-bank candidates, or 60 solves. All 180 solves across the three seeds were reconstructed using augmented least squares rather than the frozen scientific implementation's normal-equation solver. Raw and projected normalizers, family projections, held-out predictions, fold and pooled squared errors, selected candidate indices and complete selected heads agree. The maximum tensor discrepancy across all seeds is below 3.82e-11, versus the predeclared 1e-8 coefficient tolerance.

The audit also verifies the completed inventories, bank/continuation reference identities, exact 24-state by four-action target grid, exclusion of the entire held-out trajectory from each fit, deterministic selection ties and the complete fitting-cost ledger. The 180 verification least-squares solves are additional verification work; they are not replacement trained heads. Shared counterfactual-bank costs remain charged once in the bank stage.

## Complete registered CV grid

Errors below are pooled held-out-trajectory mean squared errors for the four terminal Qref targets. Every family and seed selected alpha 1, the largest member of the registered grid. The family labelled `field` is the prospectively designated H12 treatment.

| Seed | Family | MSE at alpha 0.0001 | MSE at alpha 0.01 | MSE at alpha 1 | Selected alpha |
|---|---|---:|---:|---:|---:|
| 17 | field | 0.000335685837111 | 0.000137642632969 | 2.82522251186e-05 | 1 |
| 17 | generic | 0.00225459170638 | 0.000367398338897 | 2.84882979317e-05 | 1 |
| 17 | richer | 0.00896146924794 | 0.000503399568057 | 3.51453788702e-05 | 1 |
| 17 | h7 | 7.56889867135e-05 | 4.91142296911e-05 | 1.68668796766e-05 | 1 |
| 29 | field | 0.000404265409433 | 0.000183653611038 | 4.17076781933e-05 | 1 |
| 29 | generic | 0.000986674652545 | 0.000383819342072 | 7.05098253386e-05 | 1 |
| 29 | richer | 0.00178795060817 | 0.00058951690253 | 7.35655310567e-05 | 1 |
| 29 | h7 | 9.83461359781e-05 | 8.63790646255e-05 | 3.30259019324e-05 | 1 |
| 43 | field | 0.000662428836068 | 0.000354934084821 | 0.000140048890684 | 1 |
| 43 | generic | 0.00205154209589 | 0.000418085913363 | 0.00012844038502 | 1 |
| 43 | richer | 0.020666748149 | 0.000680491127619 | 0.000127051087529 | 1 |
| 43 | h7 | 0.000113779697135 | 0.000100183132766 | 8.87801684845e-05 | 1 |

## Prospective interpretation

1. **H7 currently predicts these reference-continuation targets with the lowest CV MSE in all three seeds.** H12 is slightly better than generic12 at seed 17 and better at seed 29, but worse at seed 43; richer30 also does not consistently improve on H7. These are descriptive fit diagnostics, not independent efficacy tests. H12 remains the predeclared treatment; the feature family must not be changed after these results.
2. **The strongest registered regularization won throughout.** That is compatible with limited effective information and unstable weakly regularized fits in a 24-state bank. It does not establish that an enlarged alpha grid would improve the deployed policy. No grid extension or refit is permitted in this study.
3. **Whole-trajectory CV is not source-population validation.** Its four folds hold out complete exploration trajectories, while the labels still use the same fit-only source roles and response panel. Four trajectory groups, six states per group and four paired action targets do not constitute 96 independent examples. Source-disjoint policy-development and untouched rollout-audit roles supply the later generalization boundary.
4. **Qref is a conditional continuation target.** It measures one candidate block followed by the frozen reference policy and common clean guard through step 288. The deployed receding policy can choose a new action at every decision. Predicting Qref accurately does not prove that this new closed-loop distribution has greater terminal utility, better action ranking or better retention.
5. **The release gate remains complete rollout performance.** The frozen development procedure must first compare full H12 rollouts with the strongest eligible ordinary constants and the prospectively selected adaptive comparator. The untouched rollout audit must then satisfy the registered both-observer gain and retention conditions. No CV value above substitutes for those gates.
6. **The empirical clean guard has a limited claim.** Its accept/rollback decision protects the registered training guard panel; it is not a population retention guarantee. Rejected updates and their teacher/probe work remain in the resource ledger. The independent clean endpoint panels and later retention tests remain necessary.
7. **The model and objective scope stay explicit.** The three original model seeds are fixed historical models; no new-model-seed or general LLM field-theory conclusion follows. Training uses the registered single-output-action objective. Any subsequent delayed-feedback runtime task is a separately qualified transfer setting.

## Audit identities

- `FIT_AUDIT_17.json`: `652a885a8458ba515f630cde08ec1fef84a7a610e5e11d6ec2638ad19ee94efb`; maximum independently reconstructed tensor discrepancy `3.488440092347389e-11`.
- `FIT_AUDIT_29.json`: `b3f9ea0679ccfadf43ad5fd3a5c454a7d68ef079924f40371ad320921d7aab44`; maximum independently reconstructed tensor discrepancy `1.813920801757574e-11`.
- `FIT_AUDIT_43.json`: `60821dd4600bd6033865c44ed5c73ac7cdf504bf3c69ecc72a3a5e8e5bf40648`; maximum independently reconstructed tensor discrepancy `3.819525945525371e-11`.

Reports reside under `bridge_v3_review/`; the exact controller, bank and completion hashes are included in each report. No frozen scientific sources were modified by this review.
