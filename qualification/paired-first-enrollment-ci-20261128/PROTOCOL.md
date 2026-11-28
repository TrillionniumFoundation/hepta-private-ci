# First-enrollment controls in the original architecture CI

The first-enrollment owner added by #7240 has four controls in the sibling
`deployment_issuer::paired::tests::enrollment` module. The original 33-control
exact enumeration and late-admission five-control filter do not select it.

This slice adds one five-line step to the existing qualification job. It uses
the existing `hepta_ci_exec.py`, `just test --locked`, original package/library,
zero retries, one test thread, four exact fully qualified names, and minimum 4.
All earlier steps, guards, source/merge identity and execution record rules stay
byte-identical. The original scope selector classifies the workflow change as
full scope, including effects and native; the step retains the existing
`run_native && effects` condition. A duplicate-tree base-merge lane may retain
the original native skip decision.

The four synthetic registry controls do not fit a model and cannot qualify a
real human, original Root process or useful training. Their execution status is
NOT_EXECUTED in this prospective source record. No workflow was manually
dispatched or rerun. Natural CI must supply the actual source, named results
and command receipt before anyone claims a pass.

The actual original `just fmt` ran successfully in an isolated exact-context
capsule. Its existing scoped formatter selected no code formatter for the
YAML-only edit and kept the workflow postimage unchanged. YAML parsing and
removal of exactly the new step reconstructed the original workflow object.
