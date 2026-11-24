# Cell FastPath ActionIR P3: Rust Neuron receipt adapter (shadow only)

P3 adapts a previously verified `codex-rs/hepta-infer-core` Rust
`NeuronFeatureReceiptV1` into the P2 owner-evidence projection. It preserves the
opaque Rust source receipt digest and source commit digest; it does not attempt
to reimplement the Rust canonical byte-digest algorithm.

The adapter binds request/input/runtime/encoder/head/output identities, terminal
status, Q24 vector digests and observed memory/transient/queue/latency fields.
It requires `source_verified=true`, rejects request/input drift and rejects
failed, cancelled and indeterminate receipts before projection. It never runs
a model, calls Guardian, claims TaskFlow, calls Agentd, dispatches a provider,
or admits an effect.

Every result is `authority=DENY_ALL` and `effect_admitted=false`. An `ADAPTED`
result means only that a source-verified Rust receipt was projected into the
P2 shadow contract. It is not a real model efficacy or performance result.

## Validation

```bash
python -m py_compile \
  qualification/cell-fast-path-actionir-p0/cell_fast_path_actionir.py \
  qualification/cell-fast-path-actionir-p1/fast_path_shadow_qualification.py \
  qualification/cell-fast-path-actionir-p2/owner_evidence_projection.py \
  qualification/cell-fast-path-actionir-p3/rust_receipt_adapter.py

PYTHONPATH=qualification/cell-fast-path-actionir-p0:qualification/cell-fast-path-actionir-p1:qualification/cell-fast-path-actionir-p2:qualification/cell-fast-path-actionir-p3 \
  python -m unittest discover \
  -s qualification/cell-fast-path-actionir-p3 -p 'test_*.py' -v
```

The test fixtures are synthetic source-shaped receipts. Hosted qualification
must import the exact Rust source and verify an actual receipt before this
adapter can be considered evidence.
