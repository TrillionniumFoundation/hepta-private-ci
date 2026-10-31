# Independent method audit: V13 executed memory-cell experiments

## Scientific conclusion

**The executed work demonstrates a functioning frozen-encoder / learned-adapter memory prototype and research lifecycle controls. It does not establish a general memory system, a reliable automatically improving split policy, a superior continual-learning tradeoff, or an exclusive benefit from naming components as cells.** All statements below refer to retained observations, not a new training run. No source, model, threshold, sample, or test result was changed by this audit.

## 1. Calibration-to-held-task transfer fails for the selected split

| Seed | Selected within parameter family | Selected calibration / 48 | Single calibration / 48 | Selected held / 72 | Single held / 72 |
| --- | --- | ---: | ---: | ---: | ---: |
| 713 | single | 41 | 41 | 59 | 59 |
| 971 | single | 41 | 41 | 61 | 61 |
| 1237 | random | 41 | 39 | 50 | 61 |

For seed 1237, the random partition improves calibration from single 39/48 (continue 38/48) to 41/48, but held execution falls to 50/72 versus single/continue 61/72. The recorded extrapolation of +625 correct answers per 10,000 requests is relative to continue and assumes future queries follow this calibration distribution. It is not an observed future gain and fails to predict this held ranking. This observation supports selection instability on the small authored calibration set; it does not uniquely identify overfitting as the cause without further data.

The selection code deliberately considers only single/continue/wide/fixed/random/learned/interference. Ordinary controls are evaluated but are not eligible to win this choice. Centroid scores 42/48 on calibration for every seed, higher than the selected parameter candidate. Therefore “selected” means a parameter-family choice, not the best available memory policy. The prospective value record compares against continue, not the strongest ordinary baseline.

Evidence: [seed-713 selection](run/seed-713/SELECTION.json), [seed-971 selection](run/seed-971/SELECTION.json), [seed-1237 selection](run/seed-1237/SELECTION.json), [all held outcomes](run/RESULTS.json); implementation: [experiment.py](../experiment.py).

## 2. What is and is not matched in the structure comparison

| Candidate | Learned numeric parameters | Extra presentations after parent | Qualification |
| --- | ---: | ---: | --- |
| Single parent | 10,764 | 0 | Parent trained for 4,800 presentations |
| Continue | 10,764 | 7,200 | Same architecture, additional optimization |
| Wide single, rank 24 | 23,052 | 7,200 | Matches aggregate expert parameters |
| Three rank-8 children | 23,052 | 7,200 aggregate | Heads partition the 12 labels into three sets of four |
| Router in every sparse arm | +1,155 | Ridge fit is additional | Complete sparse system totals 24,207 parameters |

Fixed, random, prototype-based, and gradient-interference partitions all receive the same 7,200 additional example presentations. This is not equal total FLOPs: expert-local updates, a wider dense model, and the extra router solve perform different work. The sparse system has 1,155 more parameters than the wide comparison once routing is counted. The initial parent function and full Adam/RNG state are preserved by widening; subset inheritance preserves adapter state and the corresponding conditional class logits. The combined split network does not preserve the parent distribution automatically, because a new group router and within-group normalization are introduced.

Each sparse arm records 120 calibration-plus-held requests and 240 expert-example invocations: exactly two experts per request. This establishes selected-only invocation rather than running all three and masking outputs afterward. It does not establish an end-to-end deployment speed advantage.

All three gradient-interference searches examine 5,775 balanced partitions using training-only A/B gradients. Recorded gradient norms are nondegenerate, so the poor result cannot be dismissed as the implemented normalization floor replacing all gradients by zero. The search minimizes a within-group negative-cosine proxy, not held task error, router error, retention, or total operating cost. Its held correct counts are 52/56/56 versus parent 59/61/61. A lower training-gradient conflict objective did not produce a better complete system in this experiment. The subsequently saved [post-run routing diagnostic](analysis/ROUTING_DIAGNOSTIC.json) records true-group top-two coverage of 68/67/70 out of 72, and oracle true-group predictions of 69/69/68 correct, for seeds 713/971/1237. The gap from actual 52/56/56 indicates losses associated with routing and cross-group competition; merely including the true expert among two selected experts does not ensure the final prediction uses it. The oracle explicitly uses the gold label, was not used for training or selection, and is not an achieved system result. These diagnostics do not uniquely isolate every contribution from partitioning, expert optimization, and score combination.

Proposal cost is explicitly recorded for the interference search and included in its proposal-plus-training figure. The prototype/random/fixed proposal-cost fields are null, not zero. This prevents treating those tables as a complete, identical resource budget.

Evidence: [all structure outcomes](run/RESULTS.json), per-seed `STRUCTURE.json` and `SELECTION.json`, [structural implementation](../structural.py), [six structural checks within the 24-test log](checks/scoped-tests.log).

## 3. New bindings are learned, but original skills are lost

