"""Real text-loss SGD through the source-pinned Joint v4/HeptaCore model.

This module is loaded only after request, input and repository-source checks.
It produces unsigned candidate bytes. It does not evaluate a task, train an NDU
policy, load a production product, or issue a Learning/Training receipt.
"""

import platform
import sys

import torch

from scripts.joint_generation_v4_io import PROFILES, read_packet
from scripts.joint_generation_v4_model import JointGeneratorV4
from scripts.joint_text_training_contract import (
    MAX_PACKET_BYTES,
    MAX_WALL_MS,
    PARAMETER_GROUPS,
    encode_float,
    float_bits,
    require,
    utf8,
)

NDU_DEFAULTS = {
    "ndu.risk": "0.25",
    "ndu.discount_per_second": "1",
    "ndu.latency_weight": "0.01",
    "ndu.horizon": "2",
    "ndu.max_forecasts": "32",
    "ndu.action_micros": "1000,1000,1000,1000,1000,1000,1000",
    "ndu.critic_output": "sigmoid-quality-v1",
}
BASE_META = set(PROFILES) | {
    "width",
    "depth",
    "mode",
    "boundary",
    "core_state_profile",
    "allow_initial_stop",
    "suppress_redundant_verify",
    "inference_profile",
}


def load_predecessor(raw):
    """Accept only a complete exact exporter roundtrip within the E inspector.

    Actor checkpoints with a retained inactive NDU block and non-default NDU
    settings are deliberately unsupported by this first worker profile. The
    original exporter cannot reproduce those bytes, so they are refused rather
    than silently normalized or dropped. Boolean/configuration values are read
    from the actual predecessor, not substituted with constructor defaults.
    """
    require(len(raw) <= MAX_PACKET_BYTES, "predecessor_packet_bound")
    metadata, tensors = read_packet(raw)
    inference = metadata.get("inference_profile")
    require(
        inference in {"actor-greedy-observed-v1", "ndu-finite-deterministic-v1"},
        "inference_profile",
    )
    expected = BASE_META | (
        set(NDU_DEFAULTS) if inference == "ndu-finite-deterministic-v1" else set()
    )
    require(set(metadata) == expected, "complete_metadata_inventory")
    for key, value in {
        **PROFILES,
        "width": "32",
        "depth": "1",
        "mode": "dual",
        "boundary": "direct",
        "core_state_profile": "persistent-v1",
    }.items():
        require(metadata[key] == value, "unsupported_predecessor_profile")
    for key in ("allow_initial_stop", "suppress_redundant_verify"):
        require(metadata[key] in ("true", "false"), "predecessor_bool")
    if inference == "ndu-finite-deterministic-v1":
        require(
            all(metadata[key] == value for key, value in NDU_DEFAULTS.items()),
            "unsupported_ndu_metadata",
        )
    model = JointGeneratorV4(
        width=32,
        depth=1,
        mode=metadata["mode"],
        boundary=metadata["boundary"],
        core_state_profile=metadata["core_state_profile"],
        allow_initial_stop=metadata["allow_initial_stop"] == "true",
        suppress_redundant_verify=metadata["suppress_redundant_verify"] == "true",
    )
    expected_state = model.state_dict()
    require(set(tensors) == set(expected_state), "complete_tensor_inventory")
    for name, value in tensors.items():
        require(
            value.dtype == torch.float64
            and value.device.type == "cpu"
            and tuple(value.shape) == tuple(expected_state[name].shape),
            "predecessor_tensor_profile",
        )
    model.load_state_dict(tensors, strict=True)
    require(
        model.export_weights(inference_profile=inference) == raw, "pretrain_roundtrip"
    )
    return model, inference


def parameter_group(name):
    if name.startswith("core."):
        return "core"
    if name.startswith(
        (
            "image_encoder.",
            "audio_encoder.",
            "video_encoder.",
            "token_encoder.",
            "text_recurrent.",
            "encoder_fusion.",
        )
    ):
        return "encoder"
    if name.startswith(
        (
            "initial_slots.",
            "feedback_projection.",
            "transition_input.",
            "action_embedding.",
            "adapters.",
        )
    ):
        return "transition_and_adapters"
    if name.startswith(("text_condition.", "emissions.text.")):
        return "text_head"
    require(
        name.startswith(
            (
                "emissions.image.",
                "emissions.audio.",
                "emissions.video.",
                "actor.",
                "critic.",
                "delivery_critic.",
            )
        ),
        "unclassified_parameter",
    )
    return "other_heads"


