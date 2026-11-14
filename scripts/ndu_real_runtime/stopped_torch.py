"""Frozen checkpoint centers and offline extraction of observed STOP macros.

No new generator is fitted here. Only the exact behavior checkpoint can be
bound to retained outcomes. Record hashes and declared groups do not establish
independent custody. Action/STOP durations exclude unrecorded planning and I/O.
"""

from collections import Counter, defaultdict
import copy
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
from types import MappingProxyType

from .controllers import ACTIONS, PublicState
from .objective import canonical_sha
from .stopped_control import PROFILE_SHA256, TerminalCenter
from .training import validate_record
from .trajectory import V2_SCHEMA, is_digest, validate_chains


def source_identity():
    """Hash the actual adapter, model, selector and numerical dependencies."""
    directory = Path(__file__).resolve().parent
    files = [
        directory / name
        for name in (
            "stopped_torch.py",
            "stopped_control.py",
            "conditional_particles.py",
            "controllers.py",
            "objective.py",
            "neural.py",
            "ocr.py",
            "training.py",
            "trajectory.py",
            "fit_loop.py",
            "metering.py",
        )
    ]
    root = directory.parents[1]
    files.append(
        root
        / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"
    )
    return canonical_sha(
        {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        }
    )


def _model_identity(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(
            json.dumps([name, str(tensor.dtype), list(tensor.shape)]).encode()
        )
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


class FrozenMacroPredictor:
    """One action followed by STOP, using the same immutable behavior weights."""

    def __init__(
        self,
        weights_path,
        *,
        expected_weights_sha256,
        expected_source_sha256,
        core,
        memory_mode="reset",
        device="cpu",
    ):
        import torch
        from .neural import ReceiptPortfolioModel

        if (
            not all(
                is_digest(x) and x != "0" * 64
                for x in (
                    expected_weights_sha256,
                    expected_source_sha256,
                )
            )
            or source_identity() != expected_source_sha256
        ):
            raise ValueError("Frozen predictor source or identity pin differs")
        if memory_mode not in {"reset", "persistent"}:
            raise ValueError("Unknown frozen behavior memory mode")
        path = Path(weights_path)
        if (
            path.is_symlink()
            or not path.is_file()
            or not 0 < path.stat().st_size <= 64 * 1024 * 1024
        ):
            raise ValueError(
                "Behavior checkpoint is outside the bounded regular-file profile"
            )
        raw = path.read_bytes()
        if (
            len(raw) > 64 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != expected_weights_sha256
        ):
            raise ValueError("Actual behavior checkpoint bytes differ")
        model = ReceiptPortfolioModel(core)
        weights = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
        expected = model.state_dict()
        if (
            not isinstance(weights, dict)
            or set(weights) != set(expected)
            or any(
                not isinstance(x, torch.Tensor)
                or x.shape != expected[name].shape
                or x.dtype != expected[name].dtype
                or not bool(torch.isfinite(x).all())
                for name, x in weights.items()
            )
        ):
            raise ValueError(
                "Behavior checkpoint does not match the finite model schema"
            )
        model.load_state_dict(weights, strict=True)
        model.to(device).eval()
        model.requires_grad_(False)
        self.model, self.memory_mode = model, memory_mode
        self._parameter_sha256 = _model_identity(model)
        self._binding = MappingProxyType(
            {
                "weights_sha256": expected_weights_sha256,
                "source_sha256": expected_source_sha256,
                "profile_sha256": PROFILE_SHA256,
            }
        )

    @property
    def binding(self):
        return self._binding

    def assert_unchanged(self):
        if (
            any(module.training for module in self.model.modules())
            or any(p.requires_grad for p in self.model.parameters())
            or _model_identity(self.model) != self._parameter_sha256
            or source_identity() != self.binding["source_sha256"]
        ):
            raise ValueError("Frozen behavior parameters, mode or source changed")

    def center(self, state, action):
        import torch
        from .neural import STATE_WIDTH

        if not isinstance(state, PublicState) or action not in state.legal_actions:
            raise ValueError(
                "Only checked current public state and a legal action are accepted"
            )
        if len(state.features) != STATE_WIDTH:
            raise ValueError("Frozen model public feature width differs")
        self.assert_unchanged()
        anchor = next(self.model.parameters())
        with torch.inference_mode():
            current = torch.tensor(
                state.features, dtype=anchor.dtype, device=anchor.device
            )[None]
            actions = torch.tensor([ACTIONS.index(action)], device=anchor.device)
            predicted, duration = self.model.predict_transition(current, actions)
            if action == "STOP":
                predicted = current
            else:
                _, stop_duration = self.model.predict_transition(
                    predicted,
                    torch.tensor([ACTIONS.index("STOP")], device=anchor.device),
                )
                duration = duration + stop_duration
            utility = self.model.utility_head(predicted).sigmoid().item()
            result = TerminalCenter(
                tuple(predicted[0].cpu().tolist()), utility, duration.item()
            )
        result.validate(STATE_WIDTH)
        self.assert_unchanged()
        return result


@dataclass(frozen=True)
class ObservedStoppedMacro:
    start_row: dict
    stop_row: dict
    prefix_rows: tuple
    duration_seconds: float
    terminal_utility: float
    records_sha256: str


def select_stopped_macros(records, *, expected_behavior_weights_sha256):
    """Select actual adjacent action/STOP and STOP-only macros from train rows.

    V2 keeps its original hash chain. V1 needs its original canonical transition
    ordinal and exact successor linkage; it is never relabeled V2. The returned
    prefix allows faithful persistent replay when the original memory profile
    is known. V1 memory semantics remain unspecified and require source review.
    """
    if (
        not is_digest(expected_behavior_weights_sha256)
        or expected_behavior_weights_sha256 == "0" * 64
    ):
        raise ValueError("The actual behavior checkpoint digest is required")
    if not isinstance(records, (list, tuple)) or not 1 <= len(records) <= 10000:
        raise ValueError("A bounded original transition roster is required")
    sequences, identities = defaultdict(list), set()
    for row in records:
        validate_record(row)
        if row.get("behavior_weights_sha256") != expected_behavior_weights_sha256:
            raise ValueError(
                "Recorded outcomes belong to a different behavior checkpoint"
            )
        if row["record_id"] in identities:
            raise ValueError("Repeated original transition identity")
        identities.add(row["record_id"])
        sequences[(row["origin_run_id"], row["episode_id"])].append(row)
    validate_chains(records)
    macros, excluded = [], Counter()
    for sequence in sequences.values():
        first = sequence[0]
        if any(
            row[key] != first[key]
            for row in sequence
            for key in (
                "schema",
                "source_group",
                "source_size",
                "reference_field",
                "expected_text",
                "target_boxes",
                "behavior_weights_sha256",
            )
        ):
            raise ValueError(
                "Mixed source, schema or reference within a behavior episode"
            )
        if first["schema"] == V2_SCHEMA:
            ordered = sorted(sequence, key=lambda row: row["episode_step"])
        else:
            indexed = []
            for row in sequence:
                prefix = row["origin_run_id"] + "/transition/"
                suffix = row["record_id"][len(prefix) :]
                if (
                    not row["record_id"].startswith(prefix)
                    or len(suffix) != 2
                    or not suffix.isascii()
                    or not suffix.isdigit()
                ):
                    raise ValueError(
                        "Legacy adjacency lacks its original transition ordinal"
                    )
                indexed.append((int(suffix), row))
            indexed.sort(key=lambda pair: pair[0])
            if [index for index, _ in indexed] != list(range(len(indexed))) or len(
                indexed
            ) > 8:
                raise ValueError(
                    "Legacy episode has missing or repeated transition ordinals"
                )
            ordered = [row for _, row in indexed]
        for before, after in zip(ordered, ordered[1:]):
            if (
                before["execution_status"] != "completed"
                or before.get("terminal_reason") is not None
                or before["next_candidate_features"] != after["candidate_features"]
                or before["next_public_metadata"] != after["public_metadata"]
                or before["after_score"] != after["before_score"]
                or (
                    before.get("next_observation_sha256") is not None
                    and before["next_observation_sha256"]
                    != after.get("observation_sha256")
                )
            ):
                raise ValueError("Observed predecessor, successor or utility differs")
        stop = ordered[-1]
        if stop["execution_status"] != "completed":
            excluded["failed_terminal_episode"] += 1
            continue
        if stop["action"] != "STOP":
            excluded["no_actual_terminal_STOP"] += 1
            continue
        if (
            stop.get("terminal_reason") != "actor_stop"
            or stop["next_candidate_features"] is not None
            or stop["next_public_metadata"] is not None
            or stop["before_score"] != stop["after_score"]
        ):
            raise ValueError("STOP is not a completed unchanged terminal observation")
        starts = [len(ordered) - 1]
        if len(ordered) > 1:
            starts.insert(0, len(ordered) - 2)
        for index in starts:
            prefix = copy.deepcopy(ordered)
            duration = math.fsum(row["duration_seconds"] for row in ordered[index:])
            if not 0 < duration <= 3600:
                raise ValueError(
                    "Observed action/STOP macro duration exceeds the finite profile"
                )
            macros.append(
                ObservedStoppedMacro(
                    prefix[index],
                    prefix[-1],
                    tuple(prefix),
                    duration,
                    stop["after_score"],
                    canonical_sha(ordered),
                )
            )
    return tuple(macros), {
        "input_records": len(records),
        "input_episodes": len(sequences),
        "selected_macros": len(macros),
        "excluded_episodes": dict(excluded),
        "input_recorded_duration_seconds": math.fsum(
            row["duration_seconds"] for row in records
        ),
        "macro_observations_overlap_and_costs_are_not_additive": True,
        "behavior_weights_sha256": expected_behavior_weights_sha256,
        "cost_scope": "recorded_action_plus_STOP_seconds; planning_transport_energy_money_unknown",
        "counterfactual_outcomes_created": False,
        "legacy_schema_rewritten": False,
    }
