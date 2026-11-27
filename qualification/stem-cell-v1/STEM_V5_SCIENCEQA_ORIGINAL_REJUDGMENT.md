# V5 — original ScienceQA independent publisher-label rejudgment

**RESEARCH ONLY · DRAFT · SHADOW_ONLY · DENY_ALL · HOLD_NO_GO · no main merge, Cell Split, Model Selection or FinalUse.**

## Fixed source and original physical result

This work is an additive child of PR #2485. The original real Granite97 + DINOv2-small ScienceQA model computation is PR #2173, GitHub Actions run 38678847948 and original artifact 11947722496. The exact ZIP SHA-256 is f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30. This original contains 64 TEST source-bound predictions for eight text/vision control arms, but it intentionally does not contain original TEST labels. Prior audit #2192 could recompute paired-count arithmetic but could not independently rejudge original human labels.

Publisher: lmms-lab/ScienceQA-IMG, immutable revision b9984af01798586705cee1fbdfa80a6dcbef04f1.
Previously frozen original SHA-256: source a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202, fit labels e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e, held labels b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3, original predictions e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7.

## New implementation

scienceqa_independent_rejudge_v5.py is an independent Python implementation. It never imports the original model/trainer/stager/scorer. First it reopens the original SHA-pinned Actions ZIP and all 14 members, rejects malformed archives, duplicate JSON and altered file checksums. Separately it downloads the exact original upstream Parquet revisions, verifies sizes and original LFS identities, then independently replays source-first four-choice selection, RGB image-group hashing, source deduplication and train:96 / calibration:32 / test:64 partition. It recomputes exact original source and label SHA-256 BEFORE using labels for output evaluation. Any changed source or sample fails closed.

Only after a matching original input/label digest does the reviewer rejoin 64 per-case original predictions and recompute all eight arms' accuracy, NLL, four-class Brier and six original exact McNemar paired tests, requiring agreement with original released totals. No original media, model weight, original text, label rows or individual answers are uploaded. The only published output is a source-bound, aggregate, always-DENY_ALL review.

The read-only workflow is hepta-stem-v5-scienceqa-original-rejudge.yml and runs only on the exact original research PR HEAD. Fork PRs cannot access the original artifact. Source tests and full publisher rejudgment are separate jobs, and a source-only success must not count as original-model/source verification.

## What has actually run

Isolated local 6/6 source/anti-tamper tests passed under ordinary Python and 6/6 under Python -O. The complete physical E3 historical Actions ZIP was independently reopened locally and its 14 member digests plus complete 64-prediction roster were verified. No local full publisher-label replay occurred: network source acquisition is blocked in the isolated local runner. The new actual publisher-reacquisition job must finish successfully on its exact commit before claiming original 64-case per-answer rejudgment.

The historical positive signal (trained visual gate 24/64 versus text-only 17/64) has unadjusted paired p≈0.189 and six-comparison Bonferroni p=1.0. It is not proven visual superiority, independent human image-necessity evidence, new prospective task performance, source-issuer signature, or a new multimodal generating system.

## Remaining gates

Need independent human review of visual necessity, causal image shuffle/lesion experiments on matched future cases, three source-disjoint future windows, matched 421M lifecycle cost and actual learned sparse Cell fleet with long-term retention. No shared Stem/model selection, NDU, Cell Split, CAS/CNS or FinalUse may be promoted on this experiment.

Local source-only reproduction: cd qualification/stem-cell-v1 && python -m unittest -v test_scienceqa_independent_rejudge_v5; run again with python -O. The original-publisher live workflow is a separate mandatory qualification barrier.
