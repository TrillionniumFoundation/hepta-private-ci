# Additional E4 controls, frozen before actual model use

The original E4 code compares a two-call F/F control with four graph arms and five resource/message removals. It cannot establish that T/F or C/F exceeds the strongest available single model. Its fixed-seed random graph is also a single graph for the whole panel.

This addition reuses the original `SharedAdapterPool`, `fit_router`, `evaluate_suite` and `run_graph`. It retains the original six-candidate A-only search and adds the following controls:

- T/T and C/C each receive their own first answer and the same stable verifier feedback. F/F is reused from the same run's original arm. All three singles are reported; no winner is selected on B.
- A best-static graph is selected from the complete A search matrix by utility sum, with a graph-ID tie break. Its selection receipt is written before either evaluation panel.
- A new random control uses a frozen seed plus task identity to draw from exactly the learner's six graph candidates.
- A Cell identity control replaces every non-F slot in the learned route with F, preserving edges and two calls. F/F no-ops are explicit and still executed.
- Each result separately retains selected success, first and last success, 0-to-1 recovery and 1-to-0 regression. Verifier-assisted retention of an earlier success does not erase a later regression.
- Before using an original route for replacement, the frozen router verifies its input-feature digest and chosen graph. That extra routing computation has a retained cost receipt.

The original Cell-removal arms remain resource-removal diagnostics: they use zero or one call when the removed Cell occurs. They do not establish Cell identity necessity at equal computation. The original fixed-seed random graph remains an older control, separate from the new per-task random routing.

## Execution scope and cost

The complete successful path plans **306 model calls and verifier opportunities**: 72 for A search, 144 for the original suite and removals, and 90 for the additional controls. These are planned counts until actual receipts exist. Format rejection may reduce actual business executions.

One shared pool serves all inference. Search, every original/intervention call, additional control calls, route validation, pool initialization and whole-worker time must be retained. Nested wall-time scopes are not additive. Equal caps do not assert equal actual cost, and unknown energy or money stays unknown.

The separate operational freeze binds the new code, unchanged original B comparison, source closure, runtime, Run02 F/T/C adapters and old A6/B3 tasks before inference. This PR does not alter the original 27-module B source or comparison. It does not use the newly trained E2 adapters.

The nine tasks remain exposed development tasks with zero independent-sample increment. All arms have zero retrieval opportunities in this profile; a retrieval-augmented baseline has not run. TT/CC supplement the controls and are not added to the learner's six-graph search.

## Verification

Six CPU tests pass using scripted providers and the actual repository verifier. They test self-repair inputs, equal-call replacement and absent-edge preservation, paid no-ops, visible late regression, A-only selection, task-bound random routing and rejection of a misbound route before model calls. They are engineering evidence, not model capability evidence.

Required `just fmt` completed successfully. The two modules' ASTs were unchanged; the extract in `FORMAT.json` identifies the retained original formatting receipt.
