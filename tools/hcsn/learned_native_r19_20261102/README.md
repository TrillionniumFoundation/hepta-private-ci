# Actual learned-checkpoint native forward qualification

This stage ports all sixteen original R19 analytic checkpoints, without further training. The state is the learned latent intervention/emission model, not the physical-owner Bayes posterior. The native program evaluates gammaQ propagation, phase prior, symbol WRITE/READ maps, and the actual FP32 40→32 tanh→4 content head plus endpoint READ control.

Immutable symbol operations are compiled into exact original FP32 probability constants, alongside rawW. The worker independently verifies every exported field against the pinned original checkpoint at original dtype; Rust separately recomputes both rawW softmax axes and rejects discrepancy beyond2e-7. This removes a CPUlibm rounding difference without changing the learned model. No owner states, answers or action tables enter exported profiles. Runtime weight mutation is outside this profile.

The original state5e-9/logits1e-5/probabilities2e-6 contract remains fixed; every action and answer must agree. All five hypothetical/current head gaps must exceed2e-5; value decision margins must exceed5e-5. Near ties abort the whole campaign without substitution. These margins accompany finite empirical validation, not a machine-checked universal error certificate.

Five development worlds across all16models pass768query comparisons. A pre-freeze rawsoftmax failure remains in development_02. NaN threshold, FP32 cast overflow, exact head tie and near action tie are rejected; an invalid unpurchased response cannot influence STOP. The valid light family includes finite threshold−1.

Formal evaluation uses20fresh known-law tapes and3072model-query comparisons. It starts only after all source and actual exported bytes are remotely published and bound by PUBLICATION.json. Reference/parity inputs never contain target labels or owner paths. No same-model pending/lease, GPU, energy or production adoption is claimed by this pure-forward stage; the owned-runtime adapter is separate.

Run from the repository root, with Rust1.95toolchain on PATH and PYTHONPATH=/tmp/hcsn-torch-runtime:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.learned_native_r19_20261102.driver \
  --output tools/hcsn/learned_native_r19_20261102/run_01
```

Review stages are native core/exported immutable parameters, parity protocol/driver, then the separately frozen owned-runtime adapter. No frozen learning candidate or native02 source is modified.
