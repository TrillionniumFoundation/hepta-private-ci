# Independent review: fixed-weight routing diagnosis run-002

## Scope, identity and current status

This is a read-only audit of the frozen five-module snapshot and retained outputs, not another model run or test suite.
No repository, diagnosis input, checkpoint or in-progress output was edited. Only this report was written.
Read cutoff: 2026-10-23T14:06:57.563449+00:00. Seed 1907 complete; seed 2719 source observations complete but routes/result not yet present; seed 4051 not yet started.
Global result.json and failure.json were both absent at cutoff. Whole-run end-of-execution identity/weight checks therefore remain pending.
**Finding: no observed execution-correctness blocker or final-label leakage in the inspected path; completion of all three seeds is not yet certified.**

Paths used below:
- W = `/workspace/scratch/12ef9c5bdc23/routing-diagnosis-work`; E = W/run-002; C = E/diagnosis-source.
- R = `/workspace/scratch/12ef9c5bdc23/hepta-memory-work`; P = R/scripts/memory_cell_population.
- H = `/workspace/scratch/1d69f04ee9f4/memory-population-20261023`; historical final results are distinct evidence.
- E/source-identity.json pins repository HEAD `d61a36e21d1ad6d90614c145455b88c647c430e8`; all 107 repository Python-file hashes still matched when read.
- E/prepared.json pins protocol SHA256 `37b4788f42c6899fe60ee3f85098e9791fdb552126d529c1112e3e178511ab8d`; protocol/input/source/cohort file pins all matched.
- Exact five-module map digest: `f618cc5c165f198e906691f8a84ac80a2ba7f9c5cc6ce3fee596a60370a4e511`; each snapshot file also matched the currently executed top-level file.

| Snapshot module | SHA256 |
| --- | --- |
| diagnosis_common.py | 6fd2c3f0692ced1fedfd6c792d61a161ccf47ecb371994ec43d1f453289e5ab2 |
| diagnosis_execution.py | 6f06a958a7e9de1e3811dbd63bae9e215a8cfa84c817f3e57ff373a7771992b9 |
| diagnosis_routing.py | 58f503e7a912488cb4dc8ea8a670e7327462bd2b800007ef639442e07234a38c |
| diagnosis_scoring.py | c82cb9bc2baa35a1e975b2a0b435ff8193c282bbafbbc0bd7b282d323c6606b2 |
| diagnosis_trial.py | 9f44fa495510f0d293d2bb00fe479593ab5c47cc891a1f33b7c1e7c4f98efab0 |

## 1. Source utilities are actual new raw-output observations

