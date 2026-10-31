"""Public two-preview task execution and a separate offline reward bank.

Pass an eval-mode raw generator with encode/step/decode/hidden, not the
ControlledSnapshot wrapper whose encode already applies a two-action plan.
prepare_episode accepts Observation only. finish_episode commits one selected
action before executing it; it never evaluates unchosen continuations. An
offline bank may be built only for declared training/development observations.
All counts are actual example calls, not FLOPs or assumed economic charges.
"""

from dataclasses import dataclass, field
import hashlib
import json
import math
import operator
from pathlib import Path
import time

import torch

from ..v6.data import DIGIT_OFFSET, Observation, render_tokens
from ..v6.neural import NeuralState, parameter_hash
from ..v6.observer import CAPTION, observe_tensors, read_bundle, write_bundle


ACTIONS = ("stop", "refine_image", "refine_text", "refine_semantic", "couple")
FIRST_ACTION = "couple"
FEATURE_NAMES = (
    "left_text_digit_confidence", "right_text_digit_confidence",
    "left_image_digit_confidence", "right_image_digit_confidence",
    "left_text_image_disagreement", "right_text_image_disagreement",
    "public_missing_fraction", "mean_pixel_bernoulli_entropy",
)


@dataclass(frozen=True)
class HardOutput:
    token_ids: torch.Tensor
    pixels_u8: torch.Tensor
    captions: tuple[str, ...]
    receipts: tuple[dict, ...] = ()
    resources: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Prepared:
    features0: torch.Tensor
    features1: torch.Tensor
    preview0: HardOutput
    preview1: HardOutput
    resources: dict
    model_sha256: str
    case_ids: tuple[str, ...]
    output_root: Path | None
    _state: NeuralState


def _timed(resources, phase, call):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = call()
    resources[phase + "_wall_ns"] = resources.get(phase + "_wall_ns", 0) + time.perf_counter_ns() - wall
    resources[phase + "_cpu_ns"] = resources.get(phase + "_cpu_ns", 0) + time.process_time_ns() - cpu
    return result


def _case_names(case_ids, count):
    names = tuple(case_ids) if case_ids is not None else tuple(f"case-{i:06d}" for i in range(count))
    if (len(names) != count or len(set(names)) != count
            or any(not isinstance(n, str) or not n or n in {".", ".."}
                   or "/" in n or "\\" in n for n in names)):
        raise ValueError("Case identities must be unique single path components")
    return names


def _frozen_eval(model, observer=None):
    if model.training or (observer is not None and observer.training):
        raise ValueError("Task execution requires eval-mode models")
    if any(p.device.type != "cpu" for p in model.parameters()):
        raise ValueError("This registered task measures CPU execution only")
    if observer is not None and any(p.requires_grad for p in observer.parameters()):
        raise ValueError("The public recognizer must be frozen")


def _hard_output(output):
    pixels = output.image_logits.detach().cpu().sigmoid()
    if pixels.ndim != 4 or pixels.shape[1:] != (1, 28, 56) or not torch.isfinite(pixels).all():
        raise ValueError("Invalid generated image")
    tokens = output.token_ids.detach().cpu().clone()
    return HardOutput(tokens, (pixels * 255).round().to(torch.uint8),
                      tuple(render_tokens(row) for row in tokens))


def _persist(hard, root, names, phase, resources):
    if root is None:
        return hard
    restored_pixels, restored_captions, receipts = [], [], []
    for index, name in enumerate(names):
        paths = write_bundle(root / name / phase, hard.captions[index],
                             hard.pixels_u8[index].float() / 255)
        pixels, caption, hashes = read_bundle(paths)
        restored = (pixels * 255).round().to(torch.uint8)
        if caption != hard.captions[index] or not torch.equal(restored[0], hard.pixels_u8[index]):
            raise ValueError("Delivered preview/final bytes differ from generated content")
        restored_pixels.append(restored)
        restored_captions.append(caption)
        receipts.append({"case_id": name, "phase": phase, "paths": paths,
                         "sha256": hashes, "readback_monotonic_ns": time.monotonic_ns()})
    for key in ("png_writes", "png_reads", "utf8_writes", "utf8_reads"):
        resources[key] = resources.get(key, 0) + len(names)
    return HardOutput(hard.token_ids, torch.cat(restored_pixels), tuple(restored_captions), tuple(receipts))


