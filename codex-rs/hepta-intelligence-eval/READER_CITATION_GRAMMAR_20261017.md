# Reader citation output protocols — four original-weight causal controls

**2026-10-17. RESEARCH / SHADOW_ONLY / DENY_ALL. This is not a fact writer,
memory-serving upgrade, learned Cell gain, independent semantic entailment
certificate, or production selection.**

## Source and ancestry

This additive experiment stacks on MemoryCell original Reader premise/format
PR #2660 and reuses its original publisher evidence-only ten-question plan.
That plan was constructed from the original LoCoMo dataset with exact SHA256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`,
and the original plan digest is
`d71f38bdc0667b465ed23fcfd3e7e057547e5ea48c18e3c27345ab4a15f6a5bc`.
Publisher source references are not independently certified sufficient premises
or deployment-eligible retrieval. The authoring cohort consists of ten
correlated dialogues; reported question counts are not independent families.

A four-arm frozen experiment varies *only the output grammar*, not question
identities, original referenced source IDs/text, Reader model, system prompt,
or 48-generation-token ceiling:

- `legacy_lines`: byte-equivalent original annotated-lines Reader prompt.
- `citation_first`: request a delivered source label before the short answer.
- `citation_last`: request a delivered source label after the answer.
- `two_field`: request separate Answer/Source lines.

Real input-token counts differ and **are measured**, not described as
equal-budget. No condition receives answers or private annotations in the
model worker. Every condition receives an independent copy of the original
source excerpt objects. Wrong lineage, duplicate arm, mutation or inconsistent
evidence across arms is rejected before model execution.

## Actual local original weights and independent replay

The pinned original SmolLM2-135M-Instruct CPU FP32 Reader file inventory is
`afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.
It is **not** numerically certified equivalent to registered Transformers/BF16.
The run used original source bytes, unmodified original weights, 40 actual
generations and a physically separate local process that reloaded original
weights to replay all 40 outputs token-for-token *before* reopening publisher
answer annotations. The ten `legacy_lines` prompts matched all ten of the
preceding study's sealed input-token and output-token hashes exactly.

| Protocol | Source labels validly emitted / 10 | Mean token-F1 on 8 scorable | Input tokens / 10 |
| --- | ---: | ---: | ---: |
| Original lines | 2 | 0.147397 | 1,858 |
| Citation first | 4 | 0.185860 | 1,909 |
| Citation last | 4 | 0.196960 | 1,859 |
| Answer/Source lines | 0 | 0.135854 | 2,009 |

Paired citation-first versus original: 1 gained / 1 lost / 6 tied on
eight scored answers. Citation-last: 1 gained / 2 lost / 5 tied.
These **are not** semantic success or statistical-superiority claims. Citation
strings were checked against delivered labels, but **no independent human
entailment review of the cited answer proposition** was performed. No method
exceeded 4/10 structurally valid citations; thus none is remotely qualified
for production. This study was not a prospectively independent sample.

Original 40-call journal SHA:
`1871486ea95af3f03f2d5bfd99be2d97871d0d745cdc7382f5252f08af1cce07`.
Separate full reexecution/review SHA:
`e0d6caed068541f437135f1c6db61b83edcdd3f3dc7b0278c2cce3a3cf2e176b`.
The sanitized, no-answer review is recorded in
`READER_CITATION_GRAMMAR_ORIGINAL_20261017.json`. Raw original dialogue
answers, publisher model files and the raw original Reader language journal
are NOT committed. Original CPU model process wall 89.16s, maximum RSS
1,075,088 KiB; the separate replay wall 88.79s, maximum RSS 1,077,356 KiB.
These are not service-wide TCO measurements.

## Reproduction

Under the existing pinned original LoCoMo and original Reader weights:

```sh
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_reader_citation_protocol.py' -v
python3 scripts/memory_cell/reader_citation_protocol.py prepare \
  EXISTING_PREMISE_PLAN NEW_CITATION_PLAN
python3 scripts/memory_cell/reader_citation_protocol.py run \
  NEW_CITATION_PLAN PINNED_READER NEW_ORIGINAL_GENERATIONS
python3 scripts/memory_cell/reader_citation_protocol.py review \
  EXISTING_PREMISE_PLAN NEW_CITATION_PLAN NEW_ORIGINAL_GENERATIONS \
  PINNED_READER ORIGINAL_LOCOMO PUBLIC_ONLY SEALED_SOURCE_RANK \
  NEW_INDEPENDENT_REVIEW_JSON
```

The read-only GitHub workflow runs the original source preparation and
MiniLM/MemoryCell ranking as inherited, creates a publisher-source-bound
evidence-only plan, invokes the original Reader in an isolated job, then
reconstructs all original inputs and reexecutes all 40 answers before scoring
with original publisher answers. No reviewer or model can issue FinalUse.

## Decision

Retain the temporal/RRF retrieval baseline and unchanged production Reader.
This experiment demonstrates prompt sensitivity of *structural citation output*,
not correct evidence attribution, source sufficiency, long-term learning,
parameter-memory superiority or real-world generalization. Future effort must
secure independent semantic support judgments, Reader capacity and actual
resource-normalized end-to-end task success before any topology mutation or
Cell promotion.
