import dataclasses
import unittest

from content_interface import (
    Action, BackendKind, CacheBudget, ContractError, CoreSnapshot, CorrectnessValue,
    CostWeights, MissingFittedAdapters, Modality, PrefixObservation, Purpose,
    StopEvaluation, VisibleContent, select_action,
)


def empty_cache(budget=128):
    return VisibleContent("object-one", CacheBudget(budget))


def observation(modality=Modality.AUDIO, prefix=1, raw=None, aligned=None, event=None):
    return PrefixObservation(event or f"{modality.value}-{prefix}", "object-one", modality,
                             prefix, prefix, prefix + 0.1,
                             [2.0, 3.0] if raw is None else raw,
                             [0.25, 0.75] if aligned is None else aligned,
                             "common-alignment-fixture", (0, prefix))


class FixtureStopHead:
    def __init__(self, correctness=0.55):
        self.correctness = correctness

    def evaluate(self, content):
        return StopEvaluation((0.9, 0.1), CorrectnessValue(self.correctness, "common-head-fixture"))


class FixtureCoreReader:
    kind = BackendKind.CORE
    reader_id = "core-reader-fixture"

    def evaluate(self, content, state, action):
        return CorrectnessValue(state.values[0], "common-head-fixture")


class FixtureHistoryReader:
    kind = BackendKind.DIRECT_HISTORY
    reader_id = "history-reader-fixture"

    def __init__(self, forecast):
        self.forecast = forecast

    def evaluate(self, content, state, action):
        if state is not None:
            raise AssertionError("Baseline was given core state")
        return CorrectnessValue(self.forecast, "common-head-fixture")


def state_for(cache, forecast=0.8, core_id="gru-fixture"):
    return CoreSnapshot(core_id, cache.fingerprint(), [forecast] + [0.0] * 31)


def audio_action(miss_probability=0, elapsed=1.2, prefix=1):
    return Action(Modality.AUDIO, prefix, elapsed, miss_probability)


class ContentContractTests(unittest.TestCase):
    def test_payload_copied_and_cache_persistent(self):
        raw = [2.0, 3.0]
        aligned = [0.25, 0.75]
        obs = observation(raw=raw, aligned=aligned)
        raw[0] = 999.0
        aligned[0] = 999.0
        before = empty_cache()
        after = before.accept(obs, 1.2)
        self.assertEqual(after.audio.raw, (2.0, 3.0))
        self.assertEqual(after.audio.aligned, (0.25, 0.75))
        self.assertIsNone(before.audio)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            after.last_accepted_at = 20.0

    def test_pairing_requires_both_accepted_modalities(self):
        cache = empty_cache().accept(observation(), 1.2)
        unaccepted_video = observation(Modality.VIDEO, aligned=[0.5, 0.25])
        self.assertIsNone(cache.pair_interactions())
        paired = cache.accept(unaccepted_video, 1.3)
        self.assertEqual(paired.pair_interactions(), (0.125, 0.1875, 0.25, 0.5))
        self.assertIsNone(cache.video)

    def test_future_prefix_release_and_completion_rejected(self):
        with self.assertRaises(ContractError):
            PrefixObservation("future", "object-one", Modality.AUDIO, 2, 1, 1.1, [1], [1],
                              "common-alignment-fixture", (0, 1))
        with self.assertRaises(ContractError):
            empty_cache().accept(observation(), 1.05)

    def test_duplicate_backward_and_skipped_updates_rejected(self):
        cache = empty_cache().accept(observation(), 1.2)
        for obs, time in ((observation(), 2.0), (observation(Modality.VIDEO), 1.2),
                          (observation(prefix=3), 3.2)):
            with self.subTest(observation=obs.event_id, time=time), self.assertRaises(ContractError):
                cache.accept(obs, time)

    def test_object_capacity_nonfinite_and_alignment_rejections(self):
        for make in (
            lambda: empty_cache(24).accept(observation(), 1.2),
            lambda: observation(raw=[float("nan")]),
            lambda: empty_cache().accept(dataclasses.replace(observation(), object_id="another"), 1.2),
        ):
            with self.assertRaises(ContractError):
                make()
        cache = empty_cache().accept(observation(), 1.2).accept(observation(Modality.VIDEO, aligned=[0.5]), 1.3)
        with self.assertRaises(ContractError):
            cache.pair_interactions()

    def test_cache_rejects_unaccepted_and_future_embedded_payloads(self):
        with self.assertRaises(ContractError):
            VisibleContent("object-one", CacheBudget(128), 1.2, observation())
        with self.assertRaises(ContractError):
            VisibleContent("object-one", CacheBudget(128), 0.5, observation(), accepted_event_ids=("audio-1",))

    def test_alignment_identity_and_interval_must_match(self):
        audio = empty_cache().accept(observation(), 1.2)
        for video in (
            dataclasses.replace(observation(Modality.VIDEO), alignment_id="another-alignment"),
            dataclasses.replace(observation(Modality.VIDEO), aligned_window=(0.25, 1.0)),
        ):
            paired = audio.accept(video, 1.3)
            with self.assertRaises(ContractError):
                paired.pair_interactions()

    def test_storage_reports_payload_and_python_objects_separately(self):
        cache = empty_cache().accept(observation(), 1.2)
        accounting = cache.storage_accounting()
        self.assertEqual(accounting["nominal_float64_payload_bytes"], 32)
        self.assertEqual(accounting["retained_event_count"], 1)
        self.assertGreater(accounting["retained_python_object_graph_bytes"], 32)
        with self.assertRaises(ContractError):
            dataclasses.replace(observation(), event_id="x" * 129)


