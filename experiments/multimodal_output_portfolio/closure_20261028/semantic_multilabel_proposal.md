# Proposal only: a separate full-window multi-label natural task

Status: **not a registration, not an active run, and not a replacement for the current v3 study.** The v3 source allocation, selected event labels, scoring rule and two independent 60% top-1 adequacy gates remain unchanged. No development, calibration or qualification prediction was used to write this proposal.

## Why distinguish this task from the current one?

The training-only annotation audit found that 17.96% of observer-training windows contain more than one action label and 74.34% contain more than one sound label, using a 0.15-second overlap rule and equal total weight per original video. The corresponding generator-training fractions are 21.09% and 77.34%. Every currently selected label still occurs in its target window. These observations establish label multiplicity; **they do not establish a ceiling on top-1 accuracy**, prove a model incapable, or justify treating a negative experiment as a software failure.

The current observer predicts the one label selected by the frozen event-allocation procedure. A full-window task would instead describe the annotated contents of the complete two-second target. That is a different supervision and reward definition and must receive its own source/task/observer/continuation/profile identities. Its scores cannot be substituted for the original single-label scores or described as passing the original gate.

The diagnostic is reproducible from `semantic_training_window_audit.py` and `TRAINING_WINDOW_AMBIGUITY_V3.json`; it uses the unchanged official training annotation archives and v3 source protocol `ad58bf5529af473f722c8e48a44f34ae07e364356b664a3a79458fecf1405b9d`.

## Freeze the ontology and annotation interpretation independently

A proposed new task contract would preserve all 63 published action IDs and all 17 sound IDs. The contract would pin the original annotation ZIP bytes, the complete ID-to-template dictionaries, the target-window rule, the exact overlap calculation, and the label-set construction implementation. The terminal observer must load this contract independently of generator metadata. Both checkpoint metadata and in-memory class order must agree with it.

One concrete rule to evaluate before registration is: a label belongs to a target if any official interval for that label overlaps the real, unpadded target window by at least 0.15 seconds. Repeated intervals for the same ID contribute one set member. All sound annotations satisfying that temporal rule would contribute to audible-content supervision; `is_visible` would remain a separate annotation, not a reason to omit an audible sound. The rule must be applied to every frozen source without filtering by model performance, label count or difficulty.

Absence from an annotation list means "not annotated under this contract." It must not be presented as a proof of physical absence unless the publisher's annotation scope supports that stronger statement. Before registration, the study must verify that scope and state how incomplete or uncertain annotations enter precision estimates. If negatives are not adequately annotated, the corresponding precision or hallucination claim remains blocked.

The manifest would store the full action and sound sets for every target, the underlying annotation IDs and intervals, and their SHA256. It would also retain the original single selected label, allowing the old task to be reproduced unchanged. The new label-set fields would live in a separate manifest; historical v3 receipts would not be rewritten.

## Independent observer training and an adequacy test that penalizes extra labels

The action and audio observers would predict sets rather than one class. Their fitting sources must remain disjoint from generator fitting sources. Reusing the already allocated training cohorts is permissible if disclosed; it does not create new independent evidence. A concrete initial family could use the same pinned S3D/TSM/PANN features with multi-label heads trained from complete training-window sets. Any head architecture, class weighting, threshold grid, tie rule and stopping budget must be registered before new development predictions. Thresholds are frozen using training/development only.

For a target set `Y` and predicted set `P`, each scored window would have:

- Precision: `|P ∩ Y| / |P|`, with an empty prediction scored zero whenever the target is nonempty.
- Recall: `|P ∩ Y| / |Y|`, with the empty-target convention explicitly fixed before allocation.
- F1 and Jaccard as complementary set-agreement measurements.
- False-positive counts and rates for every published class, including classes absent from fitting data.

Metrics would first average over retained windows within each original video and then weight videos uniformly. All vocabulary classes and their support counts must be reported; unsupported classes must not be silently removed from capability claims.

A proposed minimum point gate would require **both precision and recall at least 0.60 for each modality**, and an F1 improvement over a strong training-only constant-set/frequency baseline. Predicting all labels cannot pass merely by obtaining recall one: its precision, extra-label errors and baseline contrast remain explicit. Predicting no labels cannot pass on a cohort with positive targets. The study must report all four primary modality/metric outcomes, not select the favorable one.