def _logit_evidence(hard, output):
    """Bind the public digit-position logits before deriving preview features."""
    if not hard.receipts:
        return
    logits = output.text_logits.detach().cpu()[:, [1, 3]].contiguous()
    if logits.dtype != torch.float32 or not torch.isfinite(logits).all():
        raise ValueError("Preview evidence requires finite original float32 logits")
    for index, receipt in enumerate(hard.receipts):
        raw = logits[index].numpy().astype("<f4", copy=False).tobytes()
        receipt.update(public_text_logits=logits[index].tolist(),
                       public_text_logits_sha256=hashlib.sha256(raw).hexdigest(),
                       evidence_monotonic_ns=time.monotonic_ns())


@torch.inference_mode()
def public_features(observation, neural_output, observer, hard_output):
    """Eight bounded features; no Target, labels, source truth, or future output.

    Text confidences are maximum absolute vocabulary probabilities among the
    ten digit tokens at the two digit positions. Invalid caption grammar gives
    disagreement=1 on both sides. Pixel entropy treats delivered uint8 intensity
    as a Bernoulli parameter; it is a declared heuristic, not calibrated risk.
    """
    if not isinstance(observation, Observation):
        raise TypeError("Public features require Observation, never Batch/Target")
    _frozen_eval(observer, observer)
    pixels = hard_output.pixels_u8.float() / 255
    count = len(pixels)
    if (hard_output.pixels_u8.dtype != torch.uint8 or pixels.shape != observation.pixels.shape
            or len(hard_output.captions) != count or neural_output.text_logits.shape[:2] != (count, 7)
            or observation.mask.shape != pixels.shape or not torch.isfinite(observation.mask).all()
            or observation.mask.min() < 0 or observation.mask.max() > 1):
        raise ValueError("Public feature input shape/range mismatch")
    words = neural_output.text_logits.detach().cpu().softmax(-1)
    text_confidence = words[:, [1, 3], DIGIT_OFFSET:DIGIT_OFFSET + 10].amax(-1)
    image_probabilities = torch.stack((observer(pixels[:, :, :, :28]).softmax(-1),
                                       observer(pixels[:, :, :, 28:]).softmax(-1)), dim=1)
    image_confidence, image_digits = image_probabilities.max(-1)
    disagreements = torch.ones(count, 2)
    for index, caption in enumerate(hard_output.captions):
        match = CAPTION.fullmatch(caption.strip())
        if match:
            disagreements[index] = torch.tensor([int(match[side + 1]) != int(image_digits[index, side])
                                                  for side in range(2)], dtype=torch.float32)
    missing = 1 - observation.mask.detach().cpu().float().flatten(1).mean(1)
    entropy = -(torch.special.xlogy(pixels, pixels)
                + torch.special.xlogy(1 - pixels, 1 - pixels)).flatten(1).mean(1) / math.log(2)
    features = torch.cat((text_confidence, image_confidence, disagreements,
                          missing[:, None], entropy[:, None]), dim=1).float()
    if not torch.isfinite(features).all() or features.min() < -1e-6 or features.max() > 1 + 1e-6:
        raise ValueError("Nonfinite or unbounded public feature")
    return features.clamp(0, 1).detach().clone()