| Seed | Frozen original skills / 72 | Replay original skills at frontiers 3,4,5,6 | No-original-replay skills at frontiers 3,4,5,6 | Final replay loss vs frozen |
| --- | ---: | --- | --- | ---: |
| 713 | 59 | 52, 53, 55, 52 | 27, 17, 13, 9 | 7 |
| 971 | 61 | 52, 53, 53, 55 | 26, 12, 10, 9 | 6 |
| 1237 | 61 | 54, 54, 51, 48 | 31, 15, 15, 11 | 13 |

The updated parameter models genuinely acquire arbitrary project-to-operation bindings: frozen models perform poorly on these new requests, while most updated stages reach 12/12. However, ordinary nearest/centroid/ridge and exact-project lookup also reach 12/12 at every frontier. The bindings are explicitly present as operation IDs in the legal journal, so exact project lookup is an appropriate strong control, not an oracle inserted from test outputs.

Replay is better than no original-skill replay for retention, but does not preserve the parent quality. The comparison uses equal update counts; replay has 138 current training rows, no-replay has 18 project rows, and partial batches create unequal presentation counts. The results therefore demonstrate this concrete replay policy, not a compute-matched proof of a continual-learning mechanism. All frontiers reuse the same projects and requests, and optimization seeds do not create new independent task sets.

Evidence: [full update summaries](run/RESULTS.json), per-seed `frontier-3` through `frontier-6/RESULTS.json`; [training and public-input contract](../TASK_PROTOCOL.json).

## 4. Provenance publication is real, and its quality/availability limits are visible

| Frontier | Skill calibration / 48 | Profile calibration | Publication | Held skills | Held profile |
| --- | ---: | --- | --- | --- | --- |
| 0 | 41 | not applicable | published | 59/72 | not applicable |
| 3 | 42 | 6/6 | published | 52/72 | 12/12 |
| 4 | 41 | 6/6 | published | 53/72 | 11/12 |
| 5 | 39 | 6/6 | candidate_retained_not_published | unavailable: 0/72 served | unavailable: 0/12 served |
| 6 | 38 | 6/6 | candidate_retained_not_published | unavailable: 0/72 served | unavailable: 0/12 served |

The fixed source-bound training and SourceOwner publication pipeline runs at frontiers 0/3/4. At frontier 3, calibration skill quality increases to 42/48 while held original skills fall from 59/72 to 52/72. At frontier 4, calibration remains above the 40/48 retention floor and profile calibration is 6/6, yet held skills are 53/72 and held profile success is 11/12. Passing the implemented validator is consequently not a guarantee of held quality or perfect current-binding correctness.

At frontiers 5/6 the candidates reach only 39/48 and 38/48 on skill calibration, below the fixed 40/48 floor, and are not published. The previous release depends on corrected sources and is correctly fenced. Both the 72 skill requests and 12 profile requests are unavailable at each of these frontiers. Their evaluated counts are zero, not successful conditional-accuracy observations. An account of reliable service must retain these 0/84 served stages rather than averaging only published releases. This is a conservative dependency-consistency result with an availability failure, not a continuously available production memory system.

The final revocation probe is already unavailable before revocation because the release was stale. The record correctly sets isolated_readable_to_blocked=false. It must not be described as a new isolated live-to-blocked revocation demonstration; separate lifecycle tests contain that scenario. Neither revocation nor a corrected source-cut manifest proves erasure of old information from weights. The integration run is another execution on the same authored data, not independent efficacy replication, and SourceOwner is a research SQLite owner rather than native production Hepta authority.

Evidence: [provenance results](provenance/RESULTS.json), `provenance/frontier-*/CANDIDATE.json`, `provenance/frontier-*/OWNER_READ_RESULTS.json`, [integration source](../provenance_run.py), [lifecycle source](../lifecycle.py).

## 5. Removal and substitution show dependence, not unique cell capability

Composition full fixed-expert execution is 11/12. Replacing typed procedures by the generic wrapper produces identical output and execution status on all 12 cases, because both invoke the same supplied function. Replacing semantics by the single adapter also matches all 12 outputs/statuses; nearest-example substitution reaches 12/12, exceeding the full composition path. Removing procedures drops success to zero, and disabling expert groups drops it to 5/8/5. These are causal path-dependence checks; removal of necessary computation is not a matched-capability alternative.

For profile requests, the full path is 10/12. Generic procedures, nearest semantics, and fixed-expert semantics each match all 12 output/status pairs of full. BM25 semantics and direct current exact-KV reach 12/12. Removing memory gives 0/12 and supplying stale memory gives 6/12, establishing that current-source information matters. The “memory” in this cooperation experiment is an explicit journal read, not a parameterized memory cell. The workflow also supplies each composition step publicly. It does not demonstrate learned planning, spontaneous heterogeneous-cell discovery, or a learned cross-node meta network.