C/diagnosis_trial.py.run_seed calls fresh_rows on both fixed child versions for all 304 source questions before constructing observations.
C/diagnosis_execution.py delegates to P/population_worker.py.fresh_read: an admitted owner launches a fresh parametric_worker.py process, retains stdout/stderr and checks request, questions, adapter digest and unpostprocessed text.
C/diagnosis_routing.py.observations sets utility = exact raw text equals SOURCE probe value AND probe_eligibility.capability_allowed; reject is the supported/unsupported source operation label.
For seed 1907, all six source journals (128+128+48 per child) matched their raw stdout rows; 608 actual rows, owner pre/post admission true, fact/retrieval/answer-lexicon inputs false.
Independent standard-library reconstruction found zero mismatches across all 304 two-child utility targets, raw texts, and separately recomputed source-capability admissions.
Evidence: E/seed-1907/source-panel.json, source-observations.json, source-expert-{0,1}/*-stdout.json and *-journal.json.
Historical answer/utility reports are hashed as unchanged evidence and their COST fields retained; the new fit inputs are not copied from those old answer scores.

## 2. Final-label isolation and route freezing

C/diagnosis_routing.py.fit_and_freeze receives source observations and an explicit final-metadata whitelist: probe_id/question/family/operation/source_roots; value/gold is rejected by its exact-field check.
The coordinator has the final fixture for later scoring, but only question strings go to parent feature extraction; no final answer or final correctness feeds fit_router, nearest prototype targets or hyperparameter selection.
Both new routers use the original config unchanged: 512 features, 400 full-batch updates, l2=0.0001, lr=2.0, min_confidence=0.55, min_margin=0.05, min_utility=0.5, seed=2718.
There is no performance-driven fit loop or winning-policy selection after final scoring. This does not make the previously exposed cohort a new confirmation set.
run_seed persists route-plan.json and route-plan-commit.json before starting the three final decoder readers, then rechecks the plan hash before scoring.
Seed 1907 plan SHA256: `5a263a3b8f5ab687b5e3e560b2b43fe3340e8cf575f85f77e6747f119f475252`; recorded freeze=1792764019693132072 ns, commit file mtime=1792764019711353976 ns.
Its three final worker start times were 1792764019737978290, 1792764063088119275 and 1792764110400373427 ns; all were later. Each request binding carries that same plan hash/freeze time.
Structured metadata eligibility and guarded policies have extra source-operation information; they must not be presented as question-only learned parsing.
All child/single outputs are computed, then the frozen policies select entries of one shared raw matrix: live_dispatch_executed=false, including guarded dispatch.

## 3. What full-cross versus balanced can identify

Both use the same 64 supported operations plus 12 unsupported operations, the same freshly measured child outputs, feature recipe, initial fit seed, optimizer count and thresholds.
Full-cross has 304 rows (4 wordings per operation). Balanced selects 76 rows, one wording per operation, with exactly 16 positive and 3 explicit-negative rows per wording; the stored indices and counts matched.
This is an interpretable distribution intervention, not an otherwise equal total-compute experiment: 304 versus 76 full-batch rows changes optimization data volume and matrix work despite 400 updates each.
The observed expert correctness can change with wording. Seed 1907 full-cross fitted 212 informative/24 tied/68 reject rows; balanced fitted 54/6/16. These are effective utility labels, not just explicit-negative counts.
The balanced control reduces the original 76-versus-304 data-count confound, but differs in wording and possibly resulting utility labels from the original fit. It cannot isolate wording as the sole causal mechanism.
Source nearest-neighbor diagnostics include each query's own prototype; source-assessments.json correctly labels them training observations, not independent test performance.
All 120 final questions were already exposed historically; all policies and seeds must remain reported even if only the retention panel improves.

## 4. Lexical and dense controls perform the stated operations

Lexical implements source-only unigram+bigram raw-TF × smoothed-IDF, L2 normalization, cosine nearest source question; no final-derived vocabulary/IDF or tuned similarity threshold.
Dense actually loads the pinned trained parent with its adapter ENABLED, runs inference-mode forwards, mean-pools the final hidden state over the full prompt, and verifies adapter/base states unchanged.
Its source prototypes are only the first 304 feature rows; final question features enter query-time cosine matching, not a parameter fit. Per-row normalization does not fit on final answers.
Both controls transfer a freshly measured source utility TARGET SLOT/reject, not an answer value. They are routing baselines, not complete answer-retrieval systems or benchmarks of a general embedding service.
Ties choose lowest source index; utility ties choose lowest child slot. Learned-router utility ties instead receive a uniform soft target; this declared difference limits claims of identical target treatment.
Seed 1907: parent features [424,576] float32, 977,024 bytes, 424 forwards/26,848 input tokens, zero optimizer updates, worker exit recorded; retained file SHA matched the receipt.
Stored dense prototypes [304,576] and lexical prototypes [304,209] were present; both index target lists exactly matched the recomputed source utility targets and stored answer_values_stored=false.
Index costs are explicit: lexical 529,158 bytes; dense 1,415,428 bytes plus separately charged parent-feature computation/storage. The trained-parent/base historical cost is reused, not free.

## 5. Cost and denominator boundaries

Seed 1907 actual added work: 968 decoder queries, 61,712 decoder input tokens, 2,032 generated tokens, 9 fresh decoder processes, 424 parent forwards, 800 router updates, zero decoder updates/gradient probes.
Decoder load+generation wall=357.883s; parent-feature wall=111.285s; whole-seed wall=470.772s. Substage times overlap the whole-seed total and must not be added to it again.
C/diagnosis_scoring.py.added_costs records per-policy routing/index costs, child/parent CPU, feature work and artifact sizes; shared diagnostic generations are charged once for the event.
Historical costs remain separate: 2,560 decoder updates per seed across all old measured arms, 64 gradient probes and the old 400-update router, plus old selection/final reads. Prior codec evaluations are outside this diagnosis scope.
equal_total_budget=false and per_policy_total_budget_matched=false are accurate. There is no per-policy live-dispatch latency, energy, equal resource deployment comparison or compression conclusion here.
Oracle/uniform score only the 96 known questions; their all total=96 versus 120 for other policies, and unknown total=0. Compare known/retention/transfer, not mixed all denominators.

## 6. Seeds, sample dependence and original oracle barriers

Three fixed historical seeds are repeated configurations of the same synthetic task families, not three independent natural task cohorts.
Per seed there are 44 source roots but only 28 dependency groups (16 semantic, 8 event histories, 4 programs); 64 source examples and four wording copies are correlated.
Neither 28 groups nor three seeds alone establishes statistical independence. No valid prospective confirmation or uncertainty interval can be inferred by treating 304/120 rows as independent tasks.
P/population_protocol.py and population_aggregate.py preserve oracle retention >=0.75, router-over-metadata >=0.05, and EACH transfer family >=0.75; the latter requires >=12/16.

| Historical seed | Oracle retention | Metadata retention | Oracle event interpolation | Oracle procedure extrapolation |
| --- | --- | --- | --- | --- |
| 1907 | 61/64 | 61/64 | 5/16 | 3/16 |
| 2719 | 47/64 | 42/64 | 6/16 | 3/16 |
| 4051 | 45/64 | 45/64 | 5/16 | 0/16 |

These values were read from H/seed-*/final/result.json.metrics, not inferred from README.
On that SAME fixed raw-output matrix, seeds 2719/4051 cannot reach the oracle-quality gate; seeds 1907/4051 cannot beat metadata by 5 pp even with perfect routing; all transfer-family upper bounds are below 75%.
A new raw matrix must still be measured rather than presumed identical. Seed 1907's new oracle already matches the old bounds exactly; other new seeds were unfinished at audit cutoff.
Therefore routing-only improvement cannot be described as closing the original scientific qualification. No old threshold or original report was changed.

## 7. Concrete result interpretation and remaining evidence

Seed 1907 new retention: original=2/64, full_cross=60/64, balanced=59/64, lexical=59/64, dense=37/64, single=45/64, metadata=oracle=61/64.
Its full_cross transfer is 8/32 versus single 11/32; full_cross unknown rejection is 4/24 versus original 12/24 and metadata 24/24. Retention improvement trades against other panels and remains below metadata.
The strongest supported present conclusion is that a large original routing failure is recoverable on this exposed fixed-decoder development panel; neither unique causal attribution to wording nor general memory advantage follows.
No concrete code bug requiring interruption was found. Still pending: seed 2719/4051 completed raw evidence, whole-run source/input/base end checks, complete added-cost totals and final result flags.
Do not promote a partial seed result's decoder_hash_check='whole-trial check pending' to whole-run immutable-weight verification before execute() finishes.
