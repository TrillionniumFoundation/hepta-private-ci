# Execution-aligned control repair

This is a prospective implementation. The `advance_20261026` experiments,
qualification thresholds, negative results and original agentd owner stay intact.

## Stage 1: finite execution and complete-policy calibration

`execution.py` compiles ordered owner ticks, actual admission, complete state
identities, remaining resources and joint cost/outcome branches into the existing
finite Bellman solver. Screening costs are paid even on refusal; branch costs
remain inside the exponential expectation. `Action.reserved` is a minimum
upfront reservation; realized resource use is separately debited, and an actual
overrun must terminate as a charged refusal. Numeric native action ties follow
candidate order. Empty feasible sets are failures, not invented retained output.

`attach_observations` consumes `evidence.joint.JointObservationLaw.forecast`.
Every positive-mass event needs an explicit conditional owner/cost law. Set each
successor's `evidence` to `observation_digest(row)` and pass `states=...`; the
payload and posterior must match. These are checks on supplied declarations,
not proof of host isolation, state sufficiency or a fitted future resource law.

`calibration.load_native` reads a complete declared census of original owner
episodes and scores. Acquisition confidence targets actual terminal success
after posterior update, later owner admission and delivery. A later refusal is
zero, even when the initial confidence was high. Fitting/evaluation reject
shared writer, speaker or source bytes and changed execution identities.
Changing the calibrated admission rule requires a new frozen-pair actual replay;
the candidate mapping does not qualify itself.

## Stage 2: actual native entry and receipt import

`native_adapter.run_current_only` calls the original H1/fixed_initial owner and
media lifecycle with a checked binary identity. It does not acquire evidence or
depend on an unknown future-owner forecast. `measure_complete_policy` executes
the original dynamic/fixed_late continuation in qualification-collection mode;
its outcomes can supply complete-policy labels, but its future model is still
unqualified. Both are new opt-in run entry points, not production activation.

`import_decision` checks actual candidate scan order, owner sequence, eligibility
continuity, checkpoints, admission masks and selected actions. The imported
current mask can feed `current_terminal_backup`, which checks the resulting
action and moment against the native endpoint model. An acquisition candidate
without a supplied future-owner law is rejected. Native CPU, wall and allocation
costs stay measured separately; no economic conversion or host-wide SLA is invented.

## Evidence and remaining work

`VERIFICATION.json` reports independent leaf enumeration of 248 whole policies
over 64 finite models and consequential refusal/cost counterexamples. Its
finite-environment execution and terminal-label fixtures are not native runs.
`NATIVE_READINESS.json` verifies the exact original agentd owner source hash and
the importer negative controls. The exact later native binary/dependency and
weight/calibration/host closure has not been recovered; actual native execution
and fresh policy-specific qualification therefore remain pending. Another
task's compiled library is not substituted for the missing pinned objects.

Reproduce from the repository root with `python -m
experiments.multimodal_output_portfolio.repair_20261026.control.verify --output
/tmp/control-new-run.json`. For the native source/import checks, run the
`control.verify_native_adapter` module with `--repository` and a new `--output`.

## Stage 3: original-neuron feedback mechanism

`neuron_feedback_probe/README.md` documents a separate new run using the exact
original `sparse_tick` kernel and real delivered text/PNG/WAV/AVI files. It tests
numeric, zero, shuffled, same-information history and between-tick checkpoint
reset pathways on 256 paired synthetic cases. Reset changes 164 continuation
actions; numeric improves mean return by 0.076875 over zero/reset but is exactly
tied with the strong history control. The external raw archive's complete
manifest, identity, and independent native replay/media-readback audit are under
`neuron_feedback_probe/evidence`.
This supplies actual original-neuron state mediation evidence without resolving
the separate owner execution closure: all receipts remain DENY_ALL and require
calibration. The fixed kernel is not trained; only its downstream state readout
receives gradient updates. No full NDU or natural multimodal claim is made.
