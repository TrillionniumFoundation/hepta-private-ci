# Native12 TRAIN portfolio: positive additive means, overall qualification failed

**Final resource condition failed.** The separately charged saved-output audit
and final report process raise complete CPU to S10.018364924, H10.101410859,
A9.986479564 and N10.125681332 seconds. S/H/N exceed the unchanged10-second cap;
all unit caps hold. The final report process cost.225832 seconds, more than the
remaining S/H/N allowance after audit. This cost is retained, not excluded or
reclassified to restore a pass. Consequently the positive A−H means below are
developmental observations and **do not constitute a budget-qualified A−H pass**.
The original frozen analysis's mean-only flag is preserved unchanged, alongside
the final failed resource status in `evidence/final-costs.json` and
`evidence/final-status.json`. No rerun or cap change followed.

The single precommitted build exited0. The frozen saved-output analysis exited2:
coupling versus strong S/H log2 failed, native A−H had positive developmental
mean CE/joint differences, native N−A failed. The final full resource condition
also failed as stated above. This is reused TRAIN evidence, not formal
confirmation, reversal of CORE/r2, dynamic superiority or a best-static
whole-budget win.

Source971f36e54a4a → freeze15d77cacd63d → immutable raw results54c9706c3d35. Fourteen hand checks passed first. All24 models, every reached checkpoint, losses/gradients/actual displacements/moments/clocks, p/q/s/Q, source maps and 36 real service receipts are retained. No failed condition caused a rerun.

## Fixed primary outcomes

| Contrast, native unless stated | Mean CE change | Mean joint-success change | Result |
|---|---:|---:|---|
| S native − S independent log2 | -0.0065135157 | -0.0033836800 | rejected |
| H native − H independent log2 | -0.0077601412 | -0.0046563304 | rejected |
| A−H | +0.0027799607 | +0.0019742868 | positive TRAIN means |
| N−A | -0.0002565683 | -0.0001006754 | rejected |
| A−strong pure CE S (explicit comparison) | +0.0032467286 | +0.0023154765 | positive TRAIN means |

| Seed | Native A−H CE | A−H joint | Native N−A CE | N−A joint |
|---|---:|---:|---:|---:|
| 11 | +0.0017025115 | +0.0012494345 | -0.0003063885 | +0.0000645096 |
| 23 | +0.0048808520 | +0.0041370413 | -0.0016168863 | -0.0016686598 |
| 47 | +0.0017565185 | +0.0005363846 | +0.0011535698 | +0.0013021239 |

Native A−H and A−S CE/joint changes are positive in all three seeds. For A−H, mean both-wrong and wrong-agreement each decrease by.001974286802; both head correctness rates increase by the same amount. Greedy mean improves by.000434027778, one row in2304 seed/request observations. This supports a bounded training effect within this fixed joint architecture and resource recipe; independent-source benefit remains unconfirmed. N−A is mixed by seed and negative on both primary means. Do not substitute its positive seed47.

## All architectures and visible error cases

| Family/law | CE | Joint success | Both wrong | Wrong agreement |
|---|---:|---:|---:|---:|
| S/KEEP | 0.957714961 | 0.969908469 | 0.008902465 | 0.008517890 |
| S/log2 | 0.985452534 | 0.986366781 | 0.010455866 | 0.010447425 |
| S/native | 0.978939018 | 0.982983101 | 0.017016899 | 0.017016899 |
| H/KEEP | 0.959761276 | 0.971561432 | 0.008124489 | 0.007780999 |
| H/log2 | 0.987165927 | 0.987980621 | 0.010111384 | 0.010103463 |
| H/native | 0.979405786 | 0.983324290 | 0.016675710 | 0.016675710 |
| A/KEEP | 0.958689603 | 0.969984209 | 0.009621126 | 0.009290073 |
| A/log2 | 0.984639934 | 0.985152799 | 0.012549041 | 0.012530416 |
| A/native | 0.982185747 | 0.985298577 | 0.014701423 | 0.014701423 |
| N/KEEP | 0.966834649 | 0.975463211 | 0.007982104 | 0.007737729 |
| N/log2 | 0.987912803 | 0.988540796 | 0.009949914 | 0.009938228 |
| N/native | 0.981929178 | 0.985197902 | 0.014802098 | 0.014802098 |

| Family/native | Text correct | Image correct | Greedy joint |
|---|---:|---:|---:|
| S | 0.982983101 | 0.982983101 | 0.988281250 |
| H | 0.983324290 | 0.983324290 | 0.988281250 |
| A | 0.985298577 | 0.985298577 | 0.988715278 |
| N | 0.985197902 | 0.985197902 | 0.988715278 |

