"""Immutable critic dependency declarations, never authentication of their origin.

Encoder pins cover weights and preprocessing; public-state pins cover codec and
runtime. Action pins cover the fixed graph, primitive/macro distinction and any
continuation suffix; settlement pins cover the finalizer. Generator, answer,
utility, tariff and evaluator identities must describe the actual producer and
outcome contract. Callers independently authenticate those manifests and receipt
provenance. Legacy observations cannot acquire identity by filling these fields.
"""

from dataclasses import asdict, dataclass
import hashlib
import json


class CriticContextError(ValueError):
    """Missing or changed dependency identity requires new fit/calibration."""


@dataclass(frozen=True)
class CriticContext:
    encoder_sha256: str
    answer_sha256: str
    generator_sha256: str
    public_state_sha256: str
    action_sha256: str
    settlement_sha256: str
    utility_sha256: str
    tariff_sha256: str
    evaluator_sha256: str

    def __post_init__(self):
        for name, value in asdict(self).items():
            if (
                type(value) is not str
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise CriticContextError(
                    f"recalibration_required: invalid {name} identity"
                )

    def to_wire(self):
        return {"schema": "ndu.ctrl.critic-context.v1", **asdict(self)}

    @classmethod
    def from_wire(cls, value):
        if (
            type(value) is not dict
            or set(value) != {"schema", *cls.__dataclass_fields__}
            or value["schema"] != "ndu.ctrl.critic-context.v1"
        ):
            raise CriticContextError(
                "recalibration_required: complete versioned critic context required"
            )
        return cls(**{key: value[key] for key in cls.__dataclass_fields__})


def require_context(actual, expected=None):
    """Check exact typed declarations; no inference from shape or numeric values."""
    if type(actual) is not CriticContext:
        raise CriticContextError("recalibration_required: critic context missing")
    actual.__post_init__()
    if expected is not None:
        require_context(expected)
        changed = [
            key
            for key in CriticContext.__dataclass_fields__
            if getattr(actual, key) != getattr(expected, key)
        ]
        if changed:
            raise CriticContextError(
                "recalibration_required: changed " + ", ".join(changed)
            )
    return actual


def context_digest(context):
    return hashlib.sha256(
        json.dumps(
            require_context(context).to_wire(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