The cooperation arm ordering is fixed and each case is executed once per arm. Its timing totals diagnose actual work; they are not the randomized repeated latency study or evidence of reliable microsecond rankings.

Evidence: [cooperation summaries](cooperation/RESULTS.json), [complete per-arm traces](cooperation/PREDICTIONS.jsonl), [cooperation implementation](../cooperation.py).

## 6. Leakage, information parity, and scope of the controls

- The inspected fit paths use training X/y only; partitions and the interference gradients use the same training set. The frozen encoder processes held text during input preparation but does not learn from it. No fitted transform uses held labels in the inspected path. Scoring reads expected outputs after prediction/execution. This supports the finite comparison; it is not a security proof that arbitrary future code can never leak labels.
- Pure parameterized project inference sees the project request, not its current policy, operation ID, source revision, gold output, or case position. Its labels are learned from legal source events. Hybrid inference intentionally reads the policy at runtime and must remain labeled as that different regime. A project ID is explicitly named in these requests; the cooperation helper supplies that known address from the fixture and does not test arbitrary entity resolution.
- Exact request lookup is a coverage control and fails on new wording. Claims of superiority cannot rely on beating it while ignoring centroid, ridge, nearest, or the exact-project store; these stronger controls are present and often outperform or match the parameter system.
- All methods use the same twelve public executable operations. Payloads and independent goldens make wrong selections genuinely consequential, but the models do not invent implementations. This is finite instruction classification and new binding storage, not unrestricted semantic or procedural memory.
- The corpus is authored by one coding assistant, with only three test payload fixtures reused per skill and twelve predefined operation classes. The protocol correctly rejects treating different wording, seeds, revisions, or repeated timing trials as independent populations. No general-memory claim follows.
- The declared wording-overlap audit is now persisted in [WORDING.json](analysis/WORDING.json), with a nearest-training-query record for each of the 72 test requests. It reports zero exact normalized text matches, maximum token Jaccard overlap 0.38461538461538464, and mean per-test maximum overlap 0.2044533101556955. This is a post-run descriptive audit produced by [report_analysis.py](analysis/report_analysis.py); no training, data selection, or model selection uses it. It documents lexical overlap on this authored corpus, and does not establish semantic independence, independent authorship, or a new held population. The separately persisted [oracle routing diagnostic](analysis/ROUTING_DIAGNOSTIC.json) likewise uses held labels only for explicitly marked post-run diagnosis, not as deployable input or measured system improvement.

## 7. Smallest necessary next corrections, in order — not implemented by this audit

1. **Make promotion compare with the deployable ordinary baseline envelope and preserve availability accounting.** A parameter-family winner is insufficient. Keep the current failed selection and unserved stages visible. Specify a current-source exact/retrieval fallback or an independently valid skills-only release for rejected updates; do not serve the stale mixed-parameter artifact as a shortcut.
2. **Obtain a fresh, disjoint held set and a more informative retention/calibration contract.** The present test has already informed diagnosis. Validate new project names, novel source bindings, independently authored requests and independent payloads before changing the gate or claiming improvement. Include per-skill/current-binding retention and report uncertainty; lowering the existing floor to publish the failed candidates would not close the problem.
3. **Use the completed post-run routing diagnosis to prioritize a fresh comparison of routing and score combination.** The saved oracle-group predictions already quantify a diagnostic gap on the fixed checkpoints; they must remain oracle-only. Evaluate any proposed routing or cross-group scoring correction against parent logits and ordinary controls on fresh held data, with router work and proposal cost counted in every arm. This improvement has not been implemented or established by the existing diagnostic, and should precede adding more cells or calling low gradient conflict a value signal.
4. **Make continuous updates preserve unaffected behavior under a matched budget.** Compare the current full replay policy with isolated binding heads or source-scoped cells while holding data access, presentations/compute, and retrieval fallback fixed. Check original skill retention and corrected/unchanged project behavior separately. These are proposed experiments, not delivered results.
5. **Complete the remaining evidence contracts before scaling claims.** Preserve the completed wording audit as post-run descriptive evidence; measure per-method RAM/update/source-ingestion costs and realistic request/update ratios if an economic claim is sought. Treat cross-machine state continuation and generic substitution as engineering validity evidence until fresh task results establish additional capability or utility.

## Evidence identities

- `run/RESULTS.json` SHA-256: `dcbb5ae23040a5fc637d96ab3b1b686c91ca93f4917c3944f6c51ff0fffba405`.
- `run/seed-1237/SELECTION.json` SHA-256: `17805e877186b7a453b2738170e23142dfd74b0a02ea70087bfe310060439c3f`.
- `provenance/RESULTS.json` SHA-256: `c0bcd961c6af7e16f455d1db8a74f9b39fe0da68b3adc7d258a06471758f3fc2`.
- `cooperation/RESULTS.json` SHA-256: `f6e15e7c027b3496295131e189e1f8a3f9997c4fd47a6b1e3c631e589801ce28`.