Native has zero one-correct/disagreement mass because every output is one semantic code; consistency alone says nothing about correctness. Both-wrong is still higher than the corresponding independent log2 in every family mean. Even A native has lower CE than A independent log2 despite slightly higher joint success. Every marginal, both one-correct cases, wrong disagreement, pixel MSE and greedy array is preserved in quality-summary/quality NPZ.

All native families improve over the identical zero-update conditional law; A's mean gains are CE+.024965682213 and joint+.016197788645. Zero controls separate real training from changing the law at initialization. Native A remains below historical strong S/H/A log2 CE and below the new independent N log2. Those are retained historical/same-portfolio references, not a free model portfolio.

## Actual updates and causal limits

| Family | Independent updates11/23/47 | Native updates11/23/47 |
|---|---|---|
| S | 362 / 386 / 390 | 511 / 511 / 511 |
| H | 393 / 399 / 418 | 511 / 613 / 511 |
| A | 356 / 255 / 338 | 511 / 511 / 511 |
| N | 352 / 355 / 354 | 490 / 511 / 511 |

All24 model clocks match real updates. All120 active parameter groups have nonzero first and final actual displacement: True. The saved PNG/state audit verifies this without another model forward. Decoder parameters remained exact and decoder moments were never advanced.

All slots stopped on the frozen CPU preflight. Checkpoint costs were inside the slot allowance: a due1/128/256/512 checkpoint requires.10 remaining CPU seconds. This creates visible255/511 stopping cliffs, including A independent23 at255 and most native slots at511; H native23 reaches613. No checkpoint/guard was removed after seeing scores. These update counts, changed objectives and checkpoint/trace costs prevent assigning a failure to head capacity or a single optimizer mechanism. The saved fixed fit/inner curves are in evidence/audit-result, separated by partition and including every reached checkpoint. Mini-batch first/last losses refer to different batches and are not matched learning curves.

## Full budgets and real service

The same10-CPU-second/12B cap applies to each full six-model family. Common CPU=4.495378557: inherited bases2.075925876 + both preflights.982089705 + actual new common1.437362976. The2-second/500M tail reserve leaves.584103574 CPU seconds and1.297706064B per training slot. No unexecuted allowance is padded. Final allocation includes active work, common scheduler and .203826386 seconds of outer administration/saved-output analysis; that analysis adds2,982 actual priced summary units.

The native four-group compiler alone cost0.190958011 CPU seconds (a subset of preflight). The inherited independent compiler cost 0.382784261, a subset of old preparation. Per-slot architecture-specific binding/initialization CPU/units are retained in candidate.json. Both are paid here because every family contains both recipes. A future independent-only deployable system must not inherit unused native costs.

The separately frozen saved-output audit adds.930167 CPU seconds and19,195,498 units to EACH SAME family. It verifies all2304 actual PNGs/captions against decoded semantics, source/label/probability/action records, and all24 model states. No new model/decoder forward, sampling draw, model image render, service repeat or retiming occurred. Original build/analysis arrays and gates are unchanged.

| Family | Complete CPU, including final descriptive receipt work | Complete units |
|---|---:|---:|
| S | 10.018364924 | 9,771,516,546 |
| H | 10.101410859 | 10,150,868,964 |
| A | 9.986479564 | 9,399,505,194 |
| N | 10.125681332 | 9,638,731,411 |

All final caps hold: False. The final lossless descriptor write follows its CPU snapshot, as explicitly labeled. The new source/result Git publication and prose editing are research archival work, not a claim that all historical R&D consumed the same resource budget. Old e7de ledgers are untouched.

There are exactly576 new actual requests per family (9 calls),2304 total. The separately paid inherited64 calibration requests and nine hand-test PNGs are not added to this service-test denominator. Log2 real repairs by family: S=4, H=2, A=2, N=3. All actual sampled outcomes, including errors, are in the PNG audit; they do not replace exact-law primary expectations.

Per-call timers now include input/guard/ledger setup through inference, sampling, PNG/JSON and full probability/source receipt export. They stop before Python return and parent ledger aggregation, whose CPU is in complete family totals but not separately timed per profile. They are trace-heavy batched observations, not a complete production latency/net-CE comparison. No e7de component timing was promoted or rerun.

Maximum final native sparse/full-Q metric discrepancy=6.6613381477509392e-16. Exact requestwise joint CE, the original scorer/rho and declared greedy contracts are retained. TRAIN positivity here does not authorize formal opening or close the parent training/NDU/dynamic research goals.

Review build.json, analysis.json, the outer .execution.json, source-map.json, quality-summary.json, every model directory and evidence/audit-result.json.
