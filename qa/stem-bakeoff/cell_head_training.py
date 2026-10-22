"""Offline task learning on frozen FeatureBundles; no Encoder or action execution.

Calibration uses its own cohort. Holdouts are scored only after weights and
temperature are frozen. Artifact hashes establish byte integrity, not publisher
attestation, temporal provenance, or production admission.
"""

from dataclasses import asdict, dataclass
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
from typing import Mapping
import zipfile

import numpy as np
import torch
from torch import nn

from feature_bundle import FeatureBundleV1, FeatureIdentityV1
from multimodal_bridge import _verify_optimizer_lifecycle
from native_latent import LightCellHead

TEMPERATURES = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0)
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
TRAINED_PREFIXES = ("gate.", "down.", "up.", "task_head.")


class HeadTrainingError(ValueError):
    pass


@dataclass(frozen=True)
class HeadCohortV1:
    bundle: FeatureBundleV1 | tuple[FeatureBundleV1, ...]
    labels: tuple[int, ...] | torch.Tensor
    source_group_ids: tuple[str, ...]


@dataclass(frozen=True)
class HeadTrainingConfigV1:
    task_count: int
    mode: str = "gated"
    steps: int = 200
    learning_rate: float = 0.2
    seed: int = 7
    adapter_rank: int = 4
    state_width: int = 8
    confidence_threshold: float = 0.7

    def validate(self) -> None:
        integers = ((self.task_count, 2, 256), (self.steps, 1, 5000),
                    (self.seed, 0, 2**31 - 1), (self.adapter_rank, 1, 16),
                    (self.state_width, 1, 64))
        if (any(type(v) is not int or not lo <= v <= hi for v, lo, hi in integers)
                or self.mode not in ("linear", "gated")
                or type(self.learning_rate) not in (float, int)
                or not math.isfinite(self.learning_rate)
                or not 0 < self.learning_rate <= 1
                or type(self.confidence_threshold) not in (float, int)
                or not 0 <= self.confidence_threshold <= 1):
            raise HeadTrainingError("invalid bounded Head training configuration")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _state_digest(head: LightCellHead) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(head.state_dict().items()):
        array = value.detach().cpu().contiguous().numpy()
        digest.update(_json_bytes([name, list(array.shape), str(array.dtype)]))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _new_head(width: int, config: HeadTrainingConfigV1) -> LightCellHead:
    # Isolate initialization from the caller's RNG and use identical initial
    # tensors for linear and gated arms at the same seed.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        return LightCellHead(width, state_width=config.state_width,
                             adapter_rank=config.adapter_rank,
                             task_count=config.task_count).to(dtype=torch.float32)


def _cohort(cohort: HeadCohortV1, task_count: int) -> dict:
    if type(cohort) is not HeadCohortV1:
        raise HeadTrainingError("typed Head cohort required")
    bundles = (cohort.bundle,) if type(cohort.bundle) is FeatureBundleV1 else cohort.bundle
    if (type(bundles) is not tuple or not 1 <= len(bundles) <= 32
            or any(type(b) is not FeatureBundleV1 for b in bundles)):
        raise HeadTrainingError("bounded immutable FeatureBundles required")
    identity = bundles[0].identity
    if any(b.identity != identity for b in bundles):
        raise HeadTrainingError("mixed Encoder/preprocessor/generation/scope identity")
    parts, elements, row_count = [], 0, 0
    for bundle in bundles:
        bundle.require_identity(identity)
        part = bundle.read_global()
        elements += part.numel()
        row_count += len(part)
        if elements > 4_194_304 or row_count > 4096:
            raise HeadTrainingError("frozen feature cohort exceeds training budget")
        parts.append(part.float())
    features = torch.cat(parts).contiguous()
    rows = tuple(row for b in bundles for row in b.source_record_digests)
    if (features.ndim != 2 or not 1 <= features.shape[0] <= 4096
            or not 1 <= features.shape[1] <= 4096
            or features.numel() > 4_194_304 or not bool(torch.isfinite(features).all())
            or len(rows) != features.shape[0] or len(set(rows)) != len(rows)):
        raise HeadTrainingError("invalid, repeated or over-budget frozen feature rows")
    labels = cohort.labels
    if isinstance(labels, torch.Tensor):
        if labels.dtype != torch.int64 or labels.ndim != 1:
            raise HeadTrainingError("labels must be an int64 vector")
        labels = labels.detach().cpu().clone()
    else:
        if (type(labels) not in (tuple, list)
                or any(type(label) is not int for label in labels)):
            raise HeadTrainingError("labels must contain integer class IDs")
        labels = torch.tensor(labels, dtype=torch.int64)
    if type(cohort.source_group_ids) not in (tuple, list):
        raise HeadTrainingError("explicit source-group sequence required")
    groups = tuple(cohort.source_group_ids)
    if (labels.shape != (len(rows),) or bool((labels < 0).any())
            or bool((labels >= task_count).any()) or len(groups) != len(rows)
            or any(type(g) is not str or not 1 <= len(g) <= 256 for g in groups)):
        raise HeadTrainingError("label/source-group rows do not match feature rows")
    return {"features": features, "labels": labels, "rows": rows,
            "groups": groups, "identity": identity,
            "bundle_digests": [b.bundle_digest for b in bundles]}


