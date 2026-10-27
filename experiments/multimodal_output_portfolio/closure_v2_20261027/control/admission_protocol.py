"""One fixed new-source qualification of post-codec semantic admission."""

from copy import deepcopy

from .acceptance_calibrate_v2 import SPEC as CALIBRATION


SPEC = deepcopy(CALIBRATION)
SPEC.update({
    "schema": "hepta.ndu.native-host-semantic-admission-qualification.v1",
    "qualification_id_pairs": 424,
    "qualification_ood_pairs": 600,
    "qualification_arms": ["native_numeric_frozen_selective"],
    "stopping_rule": "Exactly one1024-pair qualification; no threshold refit, calibration revision, interim stopping, repeated arms as independent samples, or test-driven cohort expansion",
    "native_policy": "Original owner, kernel, journal, witness and DENY_ALL unchanged; nonzero arrived scalar persists across a true process restart and two zero-input delayed ticks",
    "future_numerical_verification": "Before actual feedback, run and pay for all three native scalar branches; verify the realized numerical state and expiry/budget outcome against the matching branch",
    "kernel_cost": "50 executions per episode:16 API/branch ticks,24 forecast journal/ledger replay steps,10 cold-process recovery steps",
    "later_generation": "The existing native state/readout proposes swap; only live native admission and remaining generation budget permit an actual later encoder/transition/decoder call",
    "prediction_time": "After actual candidate PNG/UTF8 readback and already-arrived scalar, before final host confirmation and private candidate score",
    "prediction_scope": "A post-codec candidate probability and terminal commit/abstain value; not a claim to predict candidate pixels before they exist",
    "final_host_confirmation": "A separate user-authorized bounded research confirmation copies already-generated candidate bytes when semantic admission passes, otherwise writes an abstention receipt. It does not reopen an expired owner, authorize another neural generation, erase the initial delivery, or grant production capabilities",
    "same_deployed_policy": "Calibrated candidate is chosen by the identical frozen native readout, expiry and generation budget; the final host semantic rule is identical to calibration002",
    "full_cohort_ece": "Every candidate is graded after the host decision, including all abstentions; ECE full and ID use exactly the old ten ppm bins and candidate strict semantic event",
    "cost_scope": "Report actual Python/child CPU, wall, generations, public observer/readback, version verification, forecast and replay work; private external grading separately timed",
    "task_sunk_fee": {"kernel": .0001, "generator": .01, "initial_delivery": .002, "refused_neural_proposal": .005},
    "past_cost": "A common sunk cost shifts both terminal entropic actions equally; it is charged in realized and predicted total moments, not dropped from reported utility",
    "bootstrap": {"draws": 5000, "seed": 27207001, "confidence": .95, "unit": "one source pair, one arm"},
    "native_semantic_profile_replaced": False,
    "production_qualification": False,
})
