# Pairing the same source-bound Reader questions, without new inference

This is research-only on the existing draft PR #1546. It compares *actual*
completed 135M and 0.5B frozen Reader outputs for the same twenty previously
exposed synthetic questions. The 0.5B Reader also completed twenty other
fixed synthetic questions that lack a completed matching 135M reference so far.
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

All external ZIP digests, inner SHA256SUMS, generating source hashes, raw
seals, cohorts, arms, Reader identities and unchanged source excerpts are
validated before any score is published. Internal EvidenceBundle seal differs
between historic 135M and 0.5B because **the original experiment mode differs**
(answer-only:<arm> vs <arm>); each is checked against its own original mode.
Byte-identical delivered evidence and the question identity are required.

## Actual outcome, not a new model improvement

Within 20 exposed tasks × four shared conditions, the stronger 0.5B model
answered **zero of the 40 fully supported facts**, including 20 one-fact
questions, and refused the question despite sufficient evidence. For 20
irrelevant-fact and 20 empty-evidence conditions it refused correctly, so
its combined strict success on the 80 paired conditions was 40/80. The
historical 135M label/unlabeled Reader achieved zero successes on all 80
conditions; its failure mode was usually JSON continuation / evidence echo.
Thus the 0.5B model improves negative-control refusals, NOT positive grounded
answer yield. Do not summarize the 40/80 combined number as actual ability
to answer evidence-supported questions.

On the additional 20 fixed new 0.5B questions, the same pattern recurred:
zero exact fact answers, full correct refusal on the 40 negative conditions.
The old 135M model has NOT been evaluated on those 20 new questions yet.
The separately submitted matching 135M study was blocked before its new
80 calls by a history-row `bundle_digest` field mismatch; that check has
now been repaired using the authentic receipt schema and preserved SHA guards.

**Not compute matched:** models differ by parameters (135M vs 494M), tokenizer,
encoded token count and generator time. Repeated arms share the 20 synthetic
subjects. Claims of independent natural-language transfer, learned NDU/FBSDE
value, production fitness, or speed superiority are explicitly excluded.

## Reproduce with exact read-only sources

Run `system2_reader_paired_capacity_audit.py` with positional arguments:
0.5B ZIP, cardinality ZIP, label ZIP, and a fresh output JSON path. Set
`HEPTA_MEMORY_TESTED_COMMIT` to exact checkout SHA. No model weights are
needed. The isolated workflow pins the three artifacts and executes all
original MemoryCell regression tests and scoped Ruff F/E9 checks before
writing the audit receipt and SHA256 manifest.
