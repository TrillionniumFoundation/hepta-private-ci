# WP1: retrospective diagnosis of the V10 memory bottleneck

## Finding and scope

The tested V10 canonical feature matrices can represent all their stored
targets with an affine map: an independent pseudoinverse control obtains
100% canonical exact recall at 32, 64, and 128 addresses, for both memory
types. The original capacity curve therefore does **not** establish a hard
representational limit at these sizes. Optimization budget matters, and the
frozen representation still provides very poor direct access from different
wording. These are separate findings.

This is a **retrospective diagnosis**, using the original V10 corpus,
checkpoints, and cached quantized-ONNX encoder features. Old held queries are
used to understand an already observed failure; they are not fresh efficacy
evidence. Nothing here changes V10's original qualification decision, promotes
its failed split candidates, or establishes the capacity of nonlinear memory
modules or attention-internal Transformer adapters. Fresh V11 content results
are reported separately in [CONTENT_REPORT.md](CONTENT_REPORT.md).

The complete results, parameter files, executed diagnostic source, source
identity records, and development evidence are retained in the
[immutable WP1 package](evidence/archives/wp1-model-development/README.md).
The package preserves the original archive bytes:

- Archive: `v11-wp1-model-development-evidence.tar.xz`.
- Size: 1,287,748 bytes; 53 member files totaling 4,714,197 bytes.
- SHA-256: `69235d13b7b5655bea8d63e93b55a3e8b0807874e2c880e55bf0e420119bfef2`.
- Results: `v11-diagnosis-geometry/DIAGNOSIS.json`,
  `v11-diagnosis-budget/DIAGNOSIS.json`, and
  `v11-diagnosis-procedure-budget/DIAGNOSIS.json` inside the restored package.

## What V10 actually trains

For a row feature vector, the residual arm computes

```text
z = x + (x A^T) B^T
logits = z H^T + b
```

There is no activation between these operations. The effective input/output
map is affine. Although the residual branch has rank 4, the full output head
`H` is also trainable. Setting the residual contribution to zero leaves a
full affine head. Consequently, describing this model's effective map as
rank-4-only would be incorrect. The factorization can change optimization
behavior without making it a nonlinear memory model. See the unchanged
[V10 implementation](../memory-cell-v10/cells.py) and the independent
[diagnostic implementation](diagnostics.py).

The diagnostic retains 384-dimensional cached features and the V10 grouped
objectives: the semantic value contains three four-bit integers, and the
procedure value contains four seven-way categorical positions. Exact recall
requires every component of the stored value to be correct.

## 1. Feature geometry

SVD is computed in float64. The numerical rank threshold is
`largest_singular_value × max(matrix.shape) × float64_epsilon`.
`X` has shape `N × 384`; the affine design `[X, 1]` has shape `N × 385`.
The table reports row rank and the ratio of largest to smallest singular
value. Complete singular-value vectors and tolerance values are retained in
the JSON results.

| Type | Addresses | Raw X rank | Raw condition | With-bias rank | With-bias condition | Centered rank | Centered condition |
|---|---:|---:|---:|---:|---:|---:|---|
| Semantic | 32 | 32 | 68.2100 | 32 | 110.4296 | 31 | Rank deficient (`null`) |
| Semantic | 64 | 64 | 138.7277 | 64 | 223.7801 | 63 | Rank deficient (`null`) |
| Semantic | 128 | 128 | 348.9904 | 128 | 567.3654 | 127 | Rank deficient (`null`) |
| Procedure | 32 | 32 | 77.6879 | 32 | 120.7280 | 31 | Rank deficient (`null`) |
| Procedure | 64 | 64 | 157.4268 | 64 | 245.6636 | 63 | Rank deficient (`null`) |
| Procedure | 128 | 128 | 396.8316 | 128 | 621.8037 | 127 | Rank deficient (`null`) |

Every raw and with-bias matrix has full row rank and zero duplicate rows.
Centering makes the rows sum to zero, so the observed rank `N - 1` is
expected; its nonfinite full-row condition is represented by JSON `null`.
It is not evidence of duplicate canonical addresses.

