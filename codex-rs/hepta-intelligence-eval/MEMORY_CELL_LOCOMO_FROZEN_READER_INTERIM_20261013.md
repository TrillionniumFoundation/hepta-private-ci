# MemoryCell: sealed LoCoMo k4/k8 Reader evidence before hosted scoring

**2026-10-13 · Research-only model results · NO-GO for promotion**

This is a separate, model-free score of **already completed** Qwen2.5-3B
reader responses on a fixed publicly sourced LoCoMo population. It does not
replace the hosted `score` job, simulate missing answers, create an independent
future population, certify citation entailment, or establish parameter-memory
benefit. The original model produced 32/32 completed generations without
opening evaluation targets in the generation process.

## Original exact evidence pins

| Evidence | GitHub Actions artifact | Entire original ZIP SHA-256 |
| --- | ---: | --- |
| Actual 32 Qwen responses, source code, sealed original journal | `11763718022`, [run #38280267308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38280267308) | `7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48` |
| Original public LoCoMo histories and 16 evaluation questions | `11728164433` | `51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37` |
| Original label-blind frozen retrieval decisions | `11729394703` | `3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097` |
| Original separately stored evaluation targets | `11728856834` | `d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978` |

- Exact generating commit: `96b5ec37b82f87d445740403e07e3705e9850955`.
- Frozen Qwen inventory digest: `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
- Frozen Reader prompt profile: `2fd394cbd23ce9d9dfb9f94def31df1b52d9e437e5be0fd6a91e5cd8736a1abe`.
- Original 16 evaluation questions from **two public source-family proxies**,
  5,882 uniquely identified original history documents and 480 original
  source-only retrieval decisions; only the 32 `lexical_k4` / `lexical_k8`
  evaluation decisions are used here.

The separately executed read-only interim checker validates the exact outer ZIP hashes, every reader and
decision `SHA256SUMS` entry (13 original reader artifact members), immutable
`READY.json`, original unscored journal SHA, all 32 question×arm rows, source
scope, selected ordered IDs, exact original UTF-8 excerpt, root IDs and source
digests, one model/profile, actual budget receipts, and no generation-time
label opening. **Only then** does it open the externally pinned evaluation ZIP.
It scores the original unedited answers with the same normalized token-F1,
exact-match, exact refusal and citation-marker grammar as the repository's
`locomo_frozen_reader_pair.py` scorer. It does not reexecute tokenization or
claim independently verified semantic citations.

## Observed Reader results, not a trained-memory effect

| Same frozen reader; 16 questions per arm | Lexical top-4 | Lexical top-8 |
| --- | ---: | ---: |
| Actual succeeded model calls | 16/16 | 16/16 |
| Eligible diagnostic token-F1 answers | 16/16 | 16/16 |
| Mean normalized token-F1 | **0.172082581** | 0.111481901 |
| Original strict normalized exact matches | 1/16 | 0/16 |
| Complete Reader prompt input tokens | **6,254** | 10,473 |
| Generated output tokens | 705 | 824 |
| Sum of original Reader seconds | 247.738 | 310.821 |
| Emitted structural citation markers | 11 | 15 |
| Answer with an undelivered citation marker | 0 | 0 |

Across **16 preregistered paired questions**, top-8 has **3 wins, 7 losses,
6 ties** in actual diagnostic F1. Its paired mean F1 difference from top-4 is
**−0.0606006800**, for **4,219 additional input tokens** (+67.46% on top-4).
Token counts are not billed API usage or total memory lifecycle cost. Emitting
only delivered citation labels does not prove their semantic support.

These 16 answers belong to only **two published source-family proxies**.
Neither statistically independent family superiority nor a cross-domain
calibrated read-policy gain follows. A top-8 or top-4 winner must not be
promoted globally from these scores. The fixed input corpus is public and
may have appeared in model pretraining; no independent contamination review
is available. `training_qualified=false` and `production_accepted=false`.

## Exact offline reproducibility and verifier scope

Save the four artifact ZIPs under the names above in one directory. Run:

```bash
PYTHONPATH=scripts/memory_cell python3 \
  scripts/memory_cell/locomo_frozen_reader_pair.py score \
  ORIGINAL_PUBLIC_ZIP_DIRECTORY ORIGINAL_TARGET_ZIP_DIRECTORY \
  EXTRACTED_COMPLETED_GENERATION_RUN_DIRECTORY NEW_SCORE_OUTPUT_DIRECTORY \
  --expected-commit 96b5ec37b82f87d445740403e07e3705e9850955
```

The additional standalone interim checker and its five tamper/metric tests are supplied as companion downloadable artifacts. The command above deliberately uses the already tracked canonical GitHub scorer rather than substituting a new one. No raw model answers are committed.

This result is a **source-pinned interim receipt**, deliberately distinct from
the queued hosted `score` job for [run #38280267308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38280267308).
When its independent hosted scorer finishes, compare its model-free results
and original generated commit before using either report as research evidence.
Future work needs additional truly disjoint sources, stronger reader-sufficiency
comparators, verified citation chains and prospective operating costs, not an
unqualified k expansion or longer training on this exposed evaluation set.
