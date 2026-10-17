# Reader evidence sufficiency × format: actual pinned FP32 model diagnosis

**2026-10-17 — RESEARCH / SHADOW_ONLY / DENY_ALL.** This narrow child of
MemoryCell Reader PR #2639 does not add a second MemoryOS, selected Reader,
production data writer, new trusted evidence, or bypass any required CI.

## Independent variables, original source and interpretation

The parent PR #2639 already sealed ten original LoCoMo question identities,
selected one per dialogue family by a preregistered SHA, and ran 50
SmolLM2-135M original-weight FP32 generations. This study keeps those
**same ten questions, same pretrained Reader, identical system message,
48-token generation budget**, and tests two carefully separated axes:

* **Published evidence completeness:** provide *all* 1–8 annotated source
  IDs from the exact original published LoCoMo document, versus remove a
  SHA-preselected one of those source IDs and renumber remaining labels.
  The selection uses question/source IDs, not answer text or learned model
  outcomes. On a one-premise question, the removed arm has no evidence.
* **Evidence format:** a strict JSON question/evidence envelope using the
  inherited \`strict_offline_result\` original Reader prompt profile, versus
  explicit \`[E1]\`-style lines with a separate instruction to cite sources.
  All four arms share the same original model checkpoint, and actual prompt
  token counts remain recorded, not claimed equal. **Equal max output
  tokens does not imply equal input token counts or cost.**

Published annotated source IDs are an **oracle source-selection diagnostic**,
never an eligible deployment retrieval policy. Even all annotated sources are
not independently certified to be semantically sufficient, and deletion of a
source does not prove it was a necessary premise. This experiment cannot
demonstrate parameter MemoryCell superiority, because it deliberately bypasses
the learned Cell in selecting the source-ID inputs.

## Actual original-weight CPU execution and source replay

* Original LoCoMo corpus SHA-256:
  \`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4\`.
* Exact plan SHA-256:
  \`d71f38bdc0667b465ed23fcfd3e7e057547e5ea48c18e3c27345ab4a15f6a5bc\`.
* Frozen Reader identity:
  \`afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c\`.
* Original sealed 40-response journal:
  \`9d5644e3701d149c1b758555d86071d44d7b022b594b553dc740af133f426e9b\`.
* Separate process, original-weight token-by-token reexecution completed for
  **40/40** responses before accessing reference answer strings. Final
  sanitized postseal score SHA-256:
  \`77f6993a97d803d87dce170c950a8e8422d9c3b6aa214bf789fc201e3310bdbf\`.

| Input condition | Original runs | String-scorable | Mean token-F1 | Answer contains an \`[E...]\` marker | Invalid marker count |
| --- | ---: | ---: | ---: | ---: | ---: |
| annotated source IDs, JSON | 10 | 8 | 0.168482 | 0 | 0 |
| one ID removed, JSON | 10 | 8 | 0.079621 | 0 | 0 |
| annotated IDs, labeled lines | 10 | 8 | 0.147397 | 2 | 0 |
| one ID removed, labeled lines | 10 | 8 | 0.069623 | 2 | 2 |

Paired complete-minus-removed:
JSON **4 gains / 0 losses / 4 ties** (mean token-F1 difference +0.088861),
labeled lines **4 gains / 1 loss / 3 ties** (+0.077775).
The eight scorable questions come from **ten correlated historical authored
dialogue families**, not ten independent prospective information sources.
These are original-model string-overlap diagnostics, not human-verified
reasoning/citation correctness. A label that was actually delivered is not
automatically semantically entailed by its source. In the removed-lines
condition, both observed label-bearing responses cited an unavailable label.

**Decision: no promotion.** Providing annotated sources helps in this small
historical test, but cited grounded answers are not reliable in either format.
The Reader requires stronger end-to-end capacity and citation controls before
learning the routing or split of more MemoryCells can be credited with a
real-task advantage.

## Engineering and tamper controls

\`reader_premise_format.py\` implements three independently invocable commands:

1. \`prepare PUBLIC SEALED_RANK ORIGINAL_CORPUS NEW_PLAN\` — only here may
   published evidence annotations be opened. The worker receives **only**
   \`plan.json\` and \`seal.json\`, neither gold answers nor private corpus.
   Plan and source identity are checked on the reviewer side, including
   duplicate, non-UTF8, out-of-scope and truncated source denial.
2. \`run NEW_PLAN READER_WEIGHTS NEW_OUTPUT\` — actually executes pinned
   original FP32 Smol weights, sealed output, exact bounded prompt/output
   tokens and immutable model identity. No answer injection or post-inserted
   citation. The eight-file Reader manifest is SHA verified before inference.
3. \`review PUBLIC SEALED_RANK ORIGINAL_CORPUS PLAN RUN READER_WEIGHTS NEW_REPORT\`
   — reconstructs **original source-only selection**, rejects plan/label
   drift, reexecutes each model response on the exact model and prompt,
   rejects a changed original output (except nondeterministic elapsed time),
   and only then opens publisher answer annotations for scored results.

These are **separate responsibilities**, not independent human adjudicators or
cryptographic signatures. No source use/training permission is inferred from
self-attested plan hashes. Current model backend has not established official
Hugging Face/BF16 parity.

Run focused tests (also validates six inherited Reader boundary tests):

\`\`\`bash
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_reader_premise_format.py' -v
\`\`\`

The five-job Actions workflow retains the exact stage separation and immutable
source artifacts. A green local test or historical run alone is **not**
the same as completed exact-HEAD hosted CI. Required \`blocking-ci\` and
Architecture checks remain mandatory, and no direct \`main\` merge is authorized.

## Required next experiment before MemoryCell promotion

Use an independently validated capable Reader with **sufficient versus
intentionally insufficient evidence**, masked-premise controls, source-citation
entailment adjudication, stronger cached BM25+dense+temporal graph retrieval,
new source families and two real future windows. Keep every model/source/cost
revision frozen and report failures, abstentions, full-token budget, p95/99,
energy, revocation, restarts and complete lifecycle TCO. Only then test
whether question-conditioned parameter memory improves *real* tasks over the
same-Reader strong retrieval baseline. Until then the source-faithful
Temporal/RRF retrieval path remains preferred.
