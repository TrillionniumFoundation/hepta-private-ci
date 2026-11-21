# Stored-law continuation compilation

This source-only research stage compiles a checkpoint's own finite analytic law
into a closed policy automaton and checks whether local MLP action boundaries
can be ruled out under the existing parameter radius. It performs no parameter
update. The architecture remains 85 -> tanh48 -> 4 for the feasibility audit;
the compiled policy is a distinct inference-program candidate.

The retained protocol uses the five original fits, excludes all 3,456 historical
schedule keys, seals 20 new IID DEV worlds, and then seals 160 fresh CONF worlds
(16 per fit per domain). Four paired fit-level Student-t comparisons use df=4
and two-sided Bonferroni familywise 95% intervals. All four lower bounds exceed
the frozen 0.005 utility threshold: compiled-minus-original gains 0.118341 IID
and 0.172524 OOD; compiled-minus-prior-selected gains 0.112503 and 0.174423.
These are fixed-deadline endpoint utilities, not market returns. Five fits and
the t approximation limit generalization; entropy has no external custodian.

The 180 complete graphs contain 82,315 states. The selected-policy closures
contain 1,406 states, preserving every structural selected-action outcome,
including zero-probability branches. All actions, complete state transitions,
terminal updates and initial expected utilities match. Median state counts are
447 and 9. Median canonical JSON sizes are 422,038 and 6,021 bytes. The full
verification graph remains separately retained; serialized size is not RSS.

Necessary single-constraint radii do not establish simultaneous realizability.
All finite Q147 bounds and all conservative MLP4324 bounds are within budget;
fixed-belief terminal obstructions contribute little occupied action-gap mass.
This study does not prove either global impossibility or a feasible joint edit.

One scientific attempt and an independent arithmetic reader completed without
retry (77.82255 total child CPU seconds, excluding zero-forward preflight).
All original input pins and restored checkpoint bytes matched. No new gradient
training occurred. The old direct-edit and trained candidates are common-sample
references with unmatched historical construction budgets.

## Reproduction inputs

The private input archives are intentionally excluded. Restore their original
directory layout and explicitly set HEPTA_WSP_INPUT_ROOT before importing these
sources. Required siblings include neuron_margin_experiment,
neuron_full_mlp_experiment and neuron_causal_rescue_20261120. The capture-time
default path in the frozen compiler is retained to preserve its exact hash;
the environment override is the portable entry point.

Read DRAFT_PROTOCOL.md and CAPSULE_CONTRACT.md before creating a new experiment.
The original protocol digest is
697e314782e7c04b99049c9c67859b5390c3ad8f09bdcb258aab9eef60256523.
Its source, phases, failures and complete private record review are retained
with the research evidence. summarize.py is a later saved-record analysis,
not a new model evaluation. Unknown future costs or utility conversion leave
general NDU at KEEP_ORIGINAL_AND_STOP.
