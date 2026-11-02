# Review of the separate raw-data auditor

This is a code review of `audit/independent.py` during development, before new formal confirmation. It did not select models or inspect formal confirmation outcomes. The reviewer authored `diagnostics.py` and `quality.py`; their original checks remain author verification. The auditor was written by a different contributor, who also authored `statistics.py`. Consequently this is a separate calculation and an internal cross-review, not third-party authorship or new independent data.

The final reviewed auditor SHA256 is `b86b404dfe93402d4dabedef4de49b7316ae1539e40e828fd2da3db193202983`. The change from the previously reviewed version only updates its scope description from six to eight quality gates after actual-label Brier/ECE were registered; no numerical or validation logic changed.

## Formulas and evidence boundaries

The auditor imports NumPy, SciPy and Python standard-library modules. It does not import the project's task executor, teacher, model, diagnostics, quality or statistical summarizers. Its per-decision recalculation uses the retained prediction and teacher-target arrays, constructs the legal-action set independently, and checks selected-action Q error, squared error, teacher-belief error, teacher expected Brier score, regret, greedy ties, pairwise ranking and the three margin definitions. Illegal Q entries cannot affect the ranking or top-two margin. A tied teacher pair is excluded at the same declared tolerance; a prediction tie on a comparable teacher pair counts as a ranking error.

Actual-label Brier is recomputed separately from teacher-belief MSE and teacher expected Brier. Episode labels are checked against the corresponding evaluator file. Actual terminal reward is 0 for STOP, +1 for a correct submitted label and −1 for an incorrect submission. Actual utility subtracts the reconstructed action/latency charges. No teacher Q, posterior, expected return or structural terminal identity substitutes for the realized reward.

The primary analysis recomputes within-fit paired utility differences for both registered contrasts and both IID/OOD domains. Its sample size is the number of registered fits, not episodes or decisions. It computes the sample SD, standard error and four two-sided Bonferroni-adjusted Student t intervals, and tests whether each lower endpoint exceeds 0.02. An absent or invalid required arm makes its contrast null; it does not silently delete that fit. These are the same stated approximately normal independent-fit assumptions as the study, rather than a distribution-free guarantee.

Numerical comparisons use absolute tolerance 1e−12 plus relative tolerance 1e−10. File identity uses SHA256. They are distinct claims; numerical agreement is not reported as bitwise floating-point equality.

## Material issues found and corrected before confirmation

The first implementation trusted the episode's copied label, did not independently reconstruct every observable successor, and only verified paths listed by a seal. It could therefore miss a consistent corruption of the copied result or an incomplete declared manifest. These were reported to the author and root before any formal result.

The reviewed revision now reconstructs the initial state and every full task successor from public rules, executed action and retained completion. This includes read budget, pending source/due tick, delay, history, reliability, failed reads, repair, elapsed time, charges, terminal submission and pending cancellation. Before/after states, cross-decision continuity and final state are compared. A delayed READ cannot complete early or be omitted when due.

It now hashes all declared cohort files and independently constructs their expected inventory from each world's public/evaluator files and injected-missing packet mask. Existing packet hashes bind to public packet digests. Ground evaluator labels bind raw episode outcomes. It also requires all expected candidate/world combinations rather than accepting a surviving subset.

The final small revision also checks each episode's exact registered execution seed using its cohort ordinal and the IID/OOD offset, which binds paired world streams across candidates. Cell-family initial latent states must be 7, while accumulator/Bayes initial states must be 0. Terminal and cell-free steps cannot sample, change latent state, or assert event/recovery. Successful content receipts must match the actual packet byte length and the retained logits' first-two-coordinate argmax, including the zero-class tie rule. This verifies the retained receipt, not a fresh execution of the neural content model.

The training inventory is independently enumerated as exactly 50 paths per registered fit: 15 models, 15 training receipts, 15 attempt records, STARTED, FINISHED, training data, probe-training data and frozen decoder artifact. The exact fit-key sets are checked. Model family/head/factors/fit and the canonical returned-model hash are compared with receipt and attempt identities. The declared physical dynamics are required to be untrained. Frozen source keys include the inherited source inventory, all new top-level scientific Python files and the selected protocol; every present source byte is checked against the seal.

Training STARTED/FINISHED source identities, protocol, stage and fit are checked. Training process receipts bind to the seal, and confirmation requires its own STARTED/FINISHED, successful process receipt and absence of FAILED. Confirmation STARTED must follow the seal timestamp, identify the same seal/model publication and report that confirmation did not preexist. The remote-verification receipt hash, model commit and model-manifest identity are checked locally.

## Remaining limited claims

This auditor does not independently reimplement the learned policy network, content neural decoder, physical transition law or fitted teacher oracle. It checks recorded targets and predictions for internal consistency with outcomes and artifacts. A complete independent rerun of those models would require separate implementations and broader validation; the present report must not imply it occurred.

It also does not recompute exact numerical state fingerprints, complete sparse occupancy strata, calibration ECE, the eight combined quality gates or frozen ridge-decoder outputs. Those remain the producer's diagnostics and explicitly labeled author checks. The independent report's `limits` field identifies these omissions. An absence of violations within the auditor's scope cannot be used to claim that those unreviewed empirical gates passed.

The local receipt check is not a fresh remote readback. Root must retain the separate actual remote blob verification, seal-publication receipt and clean cold-restore evidence. Measured CPU truth and wall-time ordering are not cryptographically established by self-authored timestamps; the external wait4 records, source bindings and retained attempts provide narrower operational evidence. Nested candidate/diagnostic CPU must not be added a second time to inclusive worker CPU.

The final registered seed namespace has a separate auditor, `audit/seed_namespaces.py`; its design-time enumeration generates no future confirmation data. A final formal run of that audit must use the actual protocol without a planning override. Current development reuse must remain labeled development.

The code author supplied meaningful self-checks for Q/belief/actual-label separation, illegal-action margin masking, missing/invalid-fit null inference, delayed READ/failure/repair/submission, and intentionally corrupted numeric/successor records. This review did not create a duplicate test suite or treat author self-checks as formal confirmation. The formal byte and raw-outcome audit still has to be run after the frozen confirmation finishes.
