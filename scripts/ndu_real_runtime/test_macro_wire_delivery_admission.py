"""Adversarial *manufactured* macro receipt acceptance tests (not policy evidence)."""

import json
from pathlib import Path
import tempfile
import unittest

from .metacontrol_macro_contract import observe_branch, sha
from .test_macro_pair_fixtures import FixtureHost, plan


def case(root, actions):
    p = plan(root)
    p["profile"]["original_operation_id"] = "fixture-run"
    directory = root / "observed"
    host = FixtureHost(
        p["config"], p["pairs"][0]["case"], p["profile"], directory,
        training=True, exploration=actions,
    )
    result = host.run()
    return p["config"], directory, result


def mutate_actor(directory, change):
    path = directory / "launch.json"
    launch = json.loads(path.read_text())
    events = [json.loads(line) for line in launch["stdout"].splitlines()]
    if change == "late_ready":
        events = events[1:] + events[:1]
    elif change == "unexpected_event":
        events.insert(1, {"schema": "ndu.real.unsupported-event.v1"})
    elif change == "wrong_ready_case":
        events[0]["case_id"] = "UNRELATED_CASE"
    elif change == "text_delivery_mismatch":
        for event in events:
            if (
                event.get("schema") == "ndu.real.actor-observation.v1"
                and event["action"]["action"] == "WRITE_TEXT"
            ):
                event["action"]["arguments"] = {"text": "SYNTHETIC_UNDELIVERED_TEXT"}
                index = event["step"]
                trajectory = directory / "trajectory.json"
                saved = json.loads(trajectory.read_text())
                saved["steps"][index]["action"] = event["action"]
                trajectory.write_text(json.dumps(saved))
    elif change in {"callback_error", "protocol_error", "limit_reason"}:
        launch[change] = {"synthetic_error": change}
    else:
        raise ValueError(change)
    launch["stdout"] = "\n".join(json.dumps(event) for event in events)
    launch["host_exchanges"] = [
        {"event_sha256": sha(json.dumps(event).encode())} for event in events
    ]
    path.write_text(json.dumps(launch))


class MacroAdmissionTests(unittest.TestCase):
    def test_normal_manufactured_stop_and_read_macros(self):
        for actions in (
            ["WRITE_TEXT", "STOP"],
            ["PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "STOP"],
        ):
            with self.subTest(actions=actions), tempfile.TemporaryDirectory() as tmp:
                config, directory, result = case(Path(tmp), actions)
                out = observe_branch(directory, result, actions, 0.2, 0.01, config)
                self.assertEqual(out["actual_native_actions"], actions)
                self.assertEqual(out["quality"], 0.5)

    def test_forged_but_internally_consistent_receipts_rejected(self):
        for change in (
            "late_ready",
            "unexpected_event",
            "wrong_ready_case",
            "callback_error",
            "protocol_error",
            "limit_reason",
            "text_delivery_mismatch",
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                actions = ["WRITE_TEXT", "STOP"]
                config, directory, result = case(Path(tmp), actions)
                mutate_actor(directory, change)
                with self.assertRaises(ValueError):
                    observe_branch(directory, result, actions, 0.2, 0.01, config)


if __name__ == "__main__":
    unittest.main()
