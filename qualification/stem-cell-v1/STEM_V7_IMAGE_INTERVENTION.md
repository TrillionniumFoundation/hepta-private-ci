# V7: frozen-Head real image interventions on original ScienceQA source

**Status:** DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. Original target `main@f8c9419df6ddeb36ff8b522a50219981fb8d9345`; PR #2485 research branch only. No production model, NDU, CNS, permission, Memory, Cell Split, FinalUse, or main modifications.

## Scientific problem

Earlier real physical Granite97 + DINOv2-small ScienceQA E3 produced 64 historical TEST examples: text-only 17/64, train-gated text+image 24/64. These results are source-bound but the original posthoc six-way corrected paired p is 1.0 and visual necessity has not been human adjudicated. The V6 numerical margin audit showed that many output flips were near ties. A probability-margin simulation cannot answer whether the model actually uses relevant image content. This V7 **physically** tests changing visual evidence while keeping the exact same question, four choices and already-fitted TRAIN-only gate.

## Frozen lineage and intervention protocol

Original pretrained experiment: PR #2173, frozen HEAD `2dc43da7d9bf343acc871219ddce44d0e14d8911`. GitHub Actions original #38678847948, archive #11947722496 SHA256 `f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30`, TEST prediction SHA256 `e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7`. Original publisher `lmms-lab/ScienceQA-IMG@b9984af01798586705cee1fbdfa80a6dcbef04f1`, 96 TRAIN / 32 CAL / 64 TEST. Source/fit/held SHAs are hard-coded from the independent V5 publisher-data audit.

Original model source is checked out read-only and byte-pinned: stock Granite embedding 97M R2 `@835ad14087e140460703cf0fae09f97d469d65c2` and DINOv2-small `@ed25f3a31f01632728cabb09d1542f84ab7b0056`. The producer physically computes the unchanged text and image features once for all cases with exact original E3 functions; before intervention, it reruns the original 80-step TRAIN-only ridge/gate producer and **requires all 64×8 original four-class output vectors to reproduce the historical model predictions within 0.002 with zero class flips**. The source and TEST labels are not passed into fitting. This is an intentionally strict negative gate; failed cross-host numerical parity is a reported failure, not silently repaired by changing tolerances.

A separate, independent implementation refits the exact same TRAIN-only 147,840-scalar ridge bridge and 769-scalar Gate (another 80 updates). It must yield *identical train-parameter SHA values to the original re-executed source on that SAME host* and the correct-image Gate output must match original current-run probabilities within 1e-5 with no flips. Historical across-host **weight SHA equality is recorded, not falsely required** if numerically equivalent outputs are attained.

The 64 sealed **intervention** rows use the same model/head weights, same text question, same four choices, same source id and same original TEST cohort. Predeclared arms:

1. `correct_image`: genuine original DINOv2 embeddings paired with their own question.
2. `other_group_image`: an original **genuine DINOv2 image feature** from the next TEST source under ascending SHA ID, with different image group; source mapping is a fixed derangement established without held labels. This performs genuine **feature-level re-pairing**, **not a new DINO forward per swapped pair**.
3. `black_image`: an actual **additional physical DINOv2 forward** on explicit 224×224 black RGB PNG, then the SAME trained bridge and Gate applied to each TEST question; it is a content-occlusion control, not equivalence to a missing-image input.
4. `text_only`: exactly the old text control; its probability bytes/argmax must match the original rerun.

Every arm incurs the actual frozen Gate prediction forward with no training or reselecting parameters. The physical runner records actual original text/vision forward-batch counters, mask forward count (=1), duplicate-check TRAIN steps, per-case masked/mispaired original source IDs, model byte identities, observed wall time and all 4 probability vectors. No raw images, source text, held labels, private model weights or model snapshots are uploaded. The per-case record may contain public source digest IDs but never confidential prompts.

## Independent outcome process

Only AFTER the producer has sealed its complete, unlabelled 64-case result, a distinct reviewer process opens the original TEST label file, validates exact original source+label SHA and 64 distinct image groups, **independently derives the prescribed derangement**, recomputes source/model/prediction origin binding and original history parity, joins all four scores, and computes independent accuracy/NLL and preregistered paired exact McNemar/three-comparison Bonferroni against `correct_image`. No missing/failed original is silently reduced from 64. Unknown target-bearing prediction fields, false producer/authority claims, wrong group, missing mask forward, incomplete source lineage, changed model revision, non-finite probabilities or incorrect baseline results reject.

## Actually executed now vs pending

Locally executed in the isolated tool container (NOT on production/dot): six normal and six Python `-O` adversarial/test methods pass, including two independent physical 384D rank/SGD training executions on explicitly synthetic features, source-mismatch and label-injection denial, and a 192-source positive independent TEST reviewer with independently held synthetic labels. This **does not load pretrained weights or original ScienceQA images**. Python compile checks and YAML parsing also passed. Original V2/V3 true Granite97 model/4096 Head numeric, V4 real BANKING77 independent source, V5 original 64-case publisher labels and V6 original model margins all passed in previous GitHub Actions exact-HEAD run; the new V7 physical image intervention must finish on its **own SHA** before any causal-data claim.

The new CI workflow has exactly two jobs: (a) source-only Torch CPU negative tests, (b) same-repository-only physically executed frozen public models, original source/label integrity, two same-host fitted parameter replays, actual black-image DINO inference, fixed-image-group swaps, and separate postseal reviewer. This is a matched retrospective intervention, not prospective human-certified image necessity.

**Not established:** independent human visual-necessity ground truth, three prospective future windows, real 4096 learned Cell benefit, equal full-lifecycle 421M comparison, production governance, multi-modal generation, Cell Split/NDU System2 efficacy, external model issuer signature or machine/GPU attestation. Original historical and newly re-executed model inputs remain separate; action is strictly read-only, outputs `DENY_ALL`. Never merge/main select on V7 source-only green.
