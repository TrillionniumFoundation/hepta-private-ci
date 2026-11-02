# R19 native finite-Q numerical owner

The Rust owner computes its own forty-state transition, Bayes posterior, public
WRITE and three-slot value controller. Its inputs are public model arrays and
legal completed observations from a separate private provider. Python future
states, actions and scoring targets are never passed to the Rust actor.

Read [REPORT_ZH.md](REPORT_ZH.md), [METRICS.json](METRICS.json),
[BLOCKERS.json](BLOCKERS.json), [BUILD_IDENTITY.json](BUILD_IDENTITY.json), and the
independent audit. The registered profile passed 80 cases, 56 operator checks
and 16 actual pending cold recoveries. This is finite implementation parity,
not trained-head or complete Hepta production qualification.

## Reproduce with a new output directory

Use Rust 1.95.0 and Python/NumPy/SciPy versions in ENVIRONMENT.json. Build command
and binary identity are preserved; no compiled binary is delivered.

```sh
rustc --edition=2024 -C opt-level=2 -D warnings \
  tools/hcsn/native_numeric_r19_20261102/main.rs -o /tmp/hcsn-r19-new-owner
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.native_numeric_r19_20261102.campaign \
  --binary /tmp/hcsn-r19-new-owner \
  --manifest tools/hcsn/native_numeric_r19_20261102/SOURCE_MANIFEST_V2.json \
  --protocol tools/hcsn/native_numeric_r19_20261102/PROTOCOL_V2.json \
  --publication tools/hcsn/native_numeric_r19_20261102/PUBLICATION_V2.json \
  --output /tmp/hcsn-r19-new-results
python -m tools.hcsn.native_numeric_r19_20261102.audit \
  /tmp/hcsn-r19-new-results --output /tmp/hcsn-r19-new-audit.json
```

Reusing the published namespace is reproducibility replay, not a fresh
confirmation. A changed algorithm/task/threshold or new confirmation needs its
own source publication, readback and untouched namespace before world access.
The runner enforces a matching publication receipt before constructing worlds.
The early incomplete run01 violated the required order and remains excluded;
see PROVENANCE_EXCLUSION.json. The new run02 used namespace 19063 after verified
source commit 13a8c2596a4c1955619d352b02f6ce0113849f0f.

`reference_fallback.py` returns separately labeled dense SciPy action/answer
proposals from only public model and owned state. Native action or answer gaps
at most 1e-7 fail closed; fallback never turns a failed native case into a pass.
All ordinary argmax ties use the original strict comparison priority.

## Numerical and ownership scope

Uniformization preserves reachable support with a minimum order and an
entry-relative Poisson remainder; unsupported underflow profiles are rejected.
Probability and repeated-event reward bounds are tracked separately. Roundoff
allowances are conditional FP64 engineering bounds, not machine-checked interval
certificates. The public model header is metadata; owned-state context also
binds actual serialized model bytes. FNV64 covers accidental context changes in
trusted host files; it does not authenticate hostile writers. Delivery and
source identities use SHA256.

Both full and anchored timing modes persist four forty-state vectors. This
implementation does not inherit R16's packed-eight-mass storage advantage.
Private provider targets remain scorer-only. Learned symbol/head/gamma model
integration is a separate source/profile and cannot borrow this plain posterior
argmax qualification.

Complete excluded and qualified raw records, per-file hashes, ASCII transport
parts and restoration instructions are in
[delivery_small/README.md](delivery_small/README.md).
