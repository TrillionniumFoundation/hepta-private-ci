# Independent original-DINOv2 artifact audit — 2026-10-15

**DRAFT / SHADOW_ONLY / DENY_ALL.** This audit is stacked on #2146; no production model-selection or FinalUse path changes.

## Original physically executed upstream evidence

- Exact source: \`d03d91fb0894b5fb85da294a7a5b85d40c227be7\` (#2146).
- GitHub Actions run [38675401089](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38675401089), both original-source contract and pinned pretrained DINOv2 CPU forward jobs concluded success.
- Artifact ID: \`11946565744\`; ZIP SHA256 \`4466690390c7b0dfc511558a2f7f4baa23bb6c96ba7ac5d3193e0bb47b6118b3\`.
- Original \`facebook/dinov2-small\` safetensors SHA256 \`ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1\`; revision \`150c8e7bb7cef2d30ec31b13a517af14840ee3f7\`.
- Two actual original-model 384D CLS+L2 feature vectors of **synthetically drawn test PNG images**, byte-sealed features SHA256 \`c431deae451f4098ed821da462ed7101b05ee2a31dce1471a7f84adeb0d1e06e\`.

## Independent review

\`e2_original_vision_receipt_audit.py\` does not import producer inference, training, bridge or source-validation modules. It independently verifies: pinned archive SHA, exact safe two-entry ZIP, canonical duplicate-free JSON, exact producer-record schema, 384D finite normalized feature bytes, original model and case/source identity binding, matched case inventory and claimed forward count, and denied authority. It **cannot** independently attest that a forward was physically executed; physical Actions job logs and pinned weights provide separate execution evidence.

Local verifier consumed the actual ZIP, passed, and independently calculated L2 range \`0.9999999323453499\` to \`1.0000000351165865\`. All 19 standalone mutation/security cases passed under ordinary Python and \`python -O\`. They use a **synthetic archive envelope**, not another pretrained forward.

CI has two distinct stages: offline 19-case tester, then an independent on-host \`gh api\` fetch of the historical exact Actions run and artifact. The latter is time-limited by GitHub's artifact retention policy; an expired artifact fails closed and is not silently treated as a scientific failure or a passing proof.

Portable manual independent check:

\`\`\`sh
python experiments/shared_stem_cell/e2_original_vision_receipt_audit.py \
  --archive /staged/original-actions-artifact.zip \
  --archive-sha256 4466690390c7b0dfc511558a2f7f4baa23bb6c96ba7ac5d3193e0bb47b6118b3
\`\`\`

## Negative scientific claims

No natural-image semantic performance, per-Cell multimodal task success, train-only real paired Granite-image Bridge, original five-arm E2 comparison, cost-adjusted future utility, prospective three-window evidence, production inference authority or selected Stem are established by this original DINO canary or its independent archive audit. Those remain blocking, alongside \`blocking-ci\` and original durable Worker/FinalUse qualification.
