# LoCoMo source-first evidence sufficiency and Reader citation review

**2026-10-13 · Research-only UNREVIEWED handoff · no production admission.**

The completed [LoCoMo matched Qwen run #38280267308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38280267308) produced **32 real answers**, comparing lexical top-4 with top-8 on the same **16 previously published development questions from only two conversation-family proxies**. The separately completed score reported token-F1 **0.172082581 versus 0.111481901**, respectively. Those low values cannot distinguish poor retrieval/evidence from inadequate Reader capacity by themselves. Structural citation markers have not received independent semantic entailment review.

The controlled eight-case Qwen strong-RAG [run #38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900) also demonstrated why a correct identifier is insufficient: complete-path and organized retrieval each achieved 8/8 strict task successes but just **4/8** full public cited evidence chains. All those controlled tasks were authored and previously exposed, not independent evaluation families. The 40+72 reader experiment and its separate replay are complete; no additional inference is required to construct this human review handoff.

## New source-pinned review worklists

[`locomo_sufficiency_worklist.py`](../../scripts/memory_cell/locomo_sufficiency_worklist.py) reads only these **three exact GitHub Actions ZIPs**:

| Immutable original evidence | Artifact | Exact outer ZIP SHA-256 |
| --- | ---: | --- |
| LoCoMo original public questions and histories | `11728164433` | `51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37` |
| Gold-blind fixed lexical retrieval decisions | `11729394703` | `3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097` |
| Unmodified actual Qwen generation journal | `11763718022` | `7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48` |

Reader source commit `96b5ec37b82f87d445740403e07e3705e9850955`, inventory digest `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225` and all 16×2 original responses are checked. The program validates the archive outer hashes, the original internal manifest where supplied, the **5,882** unique original source records, **480** label-blind retrieval decisions, original raw-answer journal, exact top-4 prefix of top-8, every delivered UTF-8 excerpt and source digest, model identity, token ceilings, frozen weights and absence of answer postprocessing. Any change fails closed.

It writes two worklists with **32 unreviewed entries each**, rather than presenting a self-generated judgment as an independent reviewer:

**1. `sufficiency-only.json` — must be reviewed first.** Provides original questions and verbatim selected evidence (with source hashes). It contains **no model answers, target/gold file, source-answer supervision or auto-scored results**. A separately authorized reviewer can indicate whether the evidence alone suffices, write the answer *derived from those sources* and identify precise UTF-8 evidence offsets. All verdict fields remain `null` until an actual reviewer fills them.

**2. `answer-and-citation.json` — a separate later review.** Provides the **unedited original Qwen answers** and exactly the evidence originally delivered, with emitted and undelivered citation labels. It contains **no benchmark target/gold file**, inferred gold-support set, automatic entailment verdict or corrected answer. The answer-support, citation-entailment and complete-chain fields also remain `null`.

These outputs have a SHA-256 manifest and an exact generating-source provenance file. They **do not** establish review independence: both GitHub Actions artifacts may be readable under the same repository access permissions, and the source-count difference is observable. Separate reviewer assignment and restricted distribution must be arranged by the actual review owner. Merely downloading or uploading the forms does not prove blindness, human independence or semantic sufficiency. Worklists do not contain reviewer identities, signatures or approvals.

## Run without models or benchmark gold

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_locomo_sufficiency_worklist.py' -v

python3 scripts/memory_cell/locomo_sufficiency_worklist.py \
  PUBLIC_ORIGINAL.zip LABEL_BLIND_DECISIONS.zip REAL_QWEN_JOURNAL.zip \
  NEW_OUTPUT_DIRECTORY
```

The opt-in read-only GitHub workflow is [`.github/workflows/hepta-memory-locomo-sufficiency-review.yml`](../../.github/workflows/hepta-memory-locomo-sufficiency-review.yml). It downloads the three source-pinned research artifacts only, **never the answer-target artifact `11728856834`**, and uploads the two review worklists separately. No model weights are fetched, no Reader is invoked, and no training, source-authority action, parameter-memory promotion or deployment is performed.

The next actual experimental decision needs a reviewer-confirmed sufficient evidence set on genuinely disjoint source-family tasks, then a same-reader/same-budget quality and full-chain citation comparison, with failures and total lifecycle costs retained. The current sources are **public, exposed and just two proxies**; they are useful diagnostics but cannot alone establish independent generalization or ≥99% citation precision. Every receipt stays `training_permitted=false`, `independent_human_semantic_judgement=false`, `production_accepted=false`.