The with-bias singular-value ranges are:

| Type | Addresses | Largest singular value | Smallest singular value |
|---|---:|---:|---:|
| Semantic | 32 | 7.1900453 | 0.06510976 |
| Semantic | 64 | 10.1435521 | 0.04532821 |
| Semantic | 128 | 14.3431310 | 0.02528024 |
| Procedure | 32 | 7.3881407 | 0.06119658 |
| Procedure | 64 | 10.4183467 | 0.04240899 |
| Procedure | 128 | 14.6768983 | 0.02360375 |

The matrices become less well conditioned as this particular corpus grows.
That observation can motivate an optimization diagnosis, but condition
numbers alone do not identify the causal share of conditioning, objective,
parameterization, learning rate, or sample exposure.

## 2. Independent affine positive control

The control solves the affine least-squares system with float64 SVD and
signed target margins of `±8`. This supplies a direct existence witness for
these finite mappings. Ridge controls use the same system and regularize
the bias as well as the weights. Their penalties were `0`, `1e-6`, `1e-4`,
and `1e-2`; no penalty was selected using held accuracy.

| Type | Addresses | Pseudoinverse canonical exact | FP32 weight representation exact | Pseudoinverse parameter L2 norm | Direct old held wording exact |
|---|---:|---:|---:|---:|---:|
| Semantic | 32 | 32/32 | 32/32 | 1,228.8742 | 0/64 |
| Semantic | 64 | 64/64 | 64/64 | 2,464.4989 | 0/128 |
| Semantic | 128 | 128/128 | 128/128 | 5,006.9674 | 0/256 |
| Procedure | 32 | 32/32 | 32/32 | 1,201.1047 | 4/64 |
| Procedure | 64 | 64/64 | 64/64 | 2,331.3967 | 3/128 |
| Procedure | 128 | 128/128 | 128/128 | 4,878.0513 | 0/256 |

Both small nonzero ridge penalties also give 100% canonical exact recall
in all six cases. The larger `1e-2` penalty gives semantic exact recall
`32/32`, `55/64`, `70/128`, and procedure exact recall `32/32`, `64/64`,
`115/128`. The lower-scoring controls remain in the evidence.

**Precision boundary.** The arm named `pinv-float32-storage` casts the
solved weights to float32 and evaluates them with the independent V10
reference, which promotes values to float64 for computation. It tests
whether representing these coefficients in FP32 loses the classification
solution. It is not a new experiment in all-FP32 arithmetic or a separately
serialized-and-reloaded pseudoinverse checkpoint. The trained budget arms
do retain their actual `.npz` parameter files.

**Large-weight boundary.** The pseudoinverse coefficients are large. For
comparison, the original seed-1741 residual checkpoints at 128 addresses
have stored-parameter L2 norms 48.2039 for semantic and 61.1269 for
procedure. These norms belong to different parameterizations, so their
ratio is not a comparable function-complexity metric. Nevertheless, the
absolute affine coefficient norms and the direct-wording failures rule out
presenting interpolation as demonstrated robust recall. No perturbation,
finite-precision margin, or out-of-distribution stability guarantee is
established.

The diagnostic explicitly separates three accesses:

- **Canonical storage:** feed the feature of the exact canonical address.
- **Worded query with oracle address:** supply the correct canonical
  address externally, then feed that address's canonical feature. Each old
  held address appears twice, so its exact accuracy equals canonical
  accuracy by construction.
- **Worded query without oracle:** feed the actual held wording's cached
  feature. This evaluates a different input vector and does not receive
  the externally correct address.

Thus the pseudoinverse's 100% oracle score demonstrates neither a learned
router nor successful end-to-end access. Semantic direct recall remains
zero in every tested capacity despite exact canonical interpolation.

## 3. Training budget controls

