"""Frozen adapter/host regressions; fitted labels are manufactured fixtures only."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from . import macro_actor, macro_policy
from .content_identity import SELECTION_SCHEMA
from .critic_context import context_digest
from .episode import EpisodeHost
from .metacontrol_macro_contract import SEQUENCES, digest
from .test_macro_policy import CONTEXT, pair


def fixture_deployment(
    policy="tuned-fixed", *, width=1, weights="a" * 64, control="b" * 64, context=None
):
    """Fit fixture returns, pin bytes, then cold-load through the real adapter."""
    if context is None:
        context = replace(
            CONTEXT,
            encoder_sha256=weights,
            answer_sha256=weights,
            generator_sha256=hashlib.sha256(
                Path(macro_actor.__file__).with_name("ocr.py").read_bytes()
            ).hexdigest(),
            public_state_sha256=macro_actor.codec_sha256(),
        )
    train = [
        pair("a", "a0", 0),
        pair("a", "a1", 1),
        pair("b", "b0", 0),
        pair("b", "b1", 1),
    ]
    calibration = [pair("cal" + str(i), "c" + str(i)) for i in range(10)]
    for row in train + calibration:
        row["context_sha256"] = context_digest(context)
        row["state"]["features"] *= width
        for branch in row["branches"].values():
            branch["public_state_sha256"] = digest(row["state"])
            branch["initial_public_state_sha256"] = digest(
                ["fixture", row["decision_id"]]
            )
    model = macro_policy.fit(
        train,
        calibration,
        context=context,
        expected_source_sha256=macro_policy.source_sha256(),
    )
    return {
        "schema": "ndu.real.macro-deployment.v1",
        "policy": policy,
        "context": context.to_wire(),
        "weights_sha256": weights,
        "control_sha256": control,
        "checkpoint_utf8": model.to_bytes().decode(),
        "checkpoint_sha256": model.sha256,
        "read_seconds_bound": 2.0,
        "finalizer_seconds_reserve": 1.0,
    }


def load_fixture(value):
    raw = json.dumps(value, sort_keys=True).encode()
    return macro_actor.FrozenMacroControl(
        raw,
        hashlib.sha256(raw).hexdigest(),
        weights_sha256="a" * 64,
        control_sha256="b" * 64,
    )


def state(step=0, remaining=10.0):
    return {
        "step": step,
        "remaining_seconds": remaining,
        "text_committed": False,
        "forced_action": None,
    }


class FrozenMacroActorTests(unittest.TestCase):
    def test_fitted_adapter_executes_whole_macro_without_forced_actions(self):
        for policy, macro in (("STOP", "STOP"), ("tuned-fixed", "READ")):
            with self.subTest(policy=policy):
                actor = load_fixture(fixture_deployment(policy))
                observed = []
                for index in range(len(SEQUENCES[macro])):
                    legal = ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
                    if index:
                        legal.append("READ_ROI")
                    action, detail = actor.next([0.5], state(index), legal)
                    observed.append(action)
                    self.assertEqual(detail["macro_deployment_sha256"], actor.sha256)
                    if index == 0:
                        public_pin = digest(detail["macro_public_state"])
                        self.assertEqual(
                            detail["macro_public_state"]["features"], [0.5]
                        )
                    self.assertEqual(detail["macro_public_state_sha256"], public_pin)
                self.assertEqual(observed, SEQUENCES[macro])
                with self.assertRaises(ValueError):
                    actor.next([0.5], state(len(observed)), legal)

    def test_forced_action_resume_and_boolean_chronology_are_refused(self):
        for changed in ({"forced_action": "STOP"}, {"step": 1}, {"step": False}):
            actor = load_fixture(fixture_deployment())
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                actor.next(
                    [0.5], {**state(), **changed}, ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
                )

    def test_budget_and_actual_legal_support_control_continuation(self):
        actor = load_fixture(fixture_deployment())
        self.assertEqual(
            actor.next([0.5], state(), ["STOP", "WRITE_TEXT"])[0], "WRITE_TEXT"
        )
        actor = load_fixture(fixture_deployment())
        self.assertEqual(
            actor.next(
                [0.5], state(remaining=2), ["STOP", "WRITE_TEXT", "PREPARE_ROI"]
            )[0],
            "WRITE_TEXT",
        )
        actor = load_fixture(fixture_deployment())
        actor.next([0.5], state(), ["STOP", "WRITE_TEXT", "PREPARE_ROI"])
        action, detail = actor.next(
            [0.5], state(1, 0.5), ["STOP", "WRITE_TEXT", "READ_ROI"]
        )
        self.assertEqual(action, "STOP")
        self.assertIn("macro_aborted", detail)
        actor = load_fixture(fixture_deployment())
        actor.next([0.5], state(), ["STOP", "WRITE_TEXT", "PREPARE_ROI"])
        with self.assertRaises(ValueError):
            actor.next([0.5], state(1), ["STOP", "WRITE_TEXT"])

    def test_content_control_codec_and_frozen_checkpoint_drift_refuse(self):
        original = fixture_deployment()
        for field in (
            "weights_sha256",
            "control_sha256",
            "encoder_sha256",
            "answer_sha256",
            "generator_sha256",
            "public_state_sha256",
            "checkpoint_sha256",
        ):
            value = deepcopy(original)
            target = value["context"] if field in value["context"] else value
            target[field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_fixture(value)
        raw = json.dumps(original).encode()
        with self.assertRaises(ValueError):
            macro_actor.FrozenMacroControl(
                raw + b" ",
                hashlib.sha256(raw).hexdigest(),
                weights_sha256="a" * 64,
                control_sha256="b" * 64,
            )

    def test_host_requires_the_original_ready_macro_policy_witness(self):
        for pin in (None, "0" * 64, "f" * 64):
            host = EpisodeHost.__new__(EpisodeHost)
            host.ready = False
            host.case = {"id": "fixture"}
            host.profile = {"model_sha256": "a" * 64}
            host.utility_profile_sha256 = "b" * 64
            host.control_profile_sha256 = "c" * 64
            host.control = SimpleNamespace(memory_mode="reset")
            host.macro_policy = {"sha256": "f" * 64}
            host.started = time.perf_counter()
            host.public_step = lambda: b"public-step\n"
            ready = {
                "schema": "ndu.real.actor-ready.v1",
                "case_id": "fixture",
                "weights_sha256": "a" * 64,
                "utility_profile_sha256": "b" * 64,
                "control_profile_sha256": "c" * 64,
                "memory_mode": "reset",
                "content_identity_profile": SELECTION_SCHEMA,
                "macro_policy_sha256": pin,
            }
            with self.subTest(pin=pin):
                if pin == "f" * 64:
                    self.assertEqual(host.callback(ready), b"public-step\n")
                    self.assertTrue(host.ready)
                else:
                    with self.assertRaises(ValueError):
                        host.callback(ready)
                    self.assertFalse(host.ready)

    def test_host_binds_checkpoint_to_executing_objective_scorer_and_finalizer(self):
        config = {
            "evaluator_sha256": "c" * 64,
            "rubric_sha256": "d" * 64,
            "latency_weight": 0.1,
        }
        fields = macro_actor.host_context(config, "e" * 64)
        context = replace(
            CONTEXT,
            generator_sha256=hashlib.sha256(
                Path(macro_actor.__file__).with_name("ocr.py").read_bytes()
            ).hexdigest(),
            public_state_sha256=macro_actor.codec_sha256(),
            **fields,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            for field in (None, *fields):
                changed = (
                    context if field is None else replace(context, **{field: "0" * 64})
                )
                deployment = fixture_deployment(context=changed)
                load_fixture(deployment)  # Every checkpoint is internally consistent.
                raw = json.dumps(deployment, sort_keys=True).encode()
                path.write_bytes(raw)
                pin = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
                with self.subTest(field=field):
                    if field is None:
                        macro_actor.verify_host_deployment(
                            pin,
                            config,
                            weights_sha256="a" * 64,
                            control_sha256="b" * 64,
                            utility_sha256="e" * 64,
                        )
                    else:
                        with self.assertRaises(ValueError):
                            macro_actor.verify_host_deployment(
                                pin,
                                config,
                                weights_sha256="a" * 64,
                                control_sha256="b" * 64,
                                utility_sha256="e" * 64,
                            )


if __name__ == "__main__":
    unittest.main()
