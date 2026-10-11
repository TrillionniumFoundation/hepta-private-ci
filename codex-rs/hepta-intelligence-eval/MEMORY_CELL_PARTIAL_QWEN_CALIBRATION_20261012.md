# MemoryCell: original Qwen calibration shard audit (2026-10-12)

**Scope:** independently inspected, real pretrained reader outputs from [GitHub Actions run 38150189865](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38150189865), generating commit `db7c31c90ad4eb7cf902c432a355c8302b0dffc2`. **This is incomplete calibration, not held-out evaluation or production qualification.** No new Qwen inference, parameter fitting, source relabeling or postprocessing was performed during the audit.

## Original source and model pins

- Qwen2.5-3B-Instruct research-only model revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1`; frozen model inventory digest `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
- Calibration-only eight-question plan SHA-256 `42417d57f72132d6403857843683f0e0497c17be5fb59c6afc2f2b25905cf031`.
- Case 0/part 0 [artifact 11707168275](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38150189865/artifacts/11707168275), ZIP `6edbb96edc7b783ddf6148b0c030e7d0ad63bfe9eec273a551bf9268d6ec7f90`.
- Case 2/part 1 [artifact 11707620762](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38150189865/artifacts/11707620762), ZIP `87f0358d2845a933866fe67ca6d4a0c08043327a0cdc9b3ad7b11848f3acf040`.
- Public source [artifact 11707090232](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38150189865/artifacts/11707090232), ZIP `ae58c43d6b5d5a39dc428e6f22b6df925e715d44307fa407f3620bec22b97904`; calibration-only labels [artifact 11706825892](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38150189865/artifacts/11706825892), ZIP `ea34d5dd7d900fa94d0c8a11729fabdccee57911a1f4c658d5ee2ffaf922eccf`.

The external standard-library replay checked all four outer ZIP SHA-256 values, both seven-member shard censuses, the six **shard manifest** file digests for each run, source IDs and ordered k-prefixes, original evidence bytes, deterministic source expansion, reader inventory, citation requests, narrow task grammar, label pins and the prior JSONL row count. Calibration labels were consulted only by this *post-generation* reviewer. It independently passed seven local corruption/census/unit tests.

## Partial real results (five answers, NOT 40)

| Original case | k | Strict success | Annotated support delivered? |
| --- | --- | --- | --- |
| new fact / case 0 | 1 | No | Yes |
| new fact / case 0 | 3 | No | Yes |
| new fact / case 0 | 6 | No | Yes |
| composition / case 2 | 2 | No | No |
| composition / case 2 | 4 | No | Yes |

Only **2/16 calibration shards**, **5/40 planned calibration answers**, and **2/8 authored calibration questions** are verified in this entry. All five original responses exist; **0/5 meet strict task success**, **4/5 have all program-annotated support present in the context**, and **1/5 cites all program-annotated sources**. Measured totals: **5,679 complete input tokens** and **105.352 Qwen generation seconds**. These are *descriptive incomplete-calibration counts*, neither confidence intervals nor validation/test accuracy, and are not appropriate for selecting k before the complete precommitted census.

## Cross-host stage identity — a real previously unmergeable condition

Two hosts produce different original stage JSON SHA-256 values: `312b094b4c9802ac592bb82ed9e691850fc0e70bce0fd1fdb432f00b74c64205` and `b592c746d2b1513751d9792f59877a2e86aaf25088c3b332d2528ed23fbb0cac`, because measured model staging elapsed seconds differ (45.182477574 vs. 30.598513707 seconds). The model inventory and publisher pins are unchanged. Removing *only* this host-specific field gives the same canonical stage SHA-256 `3c67750e9b39ed11dc78a449861cabfd0ecabe8abc6a24891bd90971dd791bd2` on both original shards.

**Do not merge this old run's raw-stage artifacts with newer sharded sources.** Commit `db7c31c` did not implement the later `canonical_model_stage.py`; the newer pipeline retains observed host staging time separately and requires canonical model identity across all 32 shards. The old partial observations cannot be passed off as successful complete calibration.

See the adjacent [machine-readable, explicitly nonqualified result](../../scripts/memory_cell/data/partial-qwen-calibration-20261012.json). The original four ZIPs remain at their referenced GitHub Actions artifact URLs. Further results must share one exact emitting source commit and include **40 calibration + 72 evaluation model responses**, then pass read-only sharded replay; subsequent test labels, independent source families, citation semantic review and lifecycle/production acceptance remain separate gates.

**Status:** `complete_calibration=false`, `frozen_k=null`, `qualified_model_evaluation=false`, `production_accepted=false`.
