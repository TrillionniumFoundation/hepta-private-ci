# Frozen features: encode once, replay Head learning without a model

`execution.run` may explicitly set `export_frozen_features: true` (default false).
The public AG News smoke opts in. After verifying its source at the existing
publication boundary, it writes the actual masked-mean float32 feature matrix
and a create-only manifest, then checks an exact reopen. No labels or raw text
are embedded in this archive. Ordered row IDs, scope, fold, Cell, input digests,
producer plan/source, complete model/tokenizer snapshot identity and the existing
feature profile are bound. A report digest supplied OUTSIDE the archive is the
replay trust root; hashes do not attest correct encoding or independent review.
Features remain derived source data, not anonymized information. Non-public
exports must stay within their existing authorized scope and retention controls.
This is an opt-in offline research artifact, not a product cache, store or CAS.

`feature_replay.py` checks that binding and <=64 MiB of tensor payload before
repeating the existing four Head fits on owned Torch storage. It requires the
original separately hashed dataset and training manifest, but no pretrained
weights/tokenizer. Training APIs still receive train labels only. Both scalar
and grouped training use the original configuration, preserve caller RNG, seal
predictions before evaluation, and compare with the original producer predictions
and exact minibatch hashes. No controls or generators are rerun or relabeled.
A mismatching replay retains its predictions and diagnostics and fails; it never
repairs scores, promotes a candidate or reports a new independent task result.

```sh
python -m experiments.shared_stem_cell.feature_replay \
  --manifest /staged/manifest.json --producer /staged/producer \
  --report-sha256 <externally-verified-producer-report-sha256> \
  --backend grouped --output /new/replay-result
```

The existing public-pretrained CI lane copies only this small replay input into a
new directory (NO model/tokenizer files), then executes scalar and grouped replay
in fresh processes. Archive creation/reopen, Head fitting and original encoding
have separate costs. Avoiding a repeat Encoder call is not an end-to-end latency,
energy or memory improvement claim. Tolerances are the existing grouped-learning
`atol=2e-5, rtol=2e-4`; argmax changes and sampling drift are separately fatal.
This first profile supports the existing 2D text feature matrix, not CLIP
candidate tensors, token-level media, optimizer checkpoint resume or production
FinalUse. Replaying an already evaluated dataset is reproducibility evidence,
not a new holdout or a permit to tune against its labels.
