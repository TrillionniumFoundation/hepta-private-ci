"""Opt-in frozen macro control inside the existing isolated receipt actor.

Only the current encoded public observation reaches the policy. READ includes
its paid preparation, observation, fresh candidate selection and final delivery.
This adapter does not release sealed sources or authorize production adoption.
"""

import hashlib
import math
from pathlib import Path

from ndu_real_materials.common import strict_json

from .critic_context import CriticContext
from .macro_public_state import project
from .metacontrol_macro_contract import SEQUENCES, digest


def codec_sha256():
    return digest(
        {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("macro_actor.py", "macro_public_state.py")
        }
    )


def host_context(config, utility_sha256):
    """Bind the declared finalizer, scorer and price to the executing host."""
    return {
        "utility_sha256": utility_sha256,
        "evaluator_sha256": config["evaluator_sha256"],
        "tariff_sha256": digest(
            {
                "schema": "ndu.real.macro-wall-tariff.v1",
                "latency_weight": config["latency_weight"],
            }
        ),
        "settlement_sha256": digest(
            {
                "schema": "ndu.real.macro-finalizer.v1",
                "host_sha256": hashlib.sha256(
                    Path(__file__).with_name("episode.py").read_bytes()
                ).hexdigest(),
                "actions": SEQUENCES["STOP"],
                "rubric_sha256": config["rubric_sha256"],
            }
        ),
    }


def verify_host_deployment(
    pin, config, *, weights_sha256, control_sha256, utility_sha256
):
    raw = Path(pin["path"]).read_bytes()
    if (
        not 0 < len(raw) <= 8 * 1024 * 1024
        or hashlib.sha256(raw).hexdigest() != pin["sha256"]
    ):
        raise ValueError("Macro deployment changed before host admission")
    value = strict_json(raw)
    context = CriticContext.from_wire(value["context"])
    if (
        value["weights_sha256"] != weights_sha256
        or value["control_sha256"] != control_sha256
        or any(
            getattr(context, k) != v
            for k, v in host_context(config, utility_sha256).items()
        )
    ):
        raise ValueError(
            "Macro context differs from executing scorer, tariff or finalizer"
        )


class FrozenMacroControl:
    """Execute one declared macro, preserving the live legal-action checks."""

    def __init__(self, raw, expected_sha256, *, weights_sha256, control_sha256):
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= 8 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise ValueError("Frozen macro deployment bytes differ")
        value = strict_json(raw)
        if (
            set(value)
            != {
                "schema",
                "policy",
                "context",
                "weights_sha256",
                "control_sha256",
                "checkpoint_utf8",
                "checkpoint_sha256",
                "read_seconds_bound",
                "finalizer_seconds_reserve",
            }
            or value["schema"] != "ndu.real.macro-deployment.v1"
        ):
            raise ValueError("Unexpected macro deployment schema")
        self.context = CriticContext.from_wire(value["context"])
        generator = Path(__file__).with_name("ocr.py")
        if (
            value["weights_sha256"] != weights_sha256
            or value["control_sha256"] != control_sha256
            or self.context.encoder_sha256 != weights_sha256
            or self.context.answer_sha256 != weights_sha256
            or self.context.generator_sha256
            != hashlib.sha256(generator.read_bytes()).hexdigest()
            or self.context.public_state_sha256 != codec_sha256()
        ):
            raise ValueError(
                "Macro content, generator or public codec requires refitting"
            )
        for name in ("read_seconds_bound", "finalizer_seconds_reserve"):
            number = value[name]
            if (
                type(number) not in (int, float)
                or not math.isfinite(number)
                or number <= 0
            ):
                raise ValueError("Positive finite macro time bounds required")
        if (
            value["policy"]
            not in {
                "STOP",
                "light",
                "tuned-fixed",
                "point",
                "unconditional",
                "conditional",
            }
            or type(value["checkpoint_utf8"]) is not str
        ):
            raise ValueError("Unknown frozen macro policy")
        from .macro_policy import load

        self.model = load(
            value["checkpoint_utf8"].encode(),
            value["checkpoint_sha256"],
            context=self.context,
        )
        self.deployment, self.sha256 = value, expected_sha256
        self.macro, self.sequence, self.index = None, None, 0

    def next(self, features, state, legal, *, public_metadata):
        if (
            type(state["step"]) is not int
            or state["step"] != self.index
            or state["forced_action"] is not None
        ):
            raise ValueError("Macro chronology or forced-action boundary changed")
        if state["text_committed"] or "WRITE_TEXT" not in legal:
            raise ValueError(
                "Macro finalizer requires an uncommitted writable text task"
            )
        detail = {}
        if self.sequence is None:
            public = project(
                features, public_metadata, state["remaining_seconds"], legal
            )
            self.macro, detail = self.model.choose(
                public,
                self.deployment["policy"],
                context=self.context,
                read_seconds_bound=self.deployment["read_seconds_bound"],
                finalizer_seconds_reserve=self.deployment["finalizer_seconds_reserve"],
            )
            self.sequence = SEQUENCES[self.macro]
            self.public_state_sha256 = digest(public)
            detail["macro_public_state"] = public
        if self.index >= len(self.sequence):
            raise ValueError("Actor continued after the completed macro")
        action = self.sequence[self.index]
        if action not in legal:
            raise ValueError("Actual macro continuation is no longer legal")
        if (
            action != "STOP"
            and state["remaining_seconds"]
            <= self.deployment["finalizer_seconds_reserve"]
        ):
            action = "STOP"
            detail["macro_aborted"] = (
                "remaining budget cannot cover reserved finalization"
            )
        detail.update(
            macro=self.macro,
            macro_step=self.index,
            macro_policy=self.deployment["policy"],
            macro_deployment_sha256=self.sha256,
            macro_public_state_sha256=self.public_state_sha256,
            forecast_calls=0,
            prediction_is_external_evidence=False,
        )
        self.index += 1
        return action, detail
