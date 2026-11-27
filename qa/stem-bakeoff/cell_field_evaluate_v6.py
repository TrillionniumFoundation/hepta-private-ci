"""V6 policy identities over the unchanged closed V5 statistical inference core.

Only names and the declared cost scope change. All source pairing, bootstrap
draws, numerical margins, completion eligibility and finite-output gates are
computed by the already frozen implementation, with no row selection.
"""

from cell_field_evaluate_v5 import (TASKS, HEADS, SEEDS, SPLITS,
    evaluate_probabilities as previous_evaluate, evaluation_protocol as previous_protocol)


POLICIES = ("zero", "myopic_h1_repaired", "loss2_h8_repaired", "adjoint_h8_repaired",
            "future_field_h8_repaired", "response_h8_guarded")
CANDIDATE = "future_field_h8_repaired"
BASELINES = ("myopic_h1_repaired", "loss2_h8_repaired")
REQUIRED_COMPLETION = (CANDIDATE, *BASELINES)
TO_PREVIOUS = {"zero": "zero", "myopic_h1_repaired": "myopic_full_h1", "loss2_h8_repaired": "loss2_h8",
    "adjoint_h8_repaired": "adjoint_h8", "future_field_h8_repaired": "response_h8_guarded",
    "response_h8_guarded": "myopic_guarded_h1"}
FROM_PREVIOUS = {value: key for key, value in TO_PREVIOUS.items()}


def translate(value, names):
    """Replace exact policy identifiers; preserve arrays, numbers and all rows."""
    if isinstance(value, dict):
        return {names.get(key, key): translate(item, names) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [translate(item, names) for item in value]
    return names.get(value, value) if isinstance(value, str) else value


def evaluation_protocol():
    plan = translate(previous_protocol(), FROM_PREVIOUS)
    plan.update(policies=list(POLICIES), candidate=CANDIDATE, primary_future_baselines=list(BASELINES),
        required_completed_policies=list(REQUIRED_COMPLETION),
        cpu_scope="own response construction, solver, all prospective trials, exact per-step repair and committed transitions; identical output/evaluation I/O separately reported")
    return plan


def evaluate_probabilities(probabilities, labels, components, protocol, costs):
    plan = protocol.get("evaluation", protocol)
    if plan != evaluation_protocol():
        raise ValueError("V6 closed family, unchanged margins or matched completion policy changed")
    previous = previous_evaluate(translate(probabilities, TO_PREVIOUS), labels, components,
                                 previous_protocol(), translate(costs, TO_PREVIOUS))
    result = translate(previous, FROM_PREVIOUS)
    result.update(schema="hepta.cell-field-fresh-evaluation.v6",
                  inference_implementation="unchanged frozen V5 numerical core with explicit bijective policy-name mapping")
    result["bootstrap"].update(plan)
    return result