class ParameterAccounting:
    """Count unique scalar positions, not steps, tensor names, or examples."""

    def __init__(self, model):
        self.parameters = dict(model.named_parameters())
        require(self.parameters, "empty_parameters")
        self.initial = {}
        self.present = set()
        self.nonzero = {}
        self.max_gradient = {group: 0.0 for group in PARAMETER_GROUPS}
        for name, value in self.parameters.items():
            parameter_group(name)
            require(
                value.requires_grad
                and value.dtype == torch.float64
                and value.device.type == "cpu"
                and bool(torch.isfinite(value).all()),
                "trainable_parameter_profile",
            )
            self.initial[name] = value.detach().clone()
            self.nonzero[name] = torch.zeros_like(value, dtype=torch.bool)

    def observe_gradients(self):
        for name, value in self.parameters.items():
            gradient = value.grad
            if gradient is None:
                continue
            require(
                tuple(gradient.shape) == tuple(value.shape)
                and gradient.dtype == torch.float64
                and bool(torch.isfinite(gradient).all()),
                "nonfinite_gradient",
            )
            self.present.add(name)
            self.nonzero[name] |= gradient.detach() != 0
            group = parameter_group(name)
            self.max_gradient[group] = max(
                self.max_gradient[group], float(gradient.detach().abs().max())
            )

    def observe_parameters(self):
        for value in self.parameters.values():
            require(bool(torch.isfinite(value).all()), "nonfinite_updated_parameter")

    def summary(self):
        rows = {
            group: {
                "group": group,
                "parameters": 0,
                "gradient_present_parameters": 0,
                "gradient_nonzero_parameters": 0,
                "changed_parameters": 0,
                "max_abs_gradient_f64_be": encode_float(self.max_gradient[group]),
                "max_abs_delta_f64_be": encode_float(0.0),
            }
            for group in PARAMETER_GROUPS
        }
        maxima = {group: 0.0 for group in PARAMETER_GROUPS}
        for name, value in self.parameters.items():
            row = rows[parameter_group(name)]
            row["parameters"] += value.numel()
            row["gradient_present_parameters"] += (
                value.numel() if name in self.present else 0
            )
            row["gradient_nonzero_parameters"] += int(
                torch.count_nonzero(self.nonzero[name])
            )
            delta = value.detach() - self.initial[name]
            require(bool(torch.isfinite(delta).all()), "nonfinite_parameter_delta")
            row["changed_parameters"] += int(torch.count_nonzero(delta))
            group = row["group"]
            maxima[group] = max(maxima[group], float(delta.abs().max()))
        for group in PARAMETER_GROUPS:
            rows[group]["max_abs_delta_f64_be"] = encode_float(maxima[group])
        return [rows[group] for group in PARAMETER_GROUPS]


def text_public(prefix):
    """No non-text source values or pseudo labels: all media/masks are zero."""
    public = {}
    for name, shape in (
        ("image", (1, 3, 16, 16)),
        ("audio", (1, 1024)),
        ("video", (1, 4, 3, 16, 16)),
    ):
        public[name] = torch.zeros(shape, dtype=torch.float64)
        public[name + "_mask"] = torch.zeros(shape, dtype=torch.float64)
    public["tokens"] = torch.tensor([list(utf8(prefix))], dtype=torch.float64)
    return public


def fresh_loss(model, public, continuation):
    state = model.encode(public)
    state = model.advance(state, "shared", public)
    state = model.advance(state, "text", public)
    loss, _ = model.text_loss(state, continuation)
    require(loss.ndim == 0 and bool(torch.isfinite(loss)), "nonfinite_text_loss")
    return loss


def train_candidate(request, predecessor, check_budget):
    """One genuine text sample and a fixed number of ordinary SGD steps.

    check_budget is the worker's fixed monotonic cooperative check. It is not
    a hard watchdog: a running Torch kernel or I/O operation cannot be stopped
    here. The eventual process/job owner must enforce its separate lifecycle.
    """
    require(sys.platform == "linux", "numeric_platform_profile")
    torch.set_num_threads(1)
    require(torch.get_num_threads() == 1, "torch_thread_profile")
    check_budget()
    model, inference = load_predecessor(predecessor)
    accounting = ParameterAccounting(model)
    public = text_public(request["prefix"])
    rate = float_bits(request["learning_rate_f64_be"])
    losses = []
    for _ in range(request["steps"]):
        check_budget()
        model.zero_grad(set_to_none=True)
        loss = fresh_loss(model, public, request["continuation"])
        losses.append(encode_float(float(loss.detach())))
        check_budget()
        loss.backward()
        accounting.observe_gradients()
        check_budget()
        # Plain SGD; no momentum, weight decay, clipping, skipped update, or
        # replacement target. Parameters without a gradient remain untouched.
        with torch.no_grad():
            for parameter in accounting.parameters.values():
                if parameter.grad is not None:
                    parameter.add_(parameter.grad, alpha=-rate)
        accounting.observe_parameters()
    check_budget()
    with torch.no_grad():
        losses.append(
            encode_float(float(fresh_loss(model, public, request["continuation"])))
        )
    groups = accounting.summary()
    core = groups[0]
    require(core["gradient_nonzero_parameters"] > 0, "no_core_gradient")
    require(core["changed_parameters"] > 0, "no_core_update")
    check_budget()
    candidate = model.export_weights(inference_profile=inference)
    require(
        len(candidate) <= min(MAX_PACKET_BYTES, request["maximum_artifact_bytes"]),
        "candidate_byte_budget",
    )
    require(candidate != predecessor, "unchanged_candidate")
    check_budget()
    restored, restored_profile = load_predecessor(candidate)
    require(
        restored_profile == inference
        and restored.export_weights(inference_profile=inference) == candidate,
        "candidate_roundtrip",
    )
    check_budget()
    return {
        "candidate_bytes": candidate,
        "training": {
            "requested_steps": request["steps"],
            "completed_steps": request["steps"],
            "source_samples": 1,
            "source_record_count": request["source_record_count"],
            "dataset_observed_rows": request["dataset_observed_rows"],
            "dataset_observed_bytes": request["dataset_observed_bytes"],
            "prefix_bytes": len(utf8(request["prefix"])),
            "continuation_bytes": len(utf8(request["continuation"])),
            "continuation_scalars": len(request["continuation"]),
            "losses_f64_be": losses,
            "parameter_groups": groups,
            "core_gradient_nonzero": True,
            "core_changed_parameters": core["changed_parameters"],
            "effective_wall_limit_milliseconds": min(
                MAX_WALL_MS, request["maximum_training_milliseconds"]
            ),
        },
        "runtime": {
            "python_version": sys.version.split()[0],
            "torch_version": str(torch.__version__),
            "platform": platform.system() + "-" + platform.machine(),
            "device": "cpu",
            "dtype": "float64",
            "threads": torch.get_num_threads(),
        },
    }
