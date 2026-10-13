# MemoryCell: two completed 40+72 Qwen runs, source-exact and cross-host audit

**Research disposition: NO-GO for parametric-memory admission or a graph-accuracy claim.** This is a new **read-only** comparison of two **existing** full real-model runs, **not 224 fresh model calls** and not an independent task population. Each full run generated 40 calibration and 72 evaluation answers against the **same eight publicly authored development queries**. A second run improves reproducibility evidence, not generalization or sample size.

## Exact authentic sources and verification

| Role | GitHub Actions | Original source commit | Externally pinned ZIP SHA-256 |
| --- | --- | --- | --- |
| Original inputs | artifact `11669174727` | `c9dd3aeff958fbdc4356a98718e96dec47f9b820` | `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b` |
| Earlier Qwen model outputs | [#38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900), attempt 2 | `6304b451268c73f3d1a605985226b102df841bbf` | `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8` |
| Earlier separate replay | artifact `11748040166` | same emitting source | `2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071` |
| Later Qwen model outputs | [#38389920977](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38389920977) | `3b03ea7dee4b270bdf328251f7a404571c9d1013` | `de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf` |
| Later separate replay | artifact `11817452081` | same emitting source | `442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1` |

The audit refuses different outer ZIP bytes, missing/extra inner `SHA256SUMS` entries, duplicate JSON fields, altered original raw answers, dropped attempts, changed reader/prompt/output token digests, unqualified model identity, different selected sources, or a falsified paired/replay receipt. **35 original, 43 reader and 8 separate-replay members** are independently verified for each applicable ZIP. Model identity: `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`; Qwen2.5-3B-Instruct revision: `82f42baa094a9600e39ccd80d34058aeeb3abbc1`, research license only. Frozen plan SHA-256: `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.

## Independently compared original generation outcomes

Across the two full successful runs, **all 40/40 calibration pairs and all 72/72 evaluation pairs** had exactly the same task ID, arm, original answer, selected ordered evidence, model identity, complete prompt-token hash, generated-token hash, token counts, and strict task success. This is **112 paired reproducibility checks**, not a claim of 112 independent questions.

| Actual evaluation arm | Correct of eight | Formal complete cited source chain | Input tokens over eight calls | Earlier reader seconds | Later reader seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibrated RAG k=1 | 5 | 3 | 3,961 | 62.51 | 107.16 |
| Hybrid RAG k=4 | 3 | 1 | 10,806 | 136.04 | 259.61 |
| Hybrid RAG k=6 | 2 | 0 | 15,463 | 194.10 | 387.82 |
| Same Hybrid k=4, reversed | 3 | 1 | 10,806 | see JSON | see JSON |
| Single-hop selection | 4 | 4 | 4,575 | see JSON | see JSON |
| Entity/time **full path** | **8** | **4** | 5,752 | 79.21 | 141.30 |
| Correction-aware organized | **8** | **4** | 5,179 | 73.51 | 130.72 |
| Program-declared support | **8** | **4** | 5,179 | see JSON | see JSON |
| No evidence | 0 | 0 | 1,630 | see JSON | see JSON |

The **four additional successes** of full-path retrieval over single-hop are real paired within-reader development results. **Additional task successes for the organizer over full-path: 0/8; additional complete formal citation chains: 0/8.** Organizing removes 573 prompt tokens over eight calls (9.96% relative to full-path), but total ingestion, indexing, maintenance, retention, revocation and recovery costs remain unmeasured. In all eight controlled cases, both full-path and organized succeed on the final answer; in four, their answers fail the strict formal *entire-program-source-chain* citation check. That formal check is not a human semantic entailment judgment.

Top-k calibration selected k=1 (k=1 through 4 each answered 4/8 on calibration, k=6 answered 2/8), but its leave-one-calibration-question-out choice changes to k=2 in one of eight folds. The score on its overlapping omitted-question comparisons is 3/8 against fixed k=4 at 4/8. The fixed eight authored questions and overlapping folds provide no statistically independent superiority estimate.

## Cross-host latency is not a portable memory benefit

Both runs pinned Torch 2.5.1 CPU BF16/eager and identical Qwen weights. The earlier reader used **AMD EPYC 9V45** with 4 logical CPU records and Torch inter-op threads=2; the later reader used **AMD EPYC 9V74** with 4 logical CPU records and inter-op threads=4. Identical output/prompt digests thus coexist with 1.7–1.9× changed observed inference times across several arms. A cross-run latency delta cannot be attributed to a memory algorithm, and neither archive supplies real cloud billing or production inference SLO qualification. Within each run the same-host paired arm comparison is still informative.

## Newer disjoint shard is still not a result

The separate [sharded 40+72 workflow #38423223376](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423223376) has produced partial successes, but at least two calibration jobs failed the **mandatory accelerated BF16 CPU host gate** on EPYC 7763 runners. This is an infrastructure eligibility failure, **zero new model calls** for those failed shards; passing shards cannot substitute for them. Do **not** disable BF16 preflight, reuse old answers to fill gaps, change the original reader precision or label partial shards as a new independent experiment. Finish exact-source qualifying shards and replay only if eligible infrastructure is available.

## Decision and next research gate

**NO-GO:** this evidence does **not** establish an independent graph/parameter-memory task advantage, semantic citation accuracy ≥99%, independent future-source collection, statistical superiority or production qualification. Do not enlarge learned memory training or switch production. The appropriate next new experiment is an independently owned, source-disjoint real task population (including correction, relationship traversal, abstention, withdrawal and recovery) and independently reviewed complete citation chains under the same frozen reader/tool/budget contracts. Preserve the old full-path and tuned RAG as controls and instrument **full** lifecycle cost, not just tokens.

Run the standard-library reproducer with original *GitHub Actions* ZIPs (model weights not needed):

```bash
python3 scripts/research/memory_cell_crossrun_audit.py ORIGINAL_INPUT.zip EARLIER_READER.zip EARLIER_REPLAY.zip LATER_READER.zip LATER_REPLAY.zip --output crossrun.json
python3 -m unittest discover -s scripts/tests -p 'test_memory_cell_crossrun_audit.py' -v
```