def task_metrics(logits: torch.Tensor, labels: torch.Tensor, *,
                 temperature: float = 1.0, confidence_threshold: float = 0.7) -> dict:
    if (not math.isfinite(temperature) or temperature <= 0
            or not 0 <= confidence_threshold <= 1
            or logits.ndim != 2 or labels.shape != (logits.shape[0],)
            or logits.shape[0] < 1 or labels.dtype != torch.int64
            or not bool(torch.isfinite(logits).all())
            or bool((labels < 0).any()) or bool((labels >= logits.shape[1]).any())):
        raise HeadTrainingError("invalid task metric inputs")
    probabilities = torch.softmax(logits.detach().double() / temperature, dim=-1)
    confidence, prediction = probabilities.max(dim=-1)
    correct = prediction.eq(labels)
    accepted = confidence >= confidence_threshold
    ece = 0.0
    bins = torch.clamp((confidence * 10).long(), max=9)
    for index in range(10):
        mask = bins == index
        if bool(mask.any()):
            ece += float(mask.double().mean() *
                         (confidence[mask].mean() - correct[mask].double().mean()).abs())
    one_hot = nn.functional.one_hot(labels, logits.shape[1]).double()
    nll = nn.functional.cross_entropy(logits.detach().double() / temperature, labels)
    return {"rows": len(labels), "accuracy": float(correct.double().mean()),
            "nll": float(nll), "brier_multiclass_sum":
            float((probabilities - one_hot).square().sum(dim=-1).mean()),
            "ece10_equal_width": ece, "coverage": float(accepted.double().mean()),
            "selective_accuracy": float(correct[accepted].double().mean())
            if bool(accepted.any()) else None, "confidence_threshold": confidence_threshold}


class TrainedCellHeadV1:
    """Frozen task-only inference API bound to the exact feature identity."""
    def __init__(self, head: LightCellHead, identity: FeatureIdentityV1, report: dict):
        self._head = head.eval().requires_grad_(False)
        self.identity = identity
        self._report = copy.deepcopy(report)

    @property
    def report(self) -> dict:
        return copy.deepcopy(self._report)

    def predict_task(self, bundle: FeatureBundleV1) -> dict:
        if type(bundle) is not FeatureBundleV1 or bundle.identity != self.identity:
            raise HeadTrainingError("Head Encoder/preprocessor/generation/scope mismatch")
        bundle.require_identity(self.identity)
        if _state_digest(self._head) != self._report["trained_tensor_sha256"]:
            raise HeadTrainingError("immutable Head weights changed")
        features = bundle.read_global().float()
        if features.shape[1] != self._head.width:
            raise HeadTrainingError("Head feature width mismatch")
        with torch.inference_mode():
            state = torch.zeros((len(features), self._head.state_width))
            logits = self._head(features, state)["task_logits"]
            probabilities = torch.softmax(logits / self._report["temperature"], dim=-1)
        return {"task_logits": logits.clone(),
                "temperature": self._report["temperature"],
                "task_probabilities": probabilities.clone(),
                "accepted": probabilities.max(dim=-1).values >=
                self._report["config"]["confidence_threshold"],
                "feature_bundle_sha256": bundle.bundle_digest, "authority": "DENY_ALL"}


