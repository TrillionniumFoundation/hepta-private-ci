# Answer repair protocol CI

The dedicated source-head workflow runs only the six manufactured optimizer
contracts and three native input/output guards. Each suite has its own minimum
non-skipped count and source-bound execution/log receipt. The workflow uses
NumPy 2.3.5 and does not install Torch, read private labels or repeat the real fit.
It also checks formatting/fatal Python errors and retains external logs as an
artifact. A queued workflow is not a passing qualification.

The real native fit remains the separate historical run reported in
ANSWER_REPAIR_RESULT.md. Its later read-only capacity check verified four unique
states in each of the 40 sources and equal raw/encoded state counts; this check
performed no additional training or future evaluation.

The standard repository `just fmt` recipe passed for the four repair Python
files without changing their bytes, using an isolated checkout and the actual
already-installed locked Ruff 0.15.13 distribution. No shim was used. The first
offline attempt failed because its new environment lacked that package; it is
retained as a failure rather than relabeled successful. This changed-file check
is not a full-repository formatting certificate.
