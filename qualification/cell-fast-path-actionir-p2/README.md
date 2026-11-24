# Cell FastPath ActionIR P2: owner evidence projection (shadow only)

P2 projects existing owner-side evidence into a candidate-bound, immutable
shadow receipt. It is the bridge between the typed P0/P1 candidate and the
repository's real Rust boundaries:

- `NeuronFeatureReceiptV1` request/input/runtime/encoder/head/output digests,
  terminal status, resource observations, and receipt digest;
- Guardian fast-decision evidence with authorization version, scope, freshness,
  newer failed classification, risk and threshold;
- TaskFlow observer evidence with intent/payload/fence digests and event
  sequence, while rejecting terminal-effect claims.

The pure projector never calls Guardian, TaskFlow, Agentd, a model worker, a
GPU driver, or an external provider. A successful `PROJECTED` result means only
that the exact evidence is internally consistent for shadow analysis. Every
result has `authority=DENY_ALL` and `effect_admitted=false`.

A failed, cancelled, or indeterminate Neuron receipt has no output vectors and
forces `FALLBACK`. Stale or risky Guardian evidence forces `FALLBACK`. TaskFlow
remains observation-only; Agentd/effect-owner code must construct any future
`OperationIntentV1`/`AuthorizedEffectIntent` and own final-use, revocation,
dispatch, and reconcile.

## Validation

```bash
python -m py_compile \
  qualification/cell-fast-path-actionir-p0/cell_fast_path_actionir.py \
  qualification/cell-fast-path-actionir-p1/fast_path_shadow_qualification.py \
  qualification/cell-fast-path-actionir-p2/owner_evidence_projection.py

PYTHONPATH=qualification/cell-fast-path-actionir-p0:qualification/cell-fast-path-actionir-p1:qualification/cell-fast-path-actionir-p2 \
  python -m unittest discover \
  -s qualification/cell-fast-path-actionir-p2 -p 'test_*.py' -v
```

The tests are synthetic protocol tests. They do not load a real model, prove
multimodal efficacy, approve an effect, or measure CPU/GPU latency.