All arms use the V10 float32 Adam equations, learning rate `0.01`, betas
`0.9/0.999`, epsilon `1e-8`, and batch size 32. Initial weights and schedule
prefixes are shared across budget choices within a model/capacity case.
Optimizer moments persist through convergence checks. The three budgets
are:

| Budget | Steps at 32 / 64 / 128 addresses | Sample presentations | Average presentations per address |
|---|---|---|---|
| Fixed total | 1,200 / 1,200 / 1,200 | 38,400 each | 1,200 / 600 / 300 |
| Fixed per-address | 1,200 / 2,400 / 4,800 | 38,400 / 76,800 / 153,600 | 1,200 each |
| Loss threshold with maximum | Up to 12,000 each | Up to 384,000 each | Depends on stopping and capacity |

The third budget checks full training loss every 100 steps, plus the first
and final steps. It stops only at loss `≤ 0.001`; otherwise it ends at the
12,000-step maximum with `converged=false`. No old held result chooses a
budget, stopping point, or learning rate. The word `convergence` in an arm
name is a budget policy, **not** a statement that the run converged.

Only one original initialization is diagnosed per type: semantic seed
1741 and procedure seed 1742. Procedure uses the original seed 1741 plus
the type offset of one; `--legacy-seed 1741` identifies its archived
checkpoint directory. These are not replications of V10's three-seed
aggregate and should not replace that aggregate in a report.

### Semantic exact canonical recall

| Addresses | Model | 1,200 steps | Fixed per-address | Loss-threshold arm exact | Actual steps | Final full loss | Reached loss threshold? |
|---|---|---:|---:|---:|---:|---:|---|
| 32 | Linear | 13/32 | 13/32 | 32/32 | 12,000 | 0.00712851 | **No; maximum budget** |
| 32 | Rank-4 residual | 32/32 | 32/32 | 32/32 | 6,500 | 0.00098738 | Yes |
| 64 | Linear | 3/64 | 13/64 | 63/64 | 12,000 | 0.11442490 | **No; maximum budget** |
| 64 | Rank-4 residual | 21/64 | 20/64 | 46/64 | 12,000 | 0.07274733 | **No; maximum budget** |
| 128 | Linear | 1/128 | 15/128 | 47/128 | 12,000 | 0.30848672 | **No; maximum budget** |
| 128 | Rank-4 residual | 14/128 | 36/128 | 63/128 | 12,000 | 0.16632454 | **No; maximum budget** |

### Procedure exact canonical recall

| Addresses | Model | 1,200 steps | Fixed per-address | Loss-threshold arm exact | Actual steps | Final full loss | Reached loss threshold? |
|---|---|---:|---:|---:|---:|---:|---|
| 32 | Linear | 32/32 | 32/32 | 32/32 | 10,400 | 0.00097517 | Yes |
| 32 | Rank-4 residual | 32/32 | 32/32 | 32/32 | 1,300 | 0.00094318 | Yes |
| 64 | Linear | 35/64 | 59/64 | 64/64 | 12,000 | 0.01185053 | **No; maximum budget** |
| 64 | Rank-4 residual | 27/64 | 64/64 | 64/64 | 3,900 | 0.00096730 | Yes |
| 128 | Linear | 29/128 | 88/128 | 125/128 | 12,000 | 0.17779731 | **No; maximum budget** |
| 128 | Rank-4 residual | 73/128 | 128/128 | 128/128 | 12,000 | 0.01530763 | **No; maximum budget** |

Eight of twelve loss-threshold runs exhaust the maximum without satisfying
the criterion. In particular, 100% exact classification can coexist with
loss above `0.001`. The extra steps often help canonical recall, but do not
monotonically help every arm: semantic residual at 64 addresses changes
from `21/64` to `20/64` under the fixed-per-address increase. Neither
unlimited-budget convergence nor its cost was measured.

### Direct old held wording after the loss-threshold arm