class ValueContractTests(unittest.TestCase):
    def test_core_signal_can_change_action_without_changing_stop_head(self):
        cache = empty_cache()
        decisions = [select_action(cache, state_for(cache, p), FixtureStopHead(), FixtureCoreReader(),
                                   [audio_action()], 0, 4) for p in (0.4, 0.8)]
        self.assertIsNone(decisions[0].action)
        self.assertEqual(decisions[1].action, audio_action())
        self.assertEqual(decisions[0].stop, decisions[1].stop)
        self.assertTrue(all(d.core_state_supplied_to_reader for d in decisions))
        self.assertFalse(any(d.scientific_execution for d in decisions))

    def test_same_value_core_and_direct_history_choose_same_action(self):
        cache = empty_cache()
        core = select_action(cache, state_for(cache), FixtureStopHead(), FixtureCoreReader(), [audio_action()], 0, 4)
        direct = select_action(cache, None, FixtureStopHead(), FixtureHistoryReader(0.8), [audio_action()], 0, 4)
        self.assertEqual((core.action, core.stop, core.alternatives), (direct.action, direct.stop, direct.alternatives))
        self.assertFalse(direct.core_state_supplied_to_reader)
        self.assertEqual(direct.backend, BackendKind.DIRECT_HISTORY)

    def test_value_does_not_silently_use_max_class_probability(self):
        cache = empty_cache()
        decision = select_action(cache, state_for(cache, 0.7), FixtureStopHead(0.4), FixtureCoreReader(), [audio_action()], 0, 4)
        self.assertEqual(max(decision.stop.class_probabilities), 0.9)
        self.assertEqual(decision.stop_score, 0.4)
        self.assertIsNotNone(decision.action)

    def test_initial_stop_is_legal_at_low_calibrated_confidence(self):
        cache = empty_cache()
        decision = select_action(cache, state_for(cache, 0.19), FixtureStopHead(0.2), FixtureCoreReader(), [audio_action()], 0, 4)
        self.assertIsNone(decision.action)
        self.assertEqual(cache.accepted_event_ids, ())

    def test_stop_wins_exact_tie_and_costs_can_change_choice(self):
        cache = empty_cache()
        tie = select_action(cache, state_for(cache, 0.5), FixtureStopHead(0.5), FixtureCoreReader(),
                            [audio_action()], 0, 4, CostWeights(0, 0, 0))
        self.assertIsNone(tie.action)
        costly = select_action(cache, state_for(cache, 0.8), FixtureStopHead(0.55), FixtureCoreReader(),
                               [audio_action(miss_probability=0.3)], 0, 4)
        self.assertIsNone(costly.action)

    def test_state_identity_baseline_bypass_and_clock_checked(self):
        cache = empty_cache().accept(observation(), 1.2)
        bad_calls = (
            lambda: select_action(cache, state_for(empty_cache()), FixtureStopHead(), FixtureCoreReader(), [], 1.2, 4),
            lambda: select_action(cache, state_for(cache), FixtureStopHead(), FixtureHistoryReader(0.8), [], 1.2, 4),
            lambda: select_action(cache, state_for(cache), FixtureStopHead(), FixtureCoreReader(), [], 1.1, 4),
            lambda: select_action(cache, state_for(cache), FixtureStopHead(), FixtureCoreReader(), [audio_action()], 1.2, 4),
        )
        for call in bad_calls:
            with self.assertRaises(ContractError):
                call()

    def test_head_or_target_mismatch_rejected(self):
        class WrongHead(FixtureCoreReader):
            def evaluate(self, content, state, action):
                return CorrectnessValue(0.8, "another-head")
        cache = empty_cache()
        with self.assertRaises(ContractError):
            select_action(cache, state_for(cache), FixtureStopHead(), WrongHead(), [audio_action()], 0, 4)
        with self.assertRaises(ContractError):
            CorrectnessValue(0.9, "common-head-fixture", "max_class_probability")

    def test_expired_deadline_consumes_no_core_forecast(self):
        cache = empty_cache()
        decision = select_action(cache, state_for(cache), FixtureStopHead(), FixtureCoreReader(), [audio_action()], 4.1, 4)
        self.assertIsNone(decision.action)
        self.assertFalse(decision.core_state_supplied_to_reader)
        self.assertEqual(decision.alternatives, ())

    def test_confirmation_without_fitted_adapters_refuses(self):
        cache = empty_cache()
        with self.assertRaises(MissingFittedAdapters):
            select_action(cache, state_for(cache), FixtureStopHead(), FixtureCoreReader(),
                          [audio_action()], 0, 4, purpose=Purpose.SCIENTIFIC_CONFIRMATION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
