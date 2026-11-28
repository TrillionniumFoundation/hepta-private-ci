# Named preservation constraints on the same hidden edit

Freeze this extension before opening A2, B2, or GRID outcomes. Use the two already registered sites, data, teacher, parents, clocks, cross-corpus gates and full controls. These are adaptations of named algorithms to a small continuous speech predictor. Neither is an execution of the authors' LLM benchmark.

## AlphaEdit projected writes

Fang et al., ICLR 2025. The official code audited at jianghoucheng/AlphaEdit commit b84624f44dfe8fc6cd9e41df916c44124a0c46dc constructs a projector from the small singular values of its preserved input moment matrix, stepwise divides the desired residual across the remaining edited layers, and solves a projected ridge system. The original target-value search performs Adam updates with loss.backward(). A closed-form write in that pipeline does not make the entire editing procedure gradient-free.

Construct physical input keys for each site using all time positions of the 120 old calibration examples. Compute the uncentered second moment. Use the literal numerical null space (tolerance max(shape) × machine epsilon × largest eigenvalue) as one control. Also test three low-energy spaces selected by eigenvalues ≤0.01, 0.05 or 0.2 times the largest eigenvalue. These relative thresholds accommodate acoustic features with a different scale from LLM hidden activations. Report every spectrum, retained dimension and exact-null degeneracy. Within the selected basis U, the row-oriented update is U (U' K' K U + lambda I)^(-1) U' K' R. Each new target value R is obtained by solving a damped local output-to-drive inverse on the true end-to-end forward sensitivity of one example. Re-evaluate the receiver after writing its sender. Split the desired residual over remaining sites. Refit under true-network trust scaling and old/new development selection. This target-value computation replaces the authors' LLM subject-token optimization. This is a single editing episode, so there is no prior-batch accumulated key cache. Equality of the linear algebra with a dense projected reference and deviation on the preserved key span are mandatory checks.

## CrispEdit capability-curvature constraint

Ikram et al., ICML 2026. Use the KL divergence of the old parent's output distribution against the edited output distribution as the preservation loss. At the frozen parent its exact Hessian is the Gauss–Newton matrix J_old' [diag(p) − p p'] J_old. Here the full space is only 336-dimensional, so form it from the true forward impulse responses and diagonalize it directly. Use eigenvalues ≤0.001, 0.01, or 0.1 of the maximum, preserving upstream and downstream couplings. Fit a damped Gauss–Newton task step within each allowed span; measure the actual old KL and end-to-end old task accuracy after each finite update. This imports the paper's low-curvature criterion. It uses an exact small-system curvature and a restricted least-squares task step in place of the paper's scalable K-FAC/matrix-free LLM procedure. Both the key-covariance and output-curvature methods receive the same source and teacher information as the unrestricted direct solver and same-site BP.

Charge the preserved-statistics pass, covariance/eigendecomposition, value retrieval, solves, validation search, teacher and held-out scoring. Report the one-time cost, per-episode application cost, and the hypothetical per-episode cost at 1, 10 and 100 identical uses; repetitions are a cost model, not measured future edits. The actual 3/15/60-second cold selections include one-time geometry, and comparison with earliest eligible exact same-site BP requires the published 20% total-time threshold. Fresh architecture- and teacher-matched outcomes are required; first-stage A/B results motivated the experiment.

Sources.

- https://github.com/jianghoucheng/AlphaEdit/blob/b84624f44dfe8fc6cd9e41df916c44124a0c46dc/AlphaEdit/AlphaEdit_main.py#L129-L149
- https://github.com/jianghoucheng/AlphaEdit/blob/b84624f44dfe8fc6cd9e41df916c44124a0c46dc/AlphaEdit/compute_z.py#L107-L185
- https://github.com/jianghoucheng/AlphaEdit/blob/b84624f44dfe8fc6cd9e41df916c44124a0c46dc/experiments/evaluate.py#L429-L443
- https://proceedings.mlr.press/v306/ikram26a.html
