# Frozen Qwen three-cohort evidence: 160 original calls, no parametric-memory promotion

**13 October 2026 — research-only, exact original artifacts.** This work uses
completed, previously generated pretrained model answers. It does **not** run new
Qwen inference, train a Cell, authenticate human source judgments or produce an
independent future-task population. Source hashes identify bytes, not semantic
truth. An independent mechanical replay is not a human entailment review.

## Three genuinely completed, but non-independent interventions

| Cohort / intervention | Original model calls | Distinct evaluation questions | Scoring metric |
| --- | ---: | ---: | --- |
| Authored controlled events: k calibration | 40 | 8 calibration questions | Strict identifier |
| Authored controlled events: nine source arrangements | 72 | 8 authored development questions | Strict identifier + formal public citation path |
| Published LoCoMo: label-blind lexical k4/k8 | 32 | 16 public questions from two conversation-family proxies | Normalized answer token-F1 |
| Same LoCoMo questions: publisher-supported sources | 16 | **The same 16 public questions**, not 16 new cases | Normalized answer token-F1 |

**160 completed original generations do not equal 160 independent questions.**
There are 24 distinct evaluation question IDs across these cohorts (plus eight
separate calibration questions). The LoCoMo sample has only **two published
conversation-family proxies**, and the event questions are authored; there is
no authenticated prospective or independent future-source cohort here.

Sources, original run IDs and exact immutable artifacts:

- Frozen event original [run 38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900), generating source `6304b451268c73f3d1a605985226b102df841bbf`: reader artifact `11743043427` (ZIP SHA-256 `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`); independent mechanical replay artifact `11748040166` (`2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071`). Exactly 40 calibration + 72 evaluation originals, each succeeded.
- Published LoCoMo lexical k4/k8 [run 38280267308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38280267308), source `96b5ec37b82f87d445740403e07e3705e9850955`: public history `11728164433`, frozen retrieval `11729394703`, separate evaluation target `11728856834`, 32 original model calls `11763718022`, and separately completed scorer `11766482516`. Their whole-ZIP SHA-256 values are hard-pinned in `reader_cross_population_gate.py`.
- Publisher-support-only LoCoMo [run 38353622487](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38353622487), source `2db775a9b423f5d53c2ec1cf69d4e67da02e35bd`: privileged source-ID plan `11792575178` (ZIP `66bc69310096b0226e90a8503df9d8d29645766066bbcf6acda7fd32241fb2b0`), original 16 model outputs `11792880133` (`14dc63bfb0e25b8b15f7b48ba8e1afd4cef4d13f8617d08d28a533baa7a202a0`), separate score `11792297662` (`cb753cd17db2b06027393175097d5a74b3fdfba459698f14d243d6ec14642698`). Publisher support IDs are **annotation-privileged** and unsuitable as a deployable online retrieval policy.

## Observed comparable and non-comparable outcomes

Under frozen Qwen inventory `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`:

| Control | Real quality | Caveat |
| --- | ---: | --- |
| Authored event full relational path | 8/8 strict | Only 4/8 correct answers cite a full declared public source chain |
| Authored event organized revision pruning | 8/8 strict | Adds **0/8** strict successes or complete citation chains relative to full path; saves 573 prompt tokens over eight reads |
| Published LoCoMo lexical k4 | 0.172083 mean token-F1 | 16 public questions |
| Published LoCoMo lexical k8 | 0.111482 mean token-F1 | Same 16 questions; more context worsened mean F1 |
| Published LoCoMo publisher-support IDs | 0.264376 mean token-F1 | Same 16 questions, **privileged annotation-assisted** source selection |

The publisher-only contrast against original LoCoMo k4 yields descriptive
+0.092294 F1, but cannot be attributed to a learned Cell. Among the **five
answerable tasks missing publisher source IDs under k4**, privileged support
helps materially; on **eight answerable tasks with the IDs already present**,
privileged source selection does not improve mean F1. Of three explicitly
unanswerable questions, the reader made only **one exact standalone refusal**;
other outputs contained unreviewed mixed refusal text. Citation label binding
is not semantic evidence of support.

## Fail-closed composite of two existing independent source auditors

`reader_three_cohort_gate.py` delegates original-byte validation to the
preexisting, independently source-pinned `reader_cross_population_gate.reconcile`
(seven original ZIPs / 144 real generations) and
`locomo_publisher_completion_receipt.audit` (three original ZIPs / 16 new
privileged-support generations). The new pure join checks **identical reader
inventory**, all planned counts, exactly matching *original* k4/k8 baseline F1,
private support privilege, the 5-missing/8-already-covered support strata, event
strict/citation dispositions, incomplete/mismatched data, and explicit no-go
research/production gates. It rejects any attempt to pool incompatible metrics,
count 16 reused LoCoMo cases as independent questions, or promote privileged
source selection to online learning evidence.

The new read-only Actions workflow reacquires the **ten unchanged original ZIPs**
and uploads only checksums and aggregate verdicts, never the original answers,
benchmark targets, private source text, model weights or publisher support plan.
It changes no required `blocking-ci` gate or production router.

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_reader_three_cohort_gate.py' -v
# The hosted workflow supplies the ten exact original ZIP paths in a fixed order.
python3 scripts/memory_cell/reader_three_cohort_gate.py \
  EVENT_MODEL.zip EVENT_REPLAY.zip LOCOMO_PUBLIC.zip LOCOMO_RETRIEVAL.zip \
  LOCOMO_TARGETS.zip LOCOMO_MODEL.zip LOCOMO_SCORE.zip \
  PUBLISHER_PLAN.zip PUBLISHER_MODEL.zip PUBLISHER_SCORE.zip \
  --output NEW_COMPOSITE_RESEARCH_RECEIPT.json
```

**Research disposition: NO-GO** for learned or parametric-memory superiority,
99% semantic citation precision, prospective source-family transfer, retention/
revocation/rollback lifecycle acceptance or production rollout. Next experiment
must obtain new independently sourced family-disjoint questions, an externally
adjudicated sufficient-evidence set, and the SAME frozen Reader tested against
label-blind strong RAG and simple full-path organization with full citation-chain
and lifecycle costs. Training the same eight authored or 16 exposed LoCoMo
questions longer cannot cure the missing validation evidence.