This would be a *new* gate, not a mathematical translation of the old top-1 gate. If a future population-accuracy claim is intended, sample size and simultaneous one-sided confidence requirements must be registered separately; an empirical 60% point estimate alone does not provide that guarantee. The initial proposed sample count for a new observer calibration is at least 128 original videos, subject to a metadata-only availability census and a declared precision analysis before any prediction is opened.

## Same-event joint evaluation

Text should make an explicit, parsable statement about the action and sound sets within this same window. A fixed public renderer can produce a caption from predicted sets. Extra text claims count as false positives, and omitted reference claims count as false negatives. A free-form-language variant would require its own independently validated parser or observer; the set renderer would not establish general language-generation capability.

Video and audio observers must run again on the actual serialized, reopened output bytes. Cached target features cannot substitute for generated-media observations. Text/output agreement and each output/reference agreement should both enter the terminal report: agreement between jointly wrong outputs is insufficient. Reconstruction against the same source window supplies a separate instance-specific constraint beyond broad category labels.

The image remains a frame reconstruction and image/video consistency measure unless an independently calibrated image-semantic observer is added. A video's action label is not automatically an image-semantic certificate.

Temporal overlap and common source-window identity establish annotated co-occurrence. They do **not** prove that a particular action caused a particular sound. Any causal claim or fine temporal-alignment claim requires additional labels and an independently tested localization observer.

Predeclared mismatch controls should physically pair a video's output with another source's audio or caption and rerun the same complete scoring path. The permutation must be fixed from source IDs before scores are known, with no choice of especially easy negative pairs. Negative-control effects should be reported across the complete allocated cohort. They should not be optimized on qualification data or used to remove difficult sources.

## Isolation from previous studies and required new sources

No new run is registered by this document. If this proposal is accepted later:

1. Preserve the complete v3 study, including any negative adequacy or efficacy result.
2. Give the new task its own directory, source manifest, label-set schema, observer freeze, emission law, runtime contract and NDU profiles. The same numerical gamma does not make two different rewards the same profile.
3. Reuse training/development sources only with explicit prior-use records. Any source whose predictions informed a design decision is development evidence, not fresh qualification.
4. Allocate fresh observer-calibration, selected-policy-calibration and qualification sources after excluding historical 112 natural sources, the 16 separately allocated host-calibration sources, all 1,024 current v3 allocations, and any other subsequently registered source. Compare original-video byte hashes in addition to IDs. Participant independence remains unproved unless the dataset supplies that identity.
5. Select new holdouts by a frozen, outcome-blind source algorithm. Do not select sources with only one label, easy classes, favorable predictions or high observer confidence. If the untouched source inventory is insufficient, report that limitation rather than recycling consumed qualification.
6. Freeze every generator checkpoint, actor, observer, ontology and threshold before new qualification. Use paired source order and explicit control policies. Preserve full physical outputs and complete costs.

For continuity with the current design, a subsequent resource proposal could use the same 256 generator-training and 512 observer-training videos, the already used development cohort, and fresh cohorts of at least 128 observer-calibration, 64 selected-policy-calibration and 64 qualification videos. These counts are a planning proposal, not selected IDs or authorization to access new holdouts. The availability census and uncertainty requirements may require a larger cohort or may make the plan infeasible.

## Generator and objective consequences

A multi-label text head changes the stochastic emission law. Independent Bernoulli label draws conditional on the shared state are one explicit normalized option. Empty or excessive sets remain outcomes with their registered costs and scores; rejection sampling or hidden retries cannot be introduced without accounting for their normalization and execution. A deterministic thresholded baseline is a separate declared law. Continuous media emissions, shared transitions and encoder paths remain trainable, while strong interpolation, frozen neural and mean-objective controls must be rerun under the new common evaluation profile.

The terminal utility must freeze its reconstruction, semantic precision/recall and cross-modal agreement weights before any new qualification. The selected-action critic must fit moments of complete actual returns for this new actor/generator/observer combination. Calibration of the previous single-label policy does not transfer automatically.

Physical CPU still has no enforced future upper bound in the present runtime. Changing label semantics does not close that tail-certificate blocker, prove a globally optimal portfolio, or resolve the conditional-exogeneity assumption used by the likelihood-ratio timing gradient.

The next decision is therefore whether complete-window set supervision is the intended scientific task. A negative result under the original single-label target remains a valid negative result under that target, even if the alternative later proves more useful.
