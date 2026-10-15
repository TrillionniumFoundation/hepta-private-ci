# V9 — exact public material / real-forward-to-Cell-profile handoff (research only)

This change does **not** produce model-selection evidence. It repairs two exact
comparison defects and provides an evidence-bound bridge between the existing
V8 public pretrained weights pilot and the V5 Cell-Head research executor.

## Fail-closed repairs

- V5 previously stamped every training receipt as `attention-mask-mean` even if
  the encoder actually ran `cls-first-token`. It now records the actual pinned
  pooling and also verifies both pooling and normalization when a Head is reloaded
  for FUTURE source-only prediction. Re-sealing an inconsistent training receipt
  is not sufficient to bypass the check.
- V8 now validates sharded weight-set completeness in the pinned plan itself;
  it also checks the downloaded JSON `weight_map` uses **exactly** the declared
  safetensors shard names. Unknown/duplicate/escaping references reject before
  a model is loaded. Its previous check on Hub metadata alone was insufficient
  for a manually changed local plan or an inconsistent remote index.

## New research handoff

`public_stem_handoff_v9.py` requires the V8 immutable source plan, acquired
material receipt, and successful physical-forward receipt. It independently
rehashes **every local source file** before producing a canonical V5 text
Encoder profile. It pins the complete file inventory, original Hub commit,
source/inference receipt SHA-256, profile SHA-256, CLS-vs-Mean pooling and L2
normalization. No downloaded weight files are copied to hosted artifacts.

The original V8 canary invokes the handoff in the same job after the real
model forward. Both candidate results (and failures) remain separate. CI's
model-free job must pass the V8+V9 contract suites; physical jobs must fail
if either candidate's loading, forward, or handoff rejects.

## Evidence limits

This is a **consistency check of untrusted research evidence**, not a remote
signature verification: anyone with write access to a synthetic receipt could
manufacture claims. The original pretrained publisher has not been independently
authenticated. V5 training still requires its separate operator authorization,
and the independent no-change baseline and future-window NDU evaluation have not
been completed. No release/production authority is minted; `authority=DENY_ALL`
and `production_accepted=false` remain mandatory.

The frozen profiles are **not** automatic Cell training results, matched
head-to-head model accuracy, p95/p99, or any sort of multimodal competence.

### Local verification

```bash
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_*.py' -v
python -m py_compile \
  experiments/shared_stem_cell/public_stem_handoff_v9.py
```

Full actual pretrained execution requires the independently queued GitHub
Actions runner with networked Hub acquisition. The source checkout cannot
substitute a fake pretrained model if it lacks real weights or Transformers.