def train_cell_head(train: HeadCohortV1, calibration: HeadCohortV1,
                    holdouts: Mapping[str, HeadCohortV1], *,
                    config: HeadTrainingConfigV1) -> TrainedCellHeadV1:
    """Train private task parameters; never accept a caller-supplied optimizer."""
    config.validate()
    if (not isinstance(holdouts, Mapping) or not 1 <= len(holdouts) <= 6
            or any(type(k) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", k)
                   or k in ("train", "calibration") for k in holdouts)):
        raise HeadTrainingError("named, separate holdout cohorts required")
    cohorts = {"train": _cohort(train, config.task_count),
               "calibration": _cohort(calibration, config.task_count)}
    cohorts.update({name: _cohort(value, config.task_count) for name, value in holdouts.items()})
    identity = cohorts["train"]["identity"]
    width = cohorts["train"]["features"].shape[1]
    seen_rows, seen_groups = set(), set()
    for cohort in cohorts.values():
        if cohort["identity"] != identity or cohort["features"].shape[1] != width:
            raise HeadTrainingError("cohort feature identities or widths differ")
        rows, groups = set(cohort["rows"]), set(cohort["groups"])
        if seen_rows.intersection(rows) or seen_groups.intersection(groups):
            raise HeadTrainingError("source record/group leakage across splits")
        seen_rows.update(rows)
        seen_groups.update(groups)
    if len(torch.unique(cohorts["train"]["labels"])) < 2:
        raise HeadTrainingError("training requires at least two observed classes")
    head = _new_head(width, config)
    initial = {k: v.detach().clone() for k, v in head.state_dict().items()}
    initial_digest = _state_digest(head)
    for name, parameter in head.named_parameters():
        parameter.requires_grad_(name.startswith("task_head.") or
                                 (config.mode == "gated" and name.startswith(TRAINED_PREFIXES)))
    parameters = [p for p in head.parameters() if p.requires_grad]
    optimizer = torch.optim.SGD(parameters, lr=config.learning_rate)
    owner_ids = tuple(id(p) for p in parameters)
    states = {name: torch.zeros((len(c["features"]), config.state_width))
              for name, c in cohorts.items()}
    with torch.no_grad():
        initial_logits = {name: head(c["features"], states[name])["task_logits"].clone()
                          for name, c in cohorts.items()}
    losses = []
    for _ in range(config.steps):
        _verify_optimizer_lifecycle(optimizer)
        if tuple(id(p) for g in optimizer.param_groups for p in g["params"]) != owner_ids:
            raise HeadTrainingError("optimizer crossed the private task Head boundary")
        optimizer.zero_grad(set_to_none=True)
        logits = head(cohorts["train"]["features"], states["train"])["task_logits"]
        loss = nn.functional.cross_entropy(logits, cohorts["train"]["labels"])
        if not bool(torch.isfinite(loss)):
            raise HeadTrainingError("nonfinite task training loss")
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):
            raise HeadTrainingError("missing or nonfinite private Head gradient")
        nn.utils.clip_grad_norm_(parameters, max_norm=5.0, error_if_nonfinite=True)
        _verify_optimizer_lifecycle(optimizer)
        optimizer.step()
        if any(not bool(torch.isfinite(p).all()) for p in head.parameters()):
            raise HeadTrainingError("nonfinite trained Head; no artifact produced")
        losses.append(float(loss.detach()))
    trained_digest = _state_digest(head)
    changed = [name for name, value in head.state_dict().items()
               if not torch.equal(initial[name], value)]
    if any(not name.startswith(TRAINED_PREFIXES if config.mode == "gated" else
                               ("task_head.",)) for name in changed):
        raise HeadTrainingError("untrained action/value/uncertainty weights changed")
    head.eval().requires_grad_(False)
    with torch.no_grad():
        logits = {name: head(c["features"], states[name])["task_logits"].clone()
                  for name, c in cohorts.items()}
    # Only calibration labels determine temperature. No heldout selects model,
    # step count, temperature, abstention threshold, or candidate winner.
    cal = cohorts["calibration"]
    temperature = min(TEMPERATURES, key=lambda t: (
        float(nn.functional.cross_entropy(logits["calibration"].double() / t, cal["labels"])),
        abs(math.log(t)), t))
    split_report = {}
    for name, c in cohorts.items():
        metrics = {stage: task_metrics(output, c["labels"], temperature=temp,
                   confidence_threshold=config.confidence_threshold)
                   for stage, output, temp in (("initial", initial_logits[name], 1.0),
                   ("trained", logits[name], 1.0), ("calibrated", logits[name], temperature))}
        split_report[name] = {"bundle_digests": c["bundle_digests"],
            "source_record_digests": list(c["rows"]),
            "source_group_sha256": hashlib.sha256(_json_bytes(c["groups"])).hexdigest(),
            "labels_sha256": hashlib.sha256(c["labels"].numpy().tobytes()).hexdigest(),
            "unique_source_groups": len(set(c["groups"])), "metrics": metrics}
    report = {"schema": "hepta.trained-cell-task-head.v1", "config": asdict(config),
        "feature_identity": asdict(identity), "feature_width": width,
        "initial_tensor_sha256": initial_digest, "trained_tensor_sha256": trained_digest,
        "optimizer": "torch.optim.SGD", "optimizer_steps": config.steps,
        "optimizer_owned_parameter_names": [name for name, _ in head.named_parameters()
            if name.startswith(TRAINED_PREFIXES if config.mode == "gated" else ("task_head.",))],
        "trainable_parameter_count": sum(p.numel() for p in parameters),
        "resident_parameter_count": sum(p.numel() for p in head.parameters()),
        "optimizer_state_bytes": 0, "changed_parameter_names": changed,
        "initial_train_loss": losses[0], "last_train_loss_before_step": losses[-1],
        "temperature": temperature, "temperature_grid": list(TEMPERATURES),
        "calibration_target": "task_logits_only", "calibration_split": "calibration",
        "action_head_status": "untrained", "value_head_status": "untrained",
        "uncertainty_head_status": "untrained_not_calibrated",
        "gate_is_calibrated_routing_probability": False,
        "local_state_training": "zero_state_only", "encoder_training_steps": 0,
        "source_groups_disjoint": True, "temporal_provenance_verified": False,
        "splits": split_report, "authority": "DENY_ALL", "mode": "SHADOW_ONLY",
        "production_activation_allowed": False}
    return TrainedCellHeadV1(head, identity, report)


