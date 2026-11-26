"""Real fitted source and reader Cells, with fictional delivery and participant identity."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

from . import adoption, data, paired_consumer_run, paired_intake, test_paired_consumer
from .online_v4.test_circuit_bundle import setup_fixture


def registered_fixture(root):
    req = setup_fixture(root)
    for arm in ("parent", "candidate"):
        bundle = req[arm]
        bundle["consumer_cell_training_receipts"] = {
            key: data.digest(
                adoption.read_json(
                    root / model["runtime"]["adapter_directory"] / "TRAINING.json"
                )
            )
            for key, model in bundle["models"].items()
            if model["runtime"].get("adapter_directory")
        }
    req["candidate"]["parent"] = data.digest(req["parent"])
    # This is a new enrollment and a new freeze over the added source bindings.
    return req


def exercise(destination=None):
    case = test_paired_consumer.LocalUseTests()
    try:
        with patch.object(test_paired_consumer, "fixture", registered_fixture):
            case.setUp()
        launch = ("fixture-pid", "unused", case.route)
        released = adoption.read_json(case.home / case.admission / "paired.json")
        for text in ("train", "1", "keep", "later"):
            with case.assertRaisesRegex(ValueError, "known prompt or effective input"):
                paired_consumer_run.encoding(released, {"input": text}, case.models)
        task = {"input": "train later"}
        td = data.digest(task)
        input_scope = case.local("request-scope", td)
        delivery = data.digest("fictional circuit request")
        test_paired_consumer.put(case.inbox / f"consumer-task-{td}.json", task)
        case.event(input_scope, delivery)
        if destination:
            shutil.copyfile(case.route, destination / "request-fixture-event.json")
        run = case.local("run", td, delivery, *launch)
        case.assertEqual(
            case.local("verify-request", td, *launch)["run_receipt"], run["run_receipt"]
        )
        op = case.home / case.admission / "consumer" / run["operation"]
        pred = adoption.read_json(op / "worker-output.json")["prediction"]
        trace = pred["circuit_trace"]
        nodes = trace["nodes"]
        case.assertEqual([n["cell_id"] for n in nodes], ["source", "reader"])
        case.assertEqual(trace["graph"]["edges"], ["answer"])
        case.assertEqual(trace["cost"]["model_calls"], 2)
        case.assertEqual(trace["cost"]["verifier_calls"], 0)
        case.assertEqual(
            nodes[1]["request"]["messages"][-1],
            {"role": "tool", "content": nodes[0]["output"]["answer"]},
        )
        case.assertEqual(nodes[1]["output"]["answer"], pred["answer"])
        case.assertEqual((op / "answer.utf8").read_bytes(), b"1")
        for damage in ("route", "edge", "output", "slot"):
            wrong = deepcopy(pred)
            altered = wrong["circuit_trace"]
            if damage == "route":
                altered["route"]["graph_id"] = "substituted"
            elif damage == "edge":
                altered["nodes"][1]["request"]["messages"][-1]["content"] = "changed"
            elif damage == "output":
                altered["nodes"][1]["output"]["output_ids"] = [0]
            else:
                altered["nodes"][0]["output"]["loaded_model_digest"] = data.digest(
                    released["parent"]
                )
            with case.assertRaises(ValueError):
                paired_consumer_run.inspect(released, task, case.models, wrong)
        material = b"fictional circuit downstream acceptance"
        effect = paired_intake.sha(material)
        (case.inbox / f"consumer-effect-{effect}.bin").write_bytes(material)
        outcome = case.local("outcome-scope", td, effect, "accepted")
        report_event = data.digest("fictional circuit outcome")
        case.event(outcome, report_event)
        if destination:
            shutil.copyfile(case.route, destination / "report-fixture-event.json")
        result = case.local("report", td, effect, "accepted", report_event, *launch)
        case.assertEqual(result, case.local("verify", td, *launch))
        case.assertFalse(result["payment_authorized"])
        case.assertEqual(result["evidence_scope"], "engineering_fixture")
        if destination:
            shutil.copytree(case.root, destination / "original")
            test_paired_consumer.put(
                destination / "SUMMARY.json",
                dict(
                    scope="engineering_fixture",
                    real_participants=0,
                    payments=0,
                    admission=case.admission,
                    run=run,
                    report=result,
                    checked_distinct_prior_inputs=["train", "1", "keep", "later"],
                    rejected_corruption=["route", "edge", "output", "slot"],
                    cold_circuit_nodes=len(nodes),
                ),
            )
    finally:
        case.doCleanups()


@unittest.skipUnless(
    sys.platform == "linux" and test_paired_consumer.NUMERICAL,
    "Linux coding CPU profile required",
)
class SubsequentCircuitTests(unittest.TestCase):
    def test_real_fitted_route_relay_and_signed_fixture_readback(self):
        exercise()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        root = Path(sys.argv[2])
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        exercise(root)
    else:
        unittest.main()
