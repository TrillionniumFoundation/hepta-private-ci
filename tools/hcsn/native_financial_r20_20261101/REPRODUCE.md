# Reproduction

Use Python 3.12 with NumPy, SciPy and mpmath, and Rust 1.95.0. The recorded local dependency selector was `PYTHONPATH=/tmp/hcsn-mpmath`; an ordinary installed mpmath is equivalent dependency setup. The absolute rustc selector in verify.py records the actual toolchain; changing a local selector requires preserving that separate execution identity.

From the repository root, use a fresh destination:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.native_financial_r20_20261101.verify --output /tmp/native-financial-replay --namespace 202011017
```

The verifier uses actual compiled Rust for every parameter tuple and CDF argument. Reference matrices are never candidate inputs. Reusing the recorded namespace is an engineering replay, not new independent confirmation. Use `--formal` only with the original published source receipt and protocol. Original raw arrays are deterministic gzip and their uncompressed identity is recorded in SUMMARY.json.

The numerical module is also importable by the R20 live owner. There the compact financial model file contains only the schema and three physical parameters; no Q, E, prior or successor states are supplied to that model constructor. Qualification of that actual persistent composition has its own source freeze and crash campaign.