def save_head_artifact(result: TrainedCellHeadV1, directory: str | Path) -> dict:
    """Create new NPZ tensor bytes and a manifest; never pickle a live module."""
    if _state_digest(result._head) != result._report["trained_tensor_sha256"]:
        raise HeadTrainingError("Head weights changed before artifact serialization")
    stream = io.BytesIO()
    np.savez(stream, **{name: value.detach().cpu().numpy()
                       for name, value in result._head.state_dict().items()})
    weights = stream.getvalue()
    if len(weights) > MAX_ARTIFACT_BYTES:
        raise HeadTrainingError("Head artifact exceeds byte budget")
    manifest = {"schema": "hepta.cell-head-artifact.v1", "report": result.report,
                "weights_file": "weights.npz", "weights_file_sha256":
                hashlib.sha256(weights).hexdigest()}
    manifest_bytes = _json_bytes(manifest)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise HeadTrainingError("Head provenance manifest exceeds byte budget")
    target = Path(directory)
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    with (target / "weights.npz").open("xb") as output:
        output.write(weights)
    with (target / "manifest.json").open("xb") as output:
        output.write(manifest_bytes)
    return {"directory": str(target), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "weights_file_sha256": manifest["weights_file_sha256"]}


def load_head_artifact(directory: str | Path, *, expected_manifest_sha256: str,
                       expected_identity: FeatureIdentityV1) -> TrainedCellHeadV1:
    """Load bounded plain tensors only under an externally retained manifest hash."""
    target = Path(directory)
    if (type(expected_identity) is not FeatureIdentityV1
            or type(expected_manifest_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None):
        raise HeadTrainingError("expected manifest and feature identity are required")
    if target.is_symlink() or not target.is_dir():
        raise HeadTrainingError("artifact directory must be a real local directory")
    payloads = {}
    for name, budget in (("manifest.json", MAX_MANIFEST_BYTES), ("weights.npz", MAX_ARTIFACT_BYTES)):
        path = target / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > budget:
            raise HeadTrainingError("linked, irregular or oversized Head artifact")
        payloads[name] = path.read_bytes()
        if len(payloads[name]) > budget:
            raise HeadTrainingError("Head artifact grew while reading")
    if hashlib.sha256(payloads["manifest.json"]).hexdigest() != expected_manifest_sha256:
        raise HeadTrainingError("Head manifest does not match retained digest")
    manifest = json.loads(payloads["manifest.json"])
    report = manifest["report"]
    if (manifest["schema"] != "hepta.cell-head-artifact.v1"
            or manifest["weights_file"] != "weights.npz"
            or hashlib.sha256(payloads["weights.npz"]).hexdigest() != manifest["weights_file_sha256"]
            or report["feature_identity"] != asdict(expected_identity)
            or report["authority"] != "DENY_ALL"
            or report["mode"] != "SHADOW_ONLY"
            or report["production_activation_allowed"] is not False):
        raise HeadTrainingError("Head artifact identity, weights or authority mismatch")
    config = HeadTrainingConfigV1(**report["config"])
    config.validate()
    if type(report["feature_width"]) is not int or not 1 <= report["feature_width"] <= 4096:
        raise HeadTrainingError("invalid artifact feature width")
    head = _new_head(report["feature_width"], config)
    expected_state = head.state_dict()
    with zipfile.ZipFile(io.BytesIO(payloads["weights.npz"])) as archive:
        entries = archive.infolist()
        if (len(entries) != len(expected_state)
                or {entry.filename for entry in entries} != {name + ".npy" for name in expected_state}
                or sum(entry.file_size for entry in entries) > MAX_ARTIFACT_BYTES):
            raise HeadTrainingError("invalid or over-budget Head tensor archive")
        # A tiny NPY member can declare a huge array. Validate headers before
        # np.load can allocate from their shapes, even under a retained hash.
        for entry in entries:
            expected = expected_state[entry.filename[:-4]]
            with archive.open(entry) as stream:
                try:
                    version = np.lib.format.read_magic(stream)
                    if version not in ((1, 0), (2, 0)):
                        raise ValueError("unsupported NPY version")
                    size_width = 2 if version == (1, 0) else 4
                    size_bytes = stream.read(size_width)
                    header_size = int.from_bytes(size_bytes, "little")
                    if len(size_bytes) != size_width or not 0 < header_size <= 4096:
                        raise ValueError("oversized or incomplete NPY header")
                    header = stream.read(header_size)
                    if len(header) != header_size:
                        raise ValueError("truncated NPY header")
                    reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                              else np.lib.format.read_array_header_2_0)
                    shape, fortran, dtype = reader(io.BytesIO(size_bytes + header),
                                                  max_header_size=4096)
                except (ValueError, EOFError, zipfile.BadZipFile) as error:
                    raise HeadTrainingError("invalid Head tensor NPY header") from error
                if (shape != tuple(expected.shape) or fortran or dtype != np.dtype("float32")
                        or entry.file_size - stream.tell() != expected.numel() * 4):
                    raise HeadTrainingError("Head tensor header shape/dtype/byte length mismatch")
    with np.load(io.BytesIO(payloads["weights.npz"]), allow_pickle=False) as arrays:
        if set(arrays.files) != set(expected_state):
            raise HeadTrainingError("Head tensor inventory differs")
        state = {}
        for name, expected in expected_state.items():
            array = arrays[name]
            if array.dtype != np.float32 or array.shape != tuple(expected.shape) or not np.isfinite(array).all():
                raise HeadTrainingError("invalid Head tensor shape/dtype/value")
            state[name] = torch.from_numpy(array.copy())
    head.load_state_dict(state, strict=True)
    if (_state_digest(head) != report["trained_tensor_sha256"]
            or type(report["temperature"]) not in (float, int)
            or report["temperature"] not in TEMPERATURES):
        raise HeadTrainingError("Head tensor or calibration identity drift")
    return TrainedCellHeadV1(head, expected_identity, report)
