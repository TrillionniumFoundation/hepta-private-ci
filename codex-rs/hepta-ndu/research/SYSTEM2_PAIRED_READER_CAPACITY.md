# Pairing the same source-bound Reader questions, without new inference

This is research-only on the existing draft PR #1546. It compares *actual*
completed 135M and 0.5B frozen Reader outputs for the same forty synthetic
questions. The first twenty were previously exposed, while the fixed next
twenty were held out from prompt selection but share the synthetic task family.
There is no new training, inference, online oracle, production switch, Encoder,
NDU, Riccati or FBSDE integration in this audit.

## Immutable parents

- Original frozen 135M labeled/unlabeled runs: completed source 24a11759,
  artifact 11760345185, SHA256 `a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a`.
  The provenance includes 140 complete original answers and a raw SHA seal.
- Its separately pinned parent cardinality run: artifact 11756357532, SHA256
  `9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121`.
- 0.5B Qwen2.5-Instruct model: source dcd799fe, artifact 11768355664,
  ZIP SHA256 `853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37`,
  raw 160-answer SHA256 `de6d403fcf357000e07f9b235b1699ed85718e3954faf167b9fbb895a1e5405f`.
  Model revision a338b55dd21219a5f4da42bc11a9313d1a27d4cc.
- Original 135M's newly completed SAME next twenty tasks: generating commit
  f6139d7b78b45add91caa491dc523ac8527fa633, artifact 11770341844,
  ZIP SHA256 `aaa8d1ee112ae8ad903834d0384f5de94cf19197d36e9ea4b6fce99d485715f0`,
  new eighty raw answers SHA256 `6b7cc60f0feb0fd2d8843db1ccb74a6453cefacd6df14de6764f93fffc6689ce`.
  This authentic continuation reused exactly eighty old prompts, verified
  their input-token digests and generated tokens, and generated only eighty
  new answers; no old model work was repurchased.

All external ZIP digests, inner SHA256SUMS, generating source hashes, raw
seals, cohorts, arms, Reader identities and unchanged source excerpts are
validated before any score is published. Internal EvidenceBundle seal differs
between historic 135M and 0.5B because **the original experiment mode differs**
(answer-only:<arm> vs <arm>); each is checked against its own original mode.
Byte-identical delivered evidence and the question identity are required.

## Actual outcome, not a new model improvement

Across 40 tasks × four shared conditions, the larger 0.5B Reader answered
**zero of the 80 fully supported facts**, including all forty direct one-fact
questions, and overrefused or echoed when facts were actually supplied. For
forty irrelevant-fact and forty empty-evidence conditions it refused correctly.
Thus its combined strict success was **80/160**, all in negative controls.

The historical 135M Reader's original 80 responses plus its now-completed
new eighty responses also yielded **zero grounded answers and zero correct
refusals across 160 conditions**; its errors were mostly label lists and JSON
continuation. The 0.5B improves appropriate abstention, **not grounded answer
yield**. The forty tasks belong to a correlated generated domain; neither
model has passed a natural task or semantic citation verification threshold.
Both original experiment-mode bundle seals were validated separately against
the exact same selected source excerpts and question IDs.

**Not compute matched:** models differ by parameters (135M vs 494M), tokenizer,
encoded token count and generator time. Repeated arms share the 20 synthetic
subjects. Claims of independent natural-language transfer, learned NDU/FBSDE
value, production fitness, or speed superiority are explicitly excluded.

## Reproduce with exact read-only sources

Run `system2_reader_paired_capacity_audit.py` with positional arguments:
0.5B ZIP, cardinality ZIP, label ZIP, new20 135M ZIP, and a fresh output JSON path. Set
`HEPTA_MEMORY_TESTED_COMMIT` to exact checkout SHA. No model weights are
needed. The isolated workflow pins all four artifacts and executes all
original MemoryCell regression tests and scoped Ruff F/E9 checks before
writing the audit receipt and SHA256 manifest.
