# Prospective original-receipt readout

This analysis helper implements the already frozen primary-arm decision and does not change the training/evaluation source, models, tasks, budgets or original scores. It was written before either new arm was evaluated. It reads B3 only after both weights and all original evaluation owners are complete. It generates no model or verifier calls. Its source SHA is `71370d3c4aec806f857b59e8f32ebab50cf031f99a80777ee6730ffae785ebfe`.

The helper distinguishes current-policy first/final/any success, recovery and regression with their actual opportunity denominators, and the separate common-parent-prefix success sets. It enforces the original native-feedback primary decision on A and B3 and reports the document-evidence control without selecting a new winner. Every original request, output, verifier receipt and feedback remains available.

The accompanying archive retains the real source-format and blob-policy checks for exact execution source 02b3, observed metadata head 9160197, and training-admission head 78099. Original policy unit-test qualification was reused only after the four policy Git blobs matched exactly; no new unit test execution is claimed. Explicit Ruff formatting, final format check and lint of this new analysis helper all exited zero, with unchanged AST and no B3 reads.

The training launch receipt refers to one persistent terminal and one original-lock owner, using source/admission commit `78099aa6af4c70c00f26cb11888e20aa59510014`. It records submission, not completion. The training operation was not retried under another key.
