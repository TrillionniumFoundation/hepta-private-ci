# MemoryCell strong Reader: publisher source-address citation audit

**October 16, 2026 · research only · HOLD_NO_GO / DENY_ALL / no FinalUse or main merge**

This additive postseal audit distinguishes three different properties: a Reader emitted a syntactically valid evidence tag; that tag refers to an *actually delivered* source; and the cited source ID is included in the original publisher's retrospective evidence references. None proves independent semantic entailment or independently certified evidence sufficiency.

## Exact historical cohort

- Original LoCoMo source SHA256: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Same precommitted 20 questions × six original evidence arms, plan SHA256: `a7ad39c6548b06dc0fd752cd77149deaeb46875b3307696fe2857ef0cd1fc3e9`.
- Original, actually generated frozen SmolLM2-135M output journal SHA256: `0797d8b1a4d9b9e3d7d68925bf4001666f253191d2bac46d90a0af11c78f0d76`.
- Audit code Git blob: `1f8bac1be6dd4cc9545a81712397e1ca988bb5de`.
- This report is a fresh **read-only recomputation of historical 135M answers**, not a new original-model inference or new Qwen3 result.

| Arm | Publisher evidence fully in delivered sources / 20 | Actual 135M generations | Emitted source tags |
| --- | ---: | ---: | ---: |
| Empty | 0 | 20 | 0 |
| BM25 | 8 | 20 | 0 |
| Temporal window | 9 | 20 | 0 |
| Meta-Graph | 9 | 20 | 0 |
| Publisher annotated (privileged) | 19 | 19 | 0 |
| Publisher annotated minus one | 0 | 19 | 0 |

Two original annotated-arm requests lacked source records and were recorded unavailable, not invented. Twenty per-arm requests are planned; 118 total real historical generations were already made in the original journal. **Address precision is `null` when the Reader emits no citations**, not 0%, 100%, or an independently verified semantic score. Retrospective published evidence is not an independently reviewed sufficient premise.

Sanitized result: `MEMORY_READER_SOURCE_CITATION_135M_AUDIT_20261016.json`, SHA256 `dec32ae25e70beb9e1c15a178cf290121522161363ba160b6260ac30a24ea778`. It contains only aggregate counters, original input/journal digests and explicitly negative authority flags. No source text, private labels, model weights or answers are committed.

## Implementation

1. New `memory_reader_source_citation.py` runs only in the **postseal reviewer** after the source corpus, model output, input-token identity and fsynced starts have been verified by their original owners.
2. Converts literal `[E1]` etc to the corresponding *delivered* source ID. Malformed or out-of-range markers count as invalid, not authorized citations.
3. Separates original publisher annotated sources, their coverage in each delivered evidence packet, source-address alignment of actually emitted citations and unmatched/unknown publisher labels.
4. Reports `publisher_address_agreement_among_known_in_range_citations=null` on zero eligible emitted tags; tracks missing labels separately. Never interprets a publisher address match as proof that the actual answer is entailed.
5. Strong Reader's `review()` adds an `publisher_source_citation` receipt only after its sealed output verification. Read-only CI exercises nine new adversarial/fixture tests; real 135M source is independently reopened for the local original-panel test. The new Qwen result, if it ever physically completes, is audited using the same logic during its separately staged postseal phase.

## Actually run checks and limitations

- **30/30 locally executed tests** in normal Python mode; **30/30 under `python -O`** (21 existing Qwen source/custody tests + 9 publisher-source citation tests).
- Tests in the local extracted checkout imported the earlier graph dependency through a narrow module import-only shim; no graph computation in the Qwen source/custody tests used that shim. On GitHub CI, the full actual graph source is present. This distinction does not affect the real historical source/plan/journal hashes used by the original-data tests.
- Exact Git Blob matches were independently checked for the two new source/test files and the modified Reader. No genuine additional Qwen3 forward was locally possible: Qwen publisher weights absent from this host.
- Physical strong-Reader workflow is separately triggered on frozen dedicated branch `research/memory-strong-reader-v2-20261016`, exact source `aa8ba657851a7172702832f57f3a9c018f40494f`; GitHub run [38985380451](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38985380451) was **queued** at the audit, not a passed Reader/model job. This one-time run uses the earlier frozen Qwen reviewer and thus does not claim the new publisher-citation receipt; the new receipt applies to follow-on executions of this source branch.

## Next model-performance gate

Only independently witnessed model execution, completed original/human-reviewed sufficient-evidence probes, answer correctness **and** cited-source semantic entailment, actual matched CPU/tokens/full lifecycle costs, source revocation/restart and out-of-time independent groups can support qualification. Any improvement by changed pretrained model/tokenizer is **Reader-stack capacity**, not MemoryCell parameter training, Cell Split, Meta-Graph or NDU gain. No production model promotion or CI waiver follows from these diagnostics.
