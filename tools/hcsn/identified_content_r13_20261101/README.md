# Hepta identified content R13

R13 is a completed, frozen research experiment on a two-parameter financial cell, smooth regenerative propagation, actual text observations and prepared native execution. It continues R12 without replacing its failed outcomes.

**Decision:** Both registered noninferiority and unique deployment-cost gates pass. Neither quality-gain gate passes. The analytic cell and a generic HMM with the same model take identical actions and receive identical utility. No production default is activated.

## Start here

- [Full Chinese report](REPORT_ZH.md)
- [Blocker dispositions](BLOCKERS_ZH.md)
- [Machine-readable acceptance](ACCEPTANCE.json)
- [Registered protocol](PROTOCOL.json) and [implementation scope](IMPLEMENTATION.md)
- [Confirmation summary](evidence/SUMMARY.json)
- [Continuous propagation and certificate limits](propagation/REPORT_ZH.md)
- [Compensated arithmetic, failures and costs](precision/NUMERICS_ZH.md)
- [Local parameter/gradient verification](verification/VERIFICATION_ZH.md)
- [Native execution evidence](native/NATIVE_ZH.md)

PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4545

Protocol commit: `168ed5ea20c98a9f313d2e1b5b41bd26d284c958`.
All 24 fits/data/runtime committed before confirmation: `37911e4eb7e5376e84d7f770656d47a4a364d40a`.

## Scope

Real public SMS text is acquired and encoded only at an actual READ. The latent time evolution, recovery and content retention are controlled by a finite CTMC. The corpus is not a natural chronological task. The frontend is trained first and then frozen; this does not demonstrate joint gradient training through discrete text bins.

Maturity is fixed and sigma/liquidity are learned. Five local checks establish rank two for their map into Q; full-posterior supervision and softmax gauge freedoms are disclosed. This is not a global observational-identifiability theorem.

The same 116-state Q drives Torch training, the common value controller, prepared Rust inference and native event/checkpoint execution. Its finite semantics are explicit. Continuous-domain, spatial, conditional-observation, payoff, model and machine-arithmetic errors have distinct evidence requirements.

The actual native default benchmark improves greatly over R12's uncached per-row path, while remaining slower than legal cached NumPy. Double-single arithmetic uses two f32 components per real (64-bit payload) and is currently much slower than mixed64. Neither result is a GPU claim.

## Restore and verify evidence

The raw data, all fits, per-example outcomes, development failures and operator evidence are stored in deterministic archives. Large archives and exact tested Linux binaries have small numbered parts. The manifests bind every member and part with SHA256.

The repository limits each Git blob to 512,000 bytes. Nine archives were repartitioned into 480,000-byte volumes after the first remote check; their complete compressed payloads, member hashes and pre-confirmation history are unchanged. See [the delivery record](delivery_ci/REPARTITION.json). This packaging correction does not change the registered experiment or its failed gates.

From this directory, with Python available:

```bash
python restore_artifacts.py
python restore_artifacts.py --verify-only
```

Restoration refuses to overwrite different existing bytes. It verifies the exact native library and event executable used for confirmation. These are Linux x86_64 artifacts; other platforms must build and verify their own native artifact identity.

With the recorded scientific Python dependencies installed:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python -c 'from evaluation import validate_freeze; from contract import ROOT; validate_freeze(ROOT / "evidence"); print("Frozen runtime, weights and library verified")'
```

Recorded environment: Python3.12.14, NumPy2.3.5, SciPy1.17.0, Torch2.10.0+cpu, mpmath1.3.0, scikit-learn1.8.0; standalone native build used rustc1.95.0. Full build receipts are archived. Re-running fits or confirmation requires a new output directory and a new execution/freeze record; original outcomes are append-only.

## Reviewable delivery stages

1. Preregister protocol and data identity.
2. Add shared text frontend and the full financial two-parameter contract.
3. Add stronger ordinary cores, causal acquisition and stable control.
4. Measure full child-process fit costs and freeze every weight.
5. Add smooth positive propagation and bounded prepared native execution.
6. Add explicit event/observation checkpoint contracts and model migration.
7. Execute independent continuous, numerical, statistical and runtime checks.
8. Publish fresh confirmation, negative findings, complete evidence and admission decisions.

## Dataset attribution

Tiago A. Almeida and José María Gómez Hidalgo, SMS Spam Collection (2011), UCI Machine Learning Repository, DOI10.24432/C5CC84. The official UCI distribution is licensed CC BY4.0. Metadata: https://archive.ics.uci.edu/dataset/228/sms+spam+collection .

The original archive is preserved; normalized identities, deduplication, hash partitions and the trained shared encoder are derived artifacts. No authors' endorsement is implied. See [data attribution](DATA_ATTRIBUTION.md).
