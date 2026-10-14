# E4 frame-byte temporal counterfactual verification (shadow)

**Research only / DENY_ALL.** A pair whose advertised order digests differ is not proof that its frames are reversals. The existing E1–E5 reviewer checks the *declared* digest pairing; this independent module actually reads staged frame files and compares their SHA-256 byte identities in exact reverse order.

Usage:

```sh
python experiments/shared_stem_cell/e4_frame_reversal_gate.py \
  --manifest /approved/frame-order-pairs.json \
  --frames-root /approved/extracted-frames \
  --output /sealed/frame-order-audit.json
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e4_frame_reversal_gate.py' -v
```

Input schema `hepta.e4-frame-order-pairs.v1`. The panel binds a stable Scope, plan/source/temporal-Head/preprocessor SHA-256, and `pairs`. Each pair has an original video SHA *claim*, group, split, monotone observation time, question digest, the forward and reversed ordered lists of relative image frame paths and expected per-frame SHA-256 values, opposite binary labels, plus predictions from order-invariant, frozen temporal and learned temporal controls. All model predictions are **claimed** sealed before labels, not independently timestamped.

The verifier reads each bounded frame through the approved local root; it rejects path traversal and symlinks, missing or oversized files, altered raw frame bytes, changed/missing/duplicate frames, same-order impostors, non-opposite labels, duplicate source groups and task pairs, illegal Scope, changed order-invariant control output, malformed/nonfinite probabilities and false production authority.

Reports paired two-direction accuracy for every arm, separately by test/future1/future2/future3. However: it **does not** decode original video, authenticate the original movie or its frame sampling, independently verify model inference, externally verify ground-truth labels, establish correct temporal reasoning or NDU, or grant FinalUse. It cannot be run against the present public audio failure artifact to manufacture task successes.

Current local mechanism evidence: 15 synthetic/adversarial cases passed, using byte-identical pushed source blobs: `e4_frame_reversal_gate.py` `9286652e69561b5e70ddfa1ba8d0eee1b0f53855`; `test_e4_frame_reversal_gate.py` `f0eddf13e724c7e71fb02f754ce938fb6579600d`. Hosted exact-head CI is separate.

Physical acceptance still requires real, published time-stamped video frame materialization, genuinely unseen event reversals, actual Whisper/audio and temporal Encoder forwards with matched content-only baselines, independently sealed future outcomes, observed target-host latency/CPU/GPU/RSS/energy and independent NDU. All promotion remains forbidden.
