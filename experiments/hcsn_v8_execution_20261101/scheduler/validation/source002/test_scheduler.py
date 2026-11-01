"""Causal behavior tests using explicit logical-clock fixtures."""

import hashlib
import json
import unittest

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, ContractError, CoreSnapshot, CorrectnessValue,
    Modality, PrefixObservation, StopEvaluation, VisibleContent,
)
from .execution import LogicalClock, ReadResult, run_episode
from .planning import Plan, Read, ServiceEstimate, Wait, choose_plan, enumerate_plans, validate_plan


def make_observation(step, now, event_id="event", object_id="object"):
    return PrefixObservation(event_id, object_id, step.modality, step.prefix_end,
                             step.prefix_end, now, (0.2, 0.8), (0.2, 0.8),
                             "alignment", (0, step.prefix_end))


class Head:
    def evaluate(self, content):
        p = 0.4 + 0.1 * len(content.accepted_event_ids)
        return StopEvaluation((p, 1 - p), CorrectnessValue(p, "head"))


class Forecast:
    reader_id = "reader"

    def __init__(self, values=None, kind=BackendKind.DIRECT_HISTORY):
        self.values = values or {}
        self.kind = kind
        self.seen = []

    def evaluate(self, content, state, plan):
        self.seen.append((content.fingerprint(), content.accepted_event_ids, plan.identity))
        return CorrectnessValue(self.values.get(plan.identity, Head().evaluate(content).calibrated_correctness.probability), "head")


class ServiceModel:
    def estimate(self, content, plan, now, deadline):
        duration = sum(step.seconds if type(step) is Wait else 0.1 for step in plan.steps)
        return ServiceEstimate(duration, 0.0)


class Core:
    def __init__(self):
        self.updates = []

    def initial(self, content):
        return CoreSnapshot("core", content.fingerprint(), (0.0,) * 32)

    def accept(self, state, content, observation, increment):
        self.updates.append((observation.event_id, increment))
        return CoreSnapshot("core", content.fingerprint(), tuple(x + increment for x in state.values))


class ScriptService:
    mode = "scripted logical-time fixture; no actual recognition/cost measurement"

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = []
        self.payload_reads = 0
        self.drains = 0

    def request(self, step, clock):
        self.requests.append(step.identity)
        completion, producer = next(self.outcomes)
        owner = self

        class Pending:
            def wait_until(self, deadline, clock):
                clock.wait_until(min(completion, deadline))
                if completion > deadline:
                    return None
                owner.payload_reads += 1
                return producer(step, clock.now())

            def drain(self, clock):
                clock.wait_until(completion)
                owner.drains += 1
                owner.payload_reads += 1
                return producer(step, clock.now())

        return Pending()


def success(event_id):
    return lambda step, now: ReadResult(observation=make_observation(step, now, event_id))