@torch.inference_mode()
def prepare_episode(model, observation, reward_observer, *, noise_seed,
                    output_root=None, case_ids=None):
    """Encode, decode preview0, couple, decode preview1, then expose both fields.

    When output_root is given, each preview is written and reopened before its
    features are computed. The later selector receives no private target.
    """
    if not isinstance(observation, Observation) or len(observation.pixels) == 0:
        raise TypeError("A nonempty public Observation is required")
    _frozen_eval(model, reward_observer)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    fingerprint, observer_hash = parameter_hash(model), parameter_hash(reward_observer)
    count = len(observation.pixels)
    names = _case_names(case_ids, count)
    root = Path(output_root) if output_root is not None else None
    resources = {"encoder_examples": count, "encoder_batches": 1,
                 "transition_examples": count, "transition_batches": 1,
                 "decoder_examples": 2 * count, "decoder_batches": 2,
                 "observer_digit_examples": 4 * count, "observer_batches": 4,
                 "target_accesses": 0}
    rng = torch.Generator().manual_seed(int(noise_seed))
    noise = torch.randn(count, model.hidden, generator=rng)
    state0 = _timed(resources, "neural", lambda: model.encode(observation, noise))
    output0 = _timed(resources, "neural", lambda: model.decode(state0))
    hard0 = _timed(resources, "media", lambda: _persist(_hard_output(output0), root, names, "preview0", resources))
    _logit_evidence(hard0, output0)
    features0 = _timed(resources, "features", lambda: public_features(observation, output0, reward_observer, hard0))
    state1 = _timed(resources, "neural", lambda: model.step(state0, FIRST_ACTION))
    output1 = _timed(resources, "neural", lambda: model.decode(state1))
    hard1 = _timed(resources, "media", lambda: _persist(_hard_output(output1), root, names, "preview1", resources))
    _logit_evidence(hard1, output1)
    features1 = _timed(resources, "features", lambda: public_features(observation, output1, reward_observer, hard1))
    if fingerprint != parameter_hash(model) or observer_hash != parameter_hash(reward_observer):
        raise RuntimeError("Preview execution mutated frozen parameters")
    resources.update(total_wall_ns=time.perf_counter_ns() - wall,
                     total_cpu_ns=time.process_time_ns() - cpu)
    return Prepared(features0, features1, hard0, hard1, resources, fingerprint, names, root, state1)


def _action_indices(actions, count):
    values = actions.detach().cpu().tolist() if isinstance(actions, torch.Tensor) else list(actions)
    indices = []
    for value in values:
        if isinstance(value, str):
            index = ACTIONS.index(value)
        elif isinstance(value, bool):
            raise ValueError("A Boolean is not a continuation action")
        else:
            index = operator.index(value)
        if index < 0 or index >= len(ACTIONS):
            raise ValueError("Unknown continuation action")
        indices.append(index)
    if len(indices) != count:
        raise ValueError("One continuation action per episode is required")
    return torch.tensor(indices, dtype=torch.long)


@torch.inference_mode()
def finish_episode(model, prepared, actions, *, output_root=None, case_ids=None):
    """Commit selected actions, execute only those continuations, deliver finals.

    Stop saves the additional transition; every action still decodes and writes
    its selected final output. File-backed execution must use the original
    preview destination, so previews cannot be invented after selection.
    """
    _frozen_eval(model)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if parameter_hash(model) != prepared.model_sha256:
        raise ValueError("Continuation model differs from the preview model")
    root, names = prepared.output_root, prepared.case_ids
    if output_root is not None and (root is None or Path(output_root) != root):
        raise ValueError("Final destination must equal the committed preview destination")
    if case_ids is not None and tuple(case_ids) != names:
        raise ValueError("Final case identities must equal preview identities")
    selected = _action_indices(actions, len(names))
    resources = {"encoder_examples": 0, "encoder_batches": 0,
                 "transition_examples": int((selected != 0).sum()),
                 "transition_batches": int(selected[selected != 0].unique().numel()),
                 "decoder_examples": len(names), "decoder_batches": 1,
                 "observer_digit_examples": 0, "observer_batches": 0,
                 "target_accesses": 0, "unchosen_continuations_executed": 0}
    if root is not None:
        for index, name in enumerate(names):
            field_bytes = torch.stack((prepared.features0[index], prepared.features1[index])).numpy().tobytes()
            decision = {"case_id": name, "action": ACTIONS[int(selected[index])],
                        "model_sha256": prepared.model_sha256,
                        "public_features_sha256": hashlib.sha256(field_bytes).hexdigest(),
                        "preview_sha256": [prepared.preview0.receipts[index]["sha256"],
                                           prepared.preview1.receipts[index]["sha256"]],
                        "preview_logits_sha256": [prepared.preview0.receipts[index]["public_text_logits_sha256"],
                                                  prepared.preview1.receipts[index]["public_text_logits_sha256"]],
                        "committed_monotonic_ns": time.monotonic_ns()}
            with (root / name / "decision.json").open("x", encoding="utf-8") as stream:
                json.dump(decision, stream, sort_keys=True, allow_nan=False)
                stream.write("\n")
        resources["decision_json_writes"] = len(names)
    groups, positions = [], []
    state = prepared._state
    for action_index in selected.unique().tolist():
        ids = torch.where(selected == action_index)[0]
        subset = NeuralState(*(getattr(state, name)[ids] for name in ("h", "image", "text", "context")),
                             state.snapshot_digest)
        if action_index:
            subset = _timed(resources, "neural", lambda: model.step(subset, ACTIONS[action_index]))
        groups.append(subset)
        positions.append(ids)
    order = torch.cat(positions).argsort()
    final_state = NeuralState(*(torch.cat([getattr(group, name) for group in groups])[order]
                               for name in ("h", "image", "text", "context")), state.snapshot_digest)
    output = _timed(resources, "neural", lambda: model.decode(final_state))
    hard = _timed(resources, "media", lambda: _persist(_hard_output(output), root, names, "final", resources))
    if parameter_hash(model) != prepared.model_sha256:
        raise RuntimeError("Continuation execution mutated parameters")
    resources.update(total_wall_ns=time.perf_counter_ns() - wall,
                     total_cpu_ns=time.process_time_ns() - cpu)
    return HardOutput(hard.token_ids, hard.pixels_u8, hard.captions, hard.receipts, resources)


