"""Contract and adversarial tests; run: python -m unittest discover -s scripts -p test_perc1.py -v."""
import base64
import copy
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from perc1.experiment import FixtureExecutor, actor_context, communication_cost, validate_trace
from perc1.fixture import smoke
from perc1.native import export_native_observation, wire_bytes
from perc1.report import build_report
from perc1.schema import ActorObservation, Cost, Dataset, Invalid, canonical, load, locator, manifest, sha


class Perc1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        smoke(cls.root)
        cls.original = {name: load(cls.root / (name + ".json")) for name in ("manifest", "dataset", "traces", "evaluator", "report")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        data = copy.deepcopy(self.original)
        self.m, self.data, self.traces, self.ev = (data[k] for k in ("manifest", "dataset", "traces", "evaluator"))
        self.ds = Dataset(self.data, self.root)

    def rebind(self):
        self.ds = Dataset(self.data, self.root)
        self.m["dataset_sha256"] = sha(self.data)
        for trace in self.traces:
            trace["manifest_sha256"] = sha(self.m)
            for i, step in enumerate(trace["steps"]):
                step["input_sha256"] = sha(actor_context(self.ds, self.ds.episodes[trace["episode_id"]], trace["steps"][:i]))

    def report(self):
        return build_report(self.m, self.ds, self.traces, self.ev, bootstrap=200)

    def executor(self):
        return FixtureExecutor(self.m, self.ds, self.ds.episodes["confirmation.missing_document"], 11, "global_fixed")

    def observation(self, value=None):
        value = value or self.traces[0]["steps"][0]["observation"]
        return ActorObservation.parse(value, self.ds.sources[value["source_id"]], self.ds.read(value["source_id"]), self.m["encoder"], "global_fixed")

    def test_complete_smoke_remains_hold(self):
        result = self.report()
        self.assertEqual((result["paired_traces"], result["structural_validation"], result["status"]), (32, "PASS", "HOLD"))
        self.assertFalse(result["scientific_qualified"])
        self.assertIsNone(result["per_observation_causal_gain"])
        self.assertEqual(result["effects"]["task_success"]["dense"]["estimate"], 0)
        self.assertLess(result["arms"]["global_active"]["cost"], result["arms"]["global_fixed"]["cost"])

    def test_flags_and_permissive_thresholds_cannot_qualify_fixture(self):
        self.m["encoder"]["kind"] = "external_artifact"
        self.m["thresholds"] = dict(minimum_task_gain=0, maximum_field_regression=0, minimum_training_seeds=2)
        for source in self.data["sources"]:
            source["uri"] = "https://example.invalid/" + source["id"]
        self.rebind()
        result = self.report()
        self.assertTrue(result["thresholds_met"])
        self.assertEqual(result["status"], "HOLD")
        self.assertFalse(result["independent_training_verified"])

    def test_original_evidence_survives_both_representation_arms(self):
        for fixed, dense in zip(self.traces[::4], self.traces[1::4]):
            self.assertEqual([(s["observation"]["source_id"], s["observation"]["raw_base64"]) for s in fixed["steps"]],
                             [(s["observation"]["source_id"], s["observation"]["raw_base64"]) for s in dense["steps"]])

    def test_source_bytes_are_checked(self):
        source = self.data["sources"][0]
        path, raw = self.root / source["path"], self.ds.read(source["id"])
        try:
            path.write_bytes(raw + b"modified")
            with self.assertRaises(Invalid):
                self.ds.read(source["id"])
        finally:
            path.write_bytes(raw)

    def test_root_escape_and_split_leakage_rejected(self):
        self.data["sources"][0]["path"] = "../secret"
        with self.assertRaises(Invalid):
            Dataset(self.data, self.root)
        self.data = copy.deepcopy(self.original["dataset"])
        self.data["sources"][12]["locator"]["origin_sha256"] = self.data["sources"][0]["locator"]["origin_sha256"]
        self.rebind()
        with self.assertRaises(Invalid):
            manifest(self.m, self.ds)

    def test_coordinate_and_time_negatives(self):
        examples = [copy.deepcopy(s["locator"]) for s in self.data["sources"][::3]][:4]
        for loc, key, invalid in ((examples[0], "start", True), (examples[0], "end", 10**9),
                                   (examples[1], "x1", 65), (examples[2], "pointer", "/bad~3"),
                                   (examples[3], "end_ns", 0), (examples[3], "last_frame", 31)):
            with self.subTest(key=key), self.assertRaises(Invalid):
                locator(dict(loc, **{key: invalid}))

    def test_unknown_fields_nonfinite_values_and_bounds(self):
        original = self.traces[0]["steps"][0]["observation"]
        for key, value in (("teacher_truth", "secret"), ("observed_ns", -1)):
            bad = copy.deepcopy(original)
            bad[key] = value
            with self.assertRaises(Invalid):
                self.observation(bad)
        for value in (float("nan"), float("inf"), 10**1000, True):
            bad = copy.deepcopy(original)
            bad["tokens"][0]["values"][0] = value
            with self.assertRaises(Invalid):
                self.observation(bad)
        bad = copy.deepcopy(original)
        bad["tokens"][0]["locator"]["end"] += 1
        with self.assertRaises(Invalid):
            self.observation(bad)

    def test_observation_is_deeply_detached_and_immutable(self):
        raw = copy.deepcopy(self.traces[0]["steps"][0]["observation"])
        obs = self.observation(raw)
        raw["tokens"][0]["values"][0] = float("nan")
        self.assertTrue(math.isfinite(obs.tokens[0]["values"][0]))
        with self.assertRaises(TypeError):
            obs.tokens[0]["values"][0] = 7
        detached = obs.to_dict()
        detached["tokens"][0]["values"][0] = 9000
        self.assertNotEqual(obs.to_dict(), detached)

    def test_cost_missing_negative_overflow_and_underbilling(self):
        cost = self.traces[0]["steps"][0]["cost"]
        for bad in ({k: v for k, v in cost.items() if k != "wait"}, dict(cost, acquisition=-1), dict(cost, acquisition=2**63 - 1)):
            with self.assertRaises(Invalid):
                Cost.parse(bad)
        self.traces[0]["steps"][0]["cost"]["communication"] = 1
        with self.assertRaises(Invalid):
            validate_trace(self.traces[0], self.m, self.ds)

    def test_budget_denial_prevents_source_read(self):
        self.m["budget"]["cap"] = 300
        runner = self.executor()
        with patch.object(self.ds, "read", side_effect=AssertionError("read before reservation")):
            self.assertFalse(runner.attempt(runner.episode["initial_ids"][0]))
        self.assertEqual(runner.trace["steps"][0]["status"], "budget_denied")
        self.assertGreater(validate_trace(runner.trace, self.m, self.ds)["spent"], 0)

    def test_failure_cancellation_unknown_and_missing_source_are_billed(self):
        for status, phase in (("failed", "failure"), ("cancelled", "cancellation"), ("unknown", "failure")):
            runner = self.executor()
            runner.attempt(runner.episode["initial_ids"][0], outcome=status)
            audit = validate_trace(runner.trace, self.m, self.ds)
            self.assertGreater(runner.trace["steps"][0]["cost"][phase], 0)
            if status == "unknown":
                self.assertGreater(audit["pending_reservation"], 0)
                with self.assertRaises(Invalid):
                    runner.attempt(runner.episode["initial_ids"][0])
        source = self.ds.sources[self.executor().episode["initial_ids"][0]]
        source["path"] = "absent.fixture"
        self.m["dataset_sha256"] = sha(self.data)
        runner = self.executor()
        runner.attempt(source["id"])
        self.assertEqual(runner.trace["steps"][0]["status"], "failed")
        validate_trace(runner.trace, self.m, self.ds)

    def test_unknown_can_interrupt_multiple_initial_reads_but_stop_cannot(self):
        episode = self.executor().episode
        episode["initial_ids"] = episode["source_ids"][:2]
        self.m["dataset_sha256"] = sha(self.data)
        runner = self.executor()
        runner.attempt(episode["initial_ids"][0], outcome="unknown")
        validate_trace(runner.trace, self.m, self.ds)
        step = runner.trace["steps"][0]
        step.update(status="stopped", proposal=None)
        step["cost"].update(acquisition=0, failure=0, communication=communication_cost(None, None, "stopped", self.m["budget"]["tariff"]))
        with self.assertRaises(Invalid):
            validate_trace(runner.trace, self.m, self.ds)

    def test_source_alias_cannot_masquerade_as_new_evidence(self):
        episode = self.executor().episode
        first, alias = (self.ds.sources[s] for s in episode["source_ids"][:2])
        for key in ("path", "sha256", "byte_length", "locator", "available_ns"):
            alias[key] = copy.deepcopy(first[key])
        self.m["dataset_sha256"] = sha(self.data)
        runner = self.executor()
        runner.attempt(first["id"])
        runner.attempt(alias["id"])
        self.assertEqual(runner.trace["steps"][-1]["status"], "no_new_evidence")
        self.assertEqual(len(validate_trace(runner.trace, self.m, self.ds)["observed_captures"]), 1)
        forged = copy.deepcopy(runner.trace["steps"][0])
        forged.update(attempt_id="1", proposal=dict(forged["proposal"], source_id=alias["id"]),
                      input_sha256=sha(actor_context(self.ds, episode, runner.trace["steps"][:1])), started_ns=1000, finished_ns=2000)
        forged["observation"].update(source_id=alias["id"], observed_ns=2000)
        runner.trace["steps"][-1] = forged
        with self.assertRaisesRegex(Invalid, "alias"):
            validate_trace(runner.trace, self.m, self.ds)

    def test_pairing_seeds_and_evaluator_identity(self):
        self.traces.pop()
        with self.assertRaises(Invalid):
            self.report()
        self.traces = copy.deepcopy(self.original["traces"])
        self.ev["identity_sha256"] = "f" * 64
        with self.assertRaises(Invalid):
            self.report()
        self.m["controller"]["training_runs"][1]["receipt_sha256"] = self.m["controller"]["training_runs"][0]["receipt_sha256"]
        with self.assertRaises(Invalid):
            manifest(self.m, self.ds)

    def test_private_truth_does_not_change_actor_and_canary_is_rejected(self):
        before = self.executor().run()
        self.ev["targets"][0]["answer"] = "private changed label"
        self.m["evaluator"]["targets_sha256"] = sha(self.ev["targets"])
        after = self.executor().run()
        self.assertEqual(before["steps"], after["steps"])
        self.assertEqual(before["answer"], after["answer"])
        self.ds.episodes[self.traces[0]["episode_id"]]["task"] += self.ev["canaries"][0]
        self.rebind()
        with self.assertRaisesRegex(Invalid, "canary"):
            self.report()

    def test_strict_json_and_template_reject_missing_frozen_identity(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}'):
            path = self.root / "bad.json"
            path.write_text(text)
            with self.assertRaises(Invalid):
                load(path)
        with self.assertRaises(Invalid):
            manifest(load(Path(__file__).parent / "perc1/example_manifest.json"), self.ds)

    def test_native_wire_matches_rust_fixture_and_raw_lane_is_identical(self):
        target = load(Path(__file__).parents[1] / "codex-rs/hepta-neuron/tests/fixtures/perception-bytes-v1.json")
        source = target["evidence"][0]["source"]
        raw = b"amount=19.99;not_paid;v=2.1"
        loc = dict(kind="bytes", origin_sha256=bytes(source["origin_digest"]).hex(), start=100, end=127, total=1000)
        obs = ActorObservation(source["source_id"], sha(raw), base64.b64encode(raw).decode(), loc,
                               bytes(target["latent_model_digest"]).hex(), [{"locator": dict(loc, start=a, end=b), "values": [v]} for a, b, v in ((100, 112, 1), (112, 127, .5))], 7000)
        args = dict(scope_digest=bytes(target["scope_digest"]).hex(), source_frontier=bytes(target["source_frontier"]).hex(), encoder_digest=bytes(target["encoder_digest"]).hex(),
                    windows=[dict(evidence_id=e["evidence_id"], start=e["coordinates"]["start"], end=e["coordinates"]["end"]) for e in target["evidence"]])
        dense = export_native_observation(obs, **args, representation="dense")
        self.assertEqual(dense, target)
        self.assertEqual(sha(wire_bytes(dense)), "e08fffef99344a9ff1bd0c70f715dfdf450ecf179732f6cd12e33fc0fa9cb454")
        global_obs = obs.to_dict()
        global_obs["tokens"] = [{"locator": loc, "values": [.75]}]
        pooled = export_native_observation(global_obs, **args, representation="global")
        self.assertEqual(pooled["evidence"], dense["evidence"])
        self.assertEqual(len(pooled["latents"][0]["evidence_digests"]), 2)
        for key, bad_value in (("observed_ns", 0), ("source_id", "invalid id"), ("source_id", "a" * 129)):
            bad = obs.to_dict()
            bad[key] = bad_value
            with self.assertRaises(Invalid):
                export_native_observation(bad, **args, representation="dense")
        for vector in ([9.0], [1.0] * 2049):
            bad = obs.to_dict()
            for token in bad["tokens"]:
                token["values"] = vector
            with self.assertRaises(Invalid):
                export_native_observation(bad, **args, representation="dense")
        bad_args = dict(args, windows=[dict(evidence_id="x", start=100, end=127)] * 65)
        with self.assertRaises(Invalid):
            export_native_observation(global_obs, **bad_args, representation="global")
        for size, dimension, reason in ((8193, 1, "8192"), (8192, 4096, "65536")):
            raw_large = b"\xff" * size
            big_loc = dict(loc, start=0, end=size, total=size)
            big = dict(global_obs, raw_base64=base64.b64encode(raw_large).decode(), raw_sha256=sha(raw_large), locator=big_loc,
                       tokens=[{"locator": big_loc, "values": [8.0] * dimension}])
            big_args = dict(args, windows=[dict(evidence_id="all", start=0, end=size)])
            with self.assertRaisesRegex(Invalid, reason):
                export_native_observation(big, **big_args, representation="global")


if __name__ == "__main__":
    unittest.main()
