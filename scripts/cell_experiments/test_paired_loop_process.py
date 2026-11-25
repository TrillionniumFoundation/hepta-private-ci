"""Complete bound CLI with actual frozen GPT-2 weights and fictional identities."""

import json
import sys
import unittest

from . import data, paired_intake
from . import test_paired_consumer as original


@unittest.skipUnless(
    sys.platform == "linux" and original.NUMERICAL,
    "Linux pinned coding CPU profile required",
)
class BoundLoopProcessTests(unittest.TestCase):
    setUp = original.LocalUseTests.setUp
    call = original.LocalUseTests.call
    event = original.LocalUseTests.event

    def local(self, *args, good=True):
        if args == ("select",):
            result = self.call(
                "paired_loop", self.home, self.admission, self.models, "identity"
            )
            self.loop_pin = json.loads(result.stdout)["loop_sha256"]
            return self.bound("select")
        return original.LocalUseTests.local(self, *args, good=good)

    def bound(self, command, *, good=True, **fields):
        args = [command, "--expected-loop", self.loop_pin]
        for name, value in fields.items():
            args.extend(["--" + name.replace("_", "-"), value])
        if command not in ("select", "readback"):
            args.extend(
                [
                    "--root-pid",
                    "fixture-pid",
                    "--sqlite-home",
                    "unused",
                    "--route",
                    self.route,
                ]
            )
        result = self.call(
            "paired_loop", self.home, self.admission, self.models, *args, good=good
        )
        return json.loads(result.stdout)["result"] if good else result.stderr

    def test_original_cold_selection_use_report_and_recovery_keep_one_identity(self):
        task = {"input": "train later"}
        task_pin = data.digest(task)
        original.put(self.inbox / ("consumer-task-" + task_pin + ".json"), task)
        request = self.local("request-scope", task_pin)
        delivery = data.digest("bound engineering request")
        self.event(request, delivery)
        run = self.bound("run", task=task_pin, delivery=delivery)
        checked = self.bound("verify-request", task=task_pin)
        self.assertEqual(run["run_receipt"], checked["run_receipt"])
        path = self.home / self.admission / "consumer" / run["operation"]
        self.assertEqual((path / "answer.utf8").read_bytes(), b"1")
        effect = b"engineering participant accepted the actual generated output"
        effect_pin = paired_intake.sha(effect)
        (self.inbox / ("consumer-effect-" + effect_pin + ".bin")).write_bytes(effect)
        report = self.local("outcome-scope", task_pin, effect_pin, "accepted")
        self.event(report, data.digest("bound engineering outcome"))
        self.bound(
            "report",
            task=task_pin,
            effect=effect_pin,
            outcome="accepted",
            delivery=data.digest("bound engineering outcome"),
        )
        readback = self.bound("verify", task=task_pin)
        self.assertEqual(readback["loop_sha256"], self.loop_pin)
        self.assertEqual(
            readback["loop_identity"]["candidate_sha256"], request["scope"]["candidate"]
        )
        self.assertEqual(readback["site_attested_independent_adopted_improvements"], 0)
        self.assertIsNone(readback["adopted_improvements_per_total_cost"])
        self.assertFalse(readback["complete_total_cost"])
        self.assertFalse(readback["settlement_authorized"])
        self.assertEqual(
            readback["authority_observation"], "live_engineering_fixture_verification"
        )
        self.assertIn(
            "already started",
            self.bound("run", task=task_pin, delivery=delivery, good=False),
        )
        recovered = self.bound("readback", task=task_pin)
        self.assertEqual(recovered["stages"], readback["stages"])
        self.assertEqual(
            recovered["authority_observation"],
            "retained_engineering_fixture_verification",
        )


if __name__ == "__main__":
    unittest.main()
