# Correlated training geometry with unchanged inference storage

Parent: `a20310944d3c97e51dce748e7b228b514608a9ae`, Draft PR #1654.
Existing qualification directory and physical-job owners only. No new loader,
runtime, durable store, live topology change, production promotion or Encoder copy.
V12's default diagonal experiment, all eighteen controls and its floors remain.

## Hypothesis, equations and fixed comparison

V12 pools only per-coordinate variances. V13 tests full pooled covariance, which
retains correlations between coordinates without storing a covariance matrix in
the inference Head. Each class and each source group receive equal fitting weight.
A source group's feature is the mean of its rows; repeated identical rows do not
increase its weight. Keep the original per-class prototypes mu_c and center m.
For the average within-class covariance S in raw Encoder coordinates, define:

    C = (1-alpha) S + max(alpha * trace(S)/d, 1e-8) I
    C w_c = mu_c - m
    b_c = -0.5 (mu_c-m)^T w_c

A checked float64 Cholesky solve is used, not an explicit inverse. Fixed scaled
residual tolerance is 1e-8. Rank-deficient and zero-variance examples use the same
fixed floor; there is no adaptive jitter or fallback after a failed factorization.
For alpha=1 the old spherical routine is called directly: the parameters are
bit-identical and neither a dense covariance nor its factor is allocated.
For alpha<1 the fitting geometry is rotation-equivariant in exact arithmetic;
this is a property of the estimator, NOT a statement about learned task quality.

Reuse V12's four source-group-stratified TRAINING folds, alpha in (0.1,1.0),
temperature in (1,4,16,64), and binary group-log-loss objective. Each fold refits
all statistics using its own training inputs. Neither calibration nor held-out
features/labels fit the geometry. Memory arms use 32 old + 120 new training rows;
all-old arms use 160 old + the SAME 120 new rows and are explicitly more expensive.
Whole content groups and original conflicting labels remain in the same folds
and protected publisher-derived splits. No true old/new group is given at inference.

The producer/reviewer are the EXISTING cell_prototype_study.py with explicit
`--covariance-profile paired-full`. This adds four full-family rules to the
fourteen V11 and four V12 rules; geometry-only ablations store/execute no expert.
The default remains diagonal v1. Paired v2 records bind the profile, complete
22-rule census, parameters, fitting work and independently reconstructed logits.
Training/CV replay still uses the SAME fitting implementation. It is not an
independent statistics implementation or an authenticated hardware execution.

## Cost and mathematical checks

Full fitting admits a conservative explicit float64 intermediate envelope before
matrix allocation: 4*n*d+8*d*d+8*k*d elements, at most 8,388,608. The spherical
fast path omits the matrix term. This excludes callers' retained inputs, index
objects, allocator and LAPACK workspace; it is NOT total RSS or a process limit.

At d=384 the covariance and factor each contain 1,179,648 bytes during correlated
fold fitting. The all-old envelope is 13,074,432 bytes. Packed conditional Heads
still contain 6,160 FP32 scalars / 24,640 bytes, equal to V12; geometry-only uses
3,080 / 12,320. No covariance, Cholesky factor or replay examples survive in them.
Encoder and normalizer costs are additional. Identical inference tensor shapes
are NOT proof of equal end-to-end latency or quality.

Two full-family searches add 18 statistic fits and 3,456 CV prediction rows.
The paired profile also reruns the 18 diagonal fits, so its total is 36 fits /
6,912 CV rows. The final observed choice needs eight actual factorizations and
ten spherical calls in the full family, not eighteen factorizations. Ancestor
conditional fitting is resealed after source changes: its 600 optimizer steps
and calibration costs remain in lineage, not reported as free teacher knowledge.

## Observed negative result and preserved optimization evidence

Reuse the authenticated f30abc25 physical BGE feature bundle, whose raw feature
SHA256 is `d6022c07854267243dba6ff11b9723376f3a24d8410bf55b14bea20eb7ea7032`.
No local Encoder forward ran. This is exploratory work on already inspected
public data, not independent preregistration or prospective Hepta evidence.
The grid and thresholds were recorded before V13's first fit; none was retuned.

| Selected family | Old held-out correct /120 | New held-out correct /120 |
| --- | ---: | ---: |
| V12 diagonal, 32 old memory rows | 118 | 118 |
| V12 diagonal, all old rows | 120 | 116 |
| V13 full search, 32 old memory rows | 118 | 118 |
| V13 full search, all old rows | 120 | 116 |

Both full searches chose alpha=1, temperature=16 on training folds. Thus the
selected V13 models use SPHERICAL geometry, not a successful learned correlation.
The all-old V12 diagonal fit chose alpha=.1, temperature=16. Full-family all-old
reminder calibration remains 16/20, Brier .322495, compared with old teacher
19/20, .089908. The unchanged two-sided rule selects frozen with qualified=false.
No quality benefit, statistical superiority or forgetting solution is established.

The first implementation actually factorized the spherical matrices too. Its
original results/costs are retained. After removing only that redundant work,
all eight candidate tensor files and all predictions are byte-identical to the
first run. The parameter grid, labels, folds and retention floors did not change.
The final 8,822 calibration/test rows replay within 1.9073486328125e-6, with zero
argmax reversals. They represent only 240 distinct held-out inputs.

## Reproduce and remaining boundaries

Use the V12 CLI with the same source-run/dataset/consolidation-run/anchor-run/
conditional-run and a new create-only output, adding:

    --covariance-profile paired-full

Run its separate --review-run command afterwards. Existing source-head AND
prospective-merge tests now explicitly include cell_correlated_checks; the new
paired command is appended to the existing physical BGE job, never replacing
fresh encoding, V9-V12 controls, global CI or native acceptance.

310 local tests passed, zero skipped: 287 inherited plus 23 new. New checks use
synthetic inputs and include an independently constructed NumPy covariance solve,
rotation invariance, exact spherical equivalence, source duplication, train-only
isolation, faulty-solver rejection and rehashed evidence tampering. The separate
real-feature experiment above uses complete original qualification files, not
function extracts. Local work does not compile the complete Rust monorepo.
New exact-SHA hosted execution must be observed separately; parent CI is not
new-source evidence. Native owner integration, future NDU benefit, semantic
recurrence and multimodal generation remain distinct uncompleted requirements.

Method background: scikit-learn's Linear/Quadratic Discriminant Analysis guide,
https://scikit-learn.org/stable/modules/lda_qda.html. Actual solve API: PyTorch
2.10 https://docs.pytorch.org/docs/2.10/generated/torch.cholesky_solve.html.
The group-balanced estimator, floors and observations above are this experiment's
own definitions/results, not a reproduction or guarantees from those sources.