@torch.inference_mode()
def build_bank(model, batch, reward_observer, *, noise_seed, role="train"):
    """Offline exact hard-output reward table; never pass this object to a policy.

    role is a caller declaration, not an independent data-lineage certificate.
    The protocol owner must enforce train/development source membership. Audit
    scoring is intentionally absent; deployment uses prepare/finish directly.
    """
    if role not in {"train", "development"}:
        raise ValueError("Unchosen-action reward banks are restricted to train/development")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    observer_hash = parameter_hash(reward_observer)
    prepared = prepare_episode(model, batch.observation, reward_observer, noise_seed=noise_seed)
    outputs, rewards = [], []
    resources = dict(prepared.resources)
    count = len(batch.observation.pixels)
    for index in range(len(ACTIONS)):
        final = finish_episode(model, prepared, [index] * count)
        scored = _timed(resources, "reward", lambda: observe_tensors(
            reward_observer, final.pixels_u8.float() / 255, final.captions,
            batch.target.pixels, batch.target.labels))
        outputs.append(final)
        rewards.append(torch.tensor([row["utility"] for row in scored], dtype=torch.float64))
        for key, value in final.resources.items():
            if key not in {"total_wall_ns", "total_cpu_ns"}:
                resources[key] = resources.get(key, 0) + value
        resources["observer_digit_examples"] += 2 * count
        resources["observer_batches"] += 2
    if observer_hash != parameter_hash(reward_observer):
        raise RuntimeError("Offline reward scoring mutated the frozen observer")
    resources.pop("unchosen_continuations_executed", None)
    resources.update(target_accesses=2 * len(ACTIONS), private_score_batches=len(ACTIONS),
                     offline_action_rows=count * len(ACTIONS),
                     offline_nonstop_continuations=count * (len(ACTIONS) - 1),
                     total_wall_ns=time.perf_counter_ns() - wall,
                     total_cpu_ns=time.process_time_ns() - cpu)
    return {"features0": prepared.features0, "features1": prepared.features1,
            "token_ids": torch.stack([out.token_ids for out in outputs], dim=1),
            "pixels_u8": torch.stack([out.pixels_u8 for out in outputs], dim=1),
            "captions": tuple(tuple(out.captions[row] for out in outputs) for row in range(count)),
            "reward": torch.stack(rewards, dim=1), "actions": ACTIONS,
            "model_sha256": prepared.model_sha256, "reward_observer_sha256": observer_hash,
            "role": role, "resources": resources}
