# MemoryCell — two completed native Stem runs: negative advancement gate

**Scope:** Read-only, original-artifact-verifiable evidence as of 2026-10-11. This is NOT another model execution, prospective holdout, independent semantic judgment, or production authorization.

## Independent execution evidence

| Source commit | GitHub Actions | Artifact ZIP SHA-256 | Inner verified files | Policy attempts |
| --- | --- | --- | ---: | ---: |
| `675970bb610c70bb0ec30a2dee05c025440510e6` | [38114716982](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114716982) | `1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8` | 130/130 | 576/576 |
| `95a20c4287bd6e9ab3fefd95774a2d9c8212d73f` | [38116089672](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38116089672) | `a3322c5dec5f0d2a7453e90a97095e746e206a01c102749b458e3ed816573cc6` | 133/133 | 576/576 |

Both GitHub Actions runs are actually **completed/success**. Original ZIP bytes, manifest file census and all declared member SHA-256 digests were independently checked; `tested-commit.txt` agreed. Three adapter safetensors payload hashes match across runs.

Each archive's `comparison/scored-policy-attempts.json` has exactly **576 unique stage/phase/arm/cell/question records**: three checkpoints (16, 32, 48), 32 registered questions across four phases per checkpoint, six arms. These are *logical policy attempts*, not 576 independent tasks or 576 newly generated model responses.

## Matched, actual held-out-development outcomes

Across the two successful source revisions, all 576 aligned policy records agree in ten original fields: answer, citation structure, diagnostic answer F1, encoder identity, feature digest, head state SHA, pool digest, selected candidate, weak native source-choice correctness and execution status. The count of differences is **0 for each field**.

For each of the five learned arms — prototype, linear, gated, shared-lineage LoRA + gated, and independently adapted LoRA + gated — comparisons with the *same-stage, same-question, same-Cell* frozen reranker give:

| Measurement on test and transfer development | Per learned arm |
| --- | ---: |
| Matched stage-scoped observations | 48 |
| Additional source-selection wins | **0** |
| Changed generated answers | **0** |
| Correct weak source-selection observations | **27/48**, same as frozen |
| Mean token-F1 over 48 planned observations | **0.052128**, same as frozen |
| Original answers containing source labels like `[E1]` | **0/48** |

**Important denominator:** The 48 rows are the same 16 test/transfer questions (8 test, 8 transfer) observed at three training checkpoints. They are not 48 new source families or independent holdouts. Six of the 48 rows have absent F1 annotations; they remain in the planned denominator, not fabricated successes.

Training actually occurred: the archives contain adapter training receipts and three pinned safetensors payloads. The result is **no observed held-out-development source/answer gain**, not a claim that no optimizer ran. Differences in training loss, memory state hashes or in-sample fit do not overturn this task result.

## Acceptance disposition

**NO-GO on scaling parametric read Heads or claiming LoRA memory advantage based on these two runs.** This is a bounded no-gain result on the exposed corpus, not a proof that learning can never work. Revisit only after a new, admitted task distribution, independently checked gold source support and a learned improvement over a reader-matched strong RAG/filtering baseline. No semantic citation precision, new future-window retention or production acceptance is authenticated by this audit.

Reproduce by downloading the two exact run artifacts, checking the above external ZIP SHA-256s and every `SHA256SUMS` line, reading `comparison/scored-policy-attempts.json`, rejecting duplicate `(stage,phase,arm,cell,question_id)` keys, aligning 576 rows by that composite key, and pairing learned arms against `frozen_rerank` on exactly matching `(stage,phase,cell,question_id)` for `phase in {test,transfer}`. Validate `comparison/report.json` has complete 576/576 census and `production_accepted=false` in both runs.

Machine-readable result: [stem-two-run-negative-gate-20261011.json](../../scripts/memory_cell/data/stem-two-run-negative-gate-20261011.json).
