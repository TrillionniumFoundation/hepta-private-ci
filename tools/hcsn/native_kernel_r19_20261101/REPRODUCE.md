# Reproduction

Use Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and Rust 1.95.0. The verifier uses the absolute compiler path recorded in verify.py; if that path differs locally, preserve a separate source identity for the path-only change. Baseline dependency blob identities are in BASELINE_INPUTS.json; all four files exist unchanged in the pinned repository commit.

From the repository root, choose a new output directory and namespace:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.native_kernel_r19_20261101.verify /tmp/native-kernel-replay --namespace 19110471
```

The verifier compiles the actual Rust program, sends exact frozen matrices and causal observations, and compares its numeric outputs with independent SciPy matrix exponentials. A new directory is mandatory. Reusing the recorded namespace is an engineering reproduction, not new confirmation evidence.

Recover exact raw JSON with:

```sh
python -m gzip -d -c tools/hcsn/native_kernel_r19_20261101/confirmation01/RAW.json.gz > /tmp/native-kernel-raw.json
```

Its SHA256 must equal `d2b9c43e6bd4b8f0a4ed97fa708527f33a67f0617422838ffa328643a2a9fa25`. The confirmation binary SHA256, source hashes and full negative request/error records are retained. The independent closed-form probe compiles the same source with warnings denied; its separate binary identity is expected to differ because the compiler invocation differs.

This is an independently executed numeric prototype. It does not register a production provider, modify production neuron crates, enable model admission or supply a live numerical callback to the recovery prototype.