| Type | Addresses | Linear direct exact | Residual direct exact |
|---|---:|---:|---:|
| Semantic | 32 | 0/64 | 0/64 |
| Semantic | 64 | 0/128 | 0/128 |
| Semantic | 128 | 1/256 | 0/256 |
| Procedure | 32 | 9/64 | 1/64 |
| Procedure | 64 | 5/128 | 2/128 |
| Procedure | 128 | 1/256 | 2/256 |

The oracle-addressed accuracy remains the canonical accuracy, whereas
direct access remains poor even in cases with perfect canonical storage.
All predictions, including fixed-budget wording predictions, are retained
in the JSON. These exact-recall metrics do not evaluate a new calibrated
abstention policy or unknown-request safety.

## 4. Conclusions that the evidence supports

**Representation:** for these six finite canonical matrices, an affine
solution exists and retains exact classifications when its coefficients
are represented in FP32. The observed Adam failures are not proof that
those particular mappings cannot be expressed.

**Optimization:** a fixed 1,200-step run reduces average exposure per
address as capacity grows. Increasing exposure improves many canonical
results, and eight maximum-budget runs still miss the stated loss
criterion. This identifies a concrete training-budget confound. It does
not isolate a unique optimization cause or promise an efficient solver
for larger or continually changing memories.

**Addressing and wording:** correct canonical storage is insufficient for
recall from a different embedding. Oracle access hides this requirement.
The direct-wording results remain a substantial failure.

**Capacity and system design:** row rank on at most 128 addresses is not a
measurement of an arbitrary-fact capacity law, a bits-per-parameter
compression rate, a sustainable update rate, or a general memory system.
No split/merge benefit, deletion guarantee, continual-learning benefit,
or network emergence follows from these controls. Full-rank interpolation
also does not rescue V10's original deployment gates. The result motivates
separating storage optimization from access and evaluating new model
families under fresh frozen protocols; it neither validates nor rules out
those model families.

## 5. Original input verification and source identity

The original [V10 transport](../memory-cell-v10-results/formal-01/TRANSPORT.json)
was restored using its checked-in verifier. It verified 2,215 files and
153,096,915 uncompressed bytes. Integrity anchors are:

| Item | SHA-256 or commit |
|---|---|
| Original 35,255,252-byte archive | `dd24d42dd46f1a980c58da6530d6164e9b547fbab4a10de2c2e21f3d26c43d3c` |
| Original raw-file manifest | `4f53318f1bf83670cee8fe4e306debc513604a8777da11baab0922c279f45a0e` |
| Original formal source commit | `dd727713ad8074a74f88b5782b2a86f26a1cc30b` |
| Original formal source manifest | `38559a7e81e22b6742febb4fdca9b52e567495cb0233eabd28aae9979c6c24b7` |
| Diagnostic executed source | `4608c77875f0b1eea35e95d1396b6f52a7bebe051c37ef52841a12833d3d9a82` |

Each diagnostic directory retains `SOURCE_IDENTITY.json`,
`LEGACY_SOURCE_PARITY.json`, and `diagnostics.executed.py`. Its identity
capture explicitly says **after execution, before any diagnostic source
edits**. This is an honest executed-source record, not a claim that WP1
was prospectively frozen as a new confirmatory study. The report itself
was authored after inspection of the results. V11 content's separate
pre-training freeze must not be attributed to this retrospective study.

All four imported V10 files matched their original formal source hashes:

| V10 dependency | SHA-256 |
|---|---|
| `cells.py` | `a75e4dfcd5fe817bb5d95eb4262ce11be9e6c10176c92d13b9b4f83e4559eb52` |
| `corpus.py` | `0e62f77e4794ecf0d3cf33dd29553adbec5ed86e90c8e82ca34ae3e173cbe21e` |
| `reference.py` | `0a6a13949da5cc5ff2ddb25b5afd2626c33fb529ba5969a6f81a4f71293374a8` |
| `export_native.py` | `bd11eaff59673888f644184115635adba34c9470d51ca356bc34c584cfa22241` |

The actual cached inputs under `data/capacity-N/` have the following
SHA-256 values. These establish which original encoder outputs were
diagnosed; the new FP32 Torch encoder was not substituted.

