# Blinded B2: six new public-source function contracts

This panel is held apart from the A-only current-policy credit training. It has six newly authored literal-input test-completion tasks from three public repositories and three maintainer organizations, with no project overlap with the previous Hepta, Chain, Requests, Werkzeug or Click tasks. The complete original source files and licenses are retained at fixed Git commits. Each extracted function is the exact original AST range.

The task author built and checked this material in a separate directory. Before both new learner weights are frozen, the training constructor receives only the commitment hashes, counts and loader interface. Task prompts, reference assertions, source functions and verifier observations are withheld until the constructor reports both frozen weight manifests. This is operational blinding within a shared workspace, not an access-control boundary or authenticated independent evaluator custody. The subsequent release must preserve the original commitment and add a separate release receipt.

## Protocol and checks

`cell_experiments.blind_panel_v4.load_panel(directory=None)` returns six records using the existing prepared-v3 action protocol and unchanged `repo_patch` version 1 verifier. Each record is `split=confirmation`, `training_allowed=false`, `origin_kind=curated_development`, and `exposure=development`. The development labels retain the fact that these are authored requirements; the separate blinding record describes what the training constructor has seen. No field claims real user traffic or an independent evaluator.

All six authored references passed the real original function and rejected both constant-output controls. Six tautological assertions of the form `subject(...) == subject(...)` passed their original calls but rejected zero controls, and therefore correctly failed the semantic verifier. The construction used 12 verifier subprocesses and no model calls. Full observations and timing are in `prepared/REFERENCE_CHECKS.json`. The source retrieval also verifies the complete Git blob identity for every source and license.

The loader checks the committed catalog, prepared records, source-retrieval index, all source and license bytes, Git blob identities, exact AST extraction, record provenance and verifier fixture bindings before registering any fixture. Two engineering tests exercise valid admission and atomic rejection of changed source, license or record bytes. They passed before `just fmt`; formatting was run afterward without rerunning tests.

The subjects use only Python builtins and the existing verifier's `re` binding. Callable predicate arguments are outside this literal-input task and remain at their defaults. No third-party package code is imported by the six subjects, and no implementation, assertion grammar, verifier score or output-control mechanism was changed for this panel. The verifier itself has its existing NumPy import; the local runtime supplied that dependency.

## Limits

There are six task units, three source-file groups, three projects and three maintainer organizations. These are not six authenticated users. Project separation and withholding from this training run do not prove absence from base-model pretraining. The controls check that generated assertions observe differing outputs; they do not constitute a complete mutation test suite or full-repository integration test. References are curator-authored checks, not teacher trajectories or student experience, and are never authorized for training.

The panel was not selected by model success, and no model has been tried on its tasks during construction. Later model results belong in a separate execution receipt tied to the frozen weights and this original commitment. Negative or failed future evaluations must remain intact.

`INDEX.json` binds the construction artifacts. `COMMITMENT.json` is the disclosure-safe pre-release envelope. `PANEL.json`, `CATALOG.json`, source files, reference checks and this README are part of the withheld material until the weight-freeze handoff.
