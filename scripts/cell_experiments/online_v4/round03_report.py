"""Read actual worker artifacts; absent output stays unknown, never a zero."""

import json
from pathlib import Path

from .reporting_v4 import MODES, aggregate, count, digest, require, sums


def report_directory(directory):
    directory = Path(directory)
    missing, unreadable = [], []

    def read(relative):
        path = directory / relative
        try:
            if not path.is_file():
                missing.append(relative)
                return None
            return json.loads(path.read_text())
        except (OSError, ValueError, UnicodeError) as error:
            unreadable.append({"path": relative, "error": str(error)})
            return None

    e2 = {
        mode: {
            "freeze": read(f"e2/{mode}/FREEZE.json"),
            "result": read(f"e2/{mode}/RESULT.json"),
            "training": [
                read(f"e2/{mode}/round-{number:03d}/model/TRAINING.json")
                for number in range(2)
            ],
        }
        for mode in MODES
    }
    search = read("circuit/search/SEARCH.json")
    studies = {panel: read(f"circuit/old_{panel}/STUDY.json") for panel in ("A", "B")}
    result = aggregate(
        e2,
        search,
        studies,
        search_plan=read("circuit/search/PLAN.json"),
        study_plans={
            panel: read(f"circuit/old_{panel}/PLAN.json") for panel in ("A", "B")
        },
    )
    extras, errors = {}, []
    keys = ("model_calls", "verifier_calls", "input_tokens", "output_tokens")
    for mode in MODES:
        for phase in ("primary", "cold"):
            name = mode + "/" + phase
            value = read("evaluations/" + name + "/EVALUATION.json")
            extras[name] = {key: None for key in keys}
            if value is None:
                continue
            try:
                require(
                    value["schema"] == "hepta.round03-exposed-evaluation.v1"
                    and value["status"] == "COMPLETE"
                    and value["mode"] == mode
                    and value["phase"] == phase
                    and value["independent_sample_increment"] == 0,
                    "evaluation scope/status differs",
                )
                require(
                    value["model_digest"] == e2[mode]["result"]["final_model_digest"],
                    "evaluation candidate differs from its actual E2 result",
                )
                steps = [step for row in value["rows"] for step in row["steps"]]
                observed = {
                    "model_calls": len(steps),
                    "verifier_calls": len(steps),
                    "input_tokens": sum(
                        count(s["output"]["input_tokens"]) for s in steps
                    ),
                    "output_tokens": sum(
                        count(s["output"]["output_tokens"]) for s in steps
                    ),
                }
                require(
                    observed == {key: count(value[key]) for key in keys},
                    "evaluation summaries differ from recorded steps",
                )
                extras[name] = {**observed, "receipt_digest": digest(value)}
            except (KeyError, TypeError, ValueError) as error:
                errors.append({"component": name, "error": str(error)})
    result.update(
        extra_exposed_evaluation_costs=extras,
        extra_exposed_evaluation_totals=sums(list(extras.values()), keys),
        extra_evaluation_issues=errors,
        missing_artifacts=missing,
        unreadable_artifacts=unreadable,
        extra_evaluation_cost_included_in_main_totals=False,
        shared_pool_initialization=read("circuit/POOL.json"),
        scope_note="Loop collection/post-update-A and Circuit costs are the main scope. "
        "Primary/cold repeated A/B evaluations are additional paid operations. "
        "Neither creates a new independent task; no missing receipt means zero cost.",
    )
    if missing or unreadable or errors:
        result["input_validation"] = "INCOMPLETE"
    return result