| Capacity | File | SHA-256 |
|---:|---|---|
| 32 | `sources.json` | `0ea19b4b10097f50d37e73e4b14f4768e0e028435fa345bd1823d00601b278f9` |
| 32 | `canonical.npz` | `343fc8e2ca7f16441b667559cbb98c6987d4d4c897688f8f685fb43c7f559773` |
| 32 | `held-queries.json` | `a613dde2fa9bff51132e8994c63a589088fa4ec3b160031570538eb85fa7f05c` |
| 32 | `held-features.npz` | `0ab190e04db4b53df4c204786c0dd1955a9b3be41a8f5938e51f2c37facca096` |
| 64 | `sources.json` | `e5c7fd604766fd7dd58f402a96b375f9ccbcac593de033b846b311c4142493a1` |
| 64 | `canonical.npz` | `dcc8012bb7b8abe0794e7f826882d9db8312ab44505c827d7ce44916f37c2760` |
| 64 | `held-queries.json` | `a71c68189ac176b48f2e226e6b5645707f2374aae416863a80020617dac8818c` |
| 64 | `held-features.npz` | `7b6546c7a8aae24510e227166da6a11f61c207f3faccb6c631881c07a17dd71d` |
| 128 | `sources.json` | `88e787d452fac786f4078e6dab967580fac4c9b5fe0e7cfc76bc8eec85e6055d` |
| 128 | `canonical.npz` | `e5267fab449fbf566c99f69c18a03b771fe88592ecf4ff06083a4d6fc694ebb7` |
| 128 | `held-queries.json` | `e64056d93834ca11417b877eea307dff02055bfabbb6464a6a3ba60a6d9b527b` |
| 128 | `held-features.npz` | `39eaa8b4eceff522788bbf484fc41d82982fbe6523a5318ed40de1d30e79e0e8` |

## 6. Reproduction commands

Run from the repository root. The original runtime used Python 3.12 and
NumPy 2.3.5. This diagnostic operates on cached NumPy features and does not
download or execute a new encoder. Output directories must not already
exist. The commands below name new output directories to preserve the
archived run.

First restore and verify the original V10 inputs:

```bash
/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python \
  qualification/memory-cell-v10-results/formal-01/restore.py \
  --output /workspace/scratch/fa15dc544533/v10-diagnostic-input-rerun
```

Then execute the geometry and both budget studies:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python \
  qualification/memory-cell-v11/diagnostics.py \
  --data /workspace/scratch/fa15dc544533/v10-diagnostic-input-rerun \
  --output /workspace/scratch/fa15dc544533/v11-diagnosis-geometry-rerun \
  --skip-training

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python \
  qualification/memory-cell-v11/diagnostics.py \
  --data /workspace/scratch/fa15dc544533/v10-diagnostic-input-rerun \
  --output /workspace/scratch/fa15dc544533/v11-diagnosis-budget-rerun \
  --kinds semantic --seed 1741 --max-steps 12000

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python \
  qualification/memory-cell-v11/diagnostics.py \
  --data /workspace/scratch/fa15dc544533/v10-diagnostic-input-rerun \
  --output /workspace/scratch/fa15dc544533/v11-diagnosis-procedure-budget-rerun \
  --kinds procedure --seed 1742 --legacy-seed 1741 --max-steps 12000
```

The original invocation used the same flags with input directory
`v10-formal-restored` and output directory names without `-rerun`.
Preserved parameter identities, schedule hashes, training-loss traces,
predictions, CPU seconds, and wall seconds are available for comparison.
Exact wall time is environment-dependent and is not a latency superiority
claim. No new experiment or test was run to author this report.

To restore the already executed WP1 evidence without retraining:

```bash
python qualification/memory-cell-v11/evidence/restore.py \
  --package qualification/memory-cell-v11/evidence/archives/wp1-model-development \
  --output /workspace/scratch/fa15dc544533/wp1-evidence-rerestored
```