class SchedulerTests(unittest.TestCase):
    def run_fixture(self, service, fixed=(), deadline=4.0, core=None, forecast=None, **kwargs):
        output = []
        forecast = forecast or Forecast(kind=BackendKind.CORE if core else BackendKind.DIRECT_HISTORY)
        receipt = run_episode("object", CacheBudget(4096), Head(), forecast, ServiceModel(), service,
                              output.append, clock=LogicalClock(), core=core, deadline=deadline,
                              horizon=3, fixed_plans=fixed, **kwargs)
        self.assertEqual(receipt["serialized_output_sha256"], hashlib.sha256(output[0]).hexdigest())
        self.assertEqual(json.loads(output[0])["accepted_event_ids"], list(receipt["output"]["accepted_event_ids"]))
        self.assertFalse(receipt["scientific_confirmation"])
        return receipt

    def test_plan_enumeration_all_paths_adjacent_and_bounded(self):
        content = VisibleContent("object", CacheBudget(4096))
        plans = enumerate_plans(content, horizon=3, wait_seconds=(0.1,))
        for plan in plans:
            validate_plan(content, plan, 3)
        self.assertEqual(len({p.identity for p in plans}), len(plans))
        self.assertIn(Plan((Read(Modality.AUDIO, 1), Read(Modality.AUDIO, 2))), plans)
        self.assertIn(Plan((Wait(0.1), Read(Modality.VIDEO, 1))), plans)
        self.assertTrue(all("WAIT:0.10000000000000001/WAIT" not in p.identity for p in plans))

    def test_skips_repeats_and_oversized_search_refused(self):
        content = VisibleContent("object", CacheBudget(4096))
        for plan in (Plan((Read(Modality.AUDIO, 2),)),
                     Plan((Read(Modality.AUDIO, 1), Read(Modality.AUDIO, 1))),
                     Plan((Wait(0.1), Wait(0.2)))):
            with self.assertRaises(ContractError):
                validate_plan(content, plan)
        with self.assertRaises(ContractError):
            enumerate_plans(content, horizon=7)

    def test_controller_shared_between_core_and_direct_history(self):
        content = VisibleContent("object", CacheBudget(4096))
        plan = Plan((Read(Modality.AUDIO, 1), Read(Modality.VIDEO, 1)))
        answers = []
        for kind in BackendKind:
            state = Core().initial(content) if kind == BackendKind.CORE else None
            selected, receipt = choose_plan(content, state, Head(), Forecast({plan.identity: 0.9}, kind),
                                            ServiceModel(), (plan,), 0, 4)
            answers.append((selected, receipt["stop_score"], receipt["plans"]))
        self.assertEqual(answers[0], answers[1])

    def test_wait_has_no_information_gain_and_stop_wins_zero_gain(self):
        content = VisibleContent("object", CacheBudget(4096))
        wait = Plan((Wait(0.1),))
        selected, _ = choose_plan(content, None, Head(), Forecast(), ServiceModel(), (wait,), 0, 4)
        self.assertIsNone(selected)
        with self.assertRaisesRegex(ContractError, "WAIT cannot"):
            choose_plan(content, None, Head(), Forecast({wait.identity: 0.9}), ServiceModel(), (wait,), 0, 4)

    def test_mandatory_audio_failure_is_charged(self):
        service = ScriptService(((0.1, lambda step, now: ReadResult(error="decode failed")),))
        receipt = self.run_fixture(service)
        self.assertEqual((service.requests, receipt["requested_observations"], receipt["observation_fee"],
                          receipt["output"]["accepted_event_ids"]), (["READ:audio:1"], 1, 0.02, ()))

    def test_wait_changes_no_cache_or_core_and_multistep_commits(self):
        service = ScriptService(((1.1, success("a1")), (1.4, success("v1")), (2.1, success("a2"))))
        core = Core()
        plan = Plan((Wait(0.2), Read(Modality.VIDEO, 1), Read(Modality.AUDIO, 2)))
        receipt = self.run_fixture(service, fixed=(plan,), core=core)
        wait = next(e for e in receipt["events"] if e["kind"] == "wait")
        self.assertEqual((wait["before"], wait["core_unchanged"]), (wait["after"], True))
        self.assertEqual(core.updates, [("a1", 1.0), ("v1", 1.0), ("a2", 1.0)])
        self.assertEqual(service.requests, ["READ:audio:1", "READ:video:1", "READ:audio:2"])
        self.assertEqual(receipt["requested_observations"], 3)

    def test_deadline_output_frozen_before_late_drain(self):
        service = ScriptService(((1.1, success("a1")), (2.0, success("v1"))))
        plan = Plan((Read(Modality.VIDEO, 1),))
        receipt = self.run_fixture(service, fixed=(plan,), deadline=1.5)
        self.assertEqual((receipt["output_elapsed_seconds"], receipt["post_drain_elapsed_seconds"],
                          receipt["requested_observations"], receipt["output"]["accepted_event_ids"], service.drains),
                         (1.5, 2.0, 2, ("a1",), 1))
        self.assertEqual([e["status"] for e in receipt["events"]], ["accepted", "timed_out"])

    def test_duplicate_response_rejected_and_charged(self):
        service = ScriptService(((1.1, success("same")), (1.2, success("same"))))
        receipt = self.run_fixture(service, fixed=(Plan((Read(Modality.VIDEO, 1),)),))
        self.assertEqual((receipt["requested_observations"], receipt["output"]["accepted_event_ids"]), (2, ("same",)))
        self.assertEqual(receipt["events"][-1]["status"], "rejected")

    def test_future_response_is_rejected_without_state_change(self):
        service = ScriptService(((1.1, lambda step, now: ReadResult(
            observation=make_observation(step, now + 1, "future"))),))
        core = Core()
        receipt = self.run_fixture(service, core=core)
        self.assertEqual((receipt["events"][0]["status"], core.updates,
                          receipt["output"]["accepted_event_ids"]), ("rejected", [], ()))

    def test_failed_midpath_only_charges_issued_work(self):
        service = ScriptService(((1.1, success("a1")),
                                 (1.2, lambda step, now: ReadResult(error="failed"))))
        receipt = self.run_fixture(service, fixed=(Plan((Read(Modality.VIDEO, 1), Read(Modality.AUDIO, 2))),))
        self.assertEqual((service.requests, receipt["requested_observations"], receipt["observation_fee"]),
                         (["READ:audio:1", "READ:video:1"], 2, 0.04))

    def test_controller_receives_only_actual_completed_prefix(self):
        service = ScriptService(((1.1, success("a1")),))
        forecast = Forecast()
        self.run_fixture(service, fixed=None, forecast=forecast)
        self.assertTrue(forecast.seen)
        self.assertEqual({ids for _, ids, _ in forecast.seen}, {("a1",)})
        self.assertEqual(service.payload_reads, 1)

    def test_slow_output_flush_is_charged_to_latency(self):
        service = ScriptService(((1.1, success("a1")),))
        clock = LogicalClock()
        captured = []

        def sink(data):
            captured.append(data)
            clock.wait_until(4.1)

        receipt = run_episode("object", CacheBudget(4096), Head(), Forecast(), ServiceModel(), service,
                              sink, clock=clock, fixed_plans=())
        self.assertEqual((receipt["timely_output"], receipt["output_elapsed_seconds"],
                          receipt["deadline_penalty"]), (False, 4.1, 1.0))
        self.assertAlmostEqual(receipt["latency_fee"], 0.0205, places=15)

    def test_failed_output_sink_still_drains_owned_late_work(self):
        service = ScriptService(((2.0, success("late")),))
        clock = LogicalClock()

        def failing_sink(data):
            raise OSError("sink closed")

        with self.assertRaisesRegex(OSError, "sink closed"):
            run_episode("object", CacheBudget(4096), Head(), Forecast(), ServiceModel(), service,
                        failing_sink, clock=clock, deadline=1.0, fixed_plans=())
        self.assertEqual((service.drains, clock.now()), (1, 2.0))


if __name__ == "__main__":
    unittest.main()
