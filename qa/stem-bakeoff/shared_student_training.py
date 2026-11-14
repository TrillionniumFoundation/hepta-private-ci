"""Small, genuinely shared latent student trained from independent raw slots.

The new 133,312-parameter profile is not an EG2 fine-tune or a trained 150M
model. Teacher shards are detached targets. Existing Cell/Encoder identities
cannot be silently reused after this separate shared-model update.
"""

import copy
from dataclasses import asdict, dataclass, replace
import hashlib
import io
import json
from pathlib import Path
import stat
import threading
import zipfile

import numpy as np
import torch
from torch import nn

from cell_evolution_snapshot import WithdrawalViewV1, check_sources, digest
from cell_head_training import _json_bytes, _state_digest
from native_latent import StemSpec, build_encoder
from offline_shard_distill import PairedCohort, SPLITS, _prepare, run_offline_distillation

MODEL_ID = "hepta_shared_tiny64_v1"
TEACHER = "embeddinggemma2_740m"
TEACHER_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
TEACHER_INVENTORY = "036c9188478057bada1b51ef856f3567509daf1e85efb9da283be1a69be0cb9b"
SOURCE_KEYS = {"image_id", "caption_id", "image_sha256", "text_sha256", "source_group_id",
               "teacher_image_source_sha256", "teacher_text_source_sha256", "source_record_sha256"}


def tensor_sha(tensor):
    return hashlib.sha256(tensor.detach().contiguous().cpu().numpy().tobytes()).hexdigest()


@dataclass(frozen=True)
class SharedStudentScopeV1:
    scope_id: str

    def __post_init__(self):
        WithdrawalViewV1(self.scope_id)  # Apply the same bounded scope rules.


class TinySharedEncoderV1(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = build_encoder(StemSpec(MODEL_ID, 64, 1, 4, 2), device="cpu", trainable=True)

    def forward(self, slots):
        if (type(slots) is not torch.Tensor or slots.device.type != "cpu"
                or slots.dtype != torch.float32 or slots.ndim != 3 or slots.shape[1:] != (32, 64)
                or not 1 <= len(slots) <= 8 or not torch.isfinite(slots).all()):
            raise ValueError("invalid bounded independent raw slots")
        present = slots[:, :, 63] == 1
        if not present.any(dim=1).all():
            raise ValueError("student input has no present modality")
        return self.encoder(slots, src_key_padding_mask=~present) * present.unsqueeze(-1)


def new_student(seed):
    if type(seed) is not int or not 0 <= seed < 2**31 or torch.get_default_dtype() != torch.float32:
        raise ValueError("bounded seed and float32 student ABI required")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        return nn.ModuleDict({"student": TinySharedEncoderV1(), "readout": nn.Linear(64, 1536)})


def validate_replay(cohorts, records, *, teacher_bank_sha256, input_manifest_sha256):
    if set(cohorts) != set(SPLITS) or set(records) != set(SPLITS):
        raise ValueError("all five source-bound split roles required")
    seen, closure = set(), {teacher_bank_sha256, input_manifest_sha256, TEACHER_INVENTORY}
    for name in SPLITS:
        rows = records[name]
        if type(cohorts[name]) is not PairedCohort or not 1 <= len(rows) <= 8:
            raise ValueError("bounded paired replay required")
        for row in rows:
            if (set(row) != SOURCE_KEYS or type(row["image_id"]) is not int
                    or type(row["caption_id"]) is not int or row["image_id"] < 0 or row["caption_id"] < 0
                    or row["source_group_id"] != f"coco2017:{row['image_id']}"
                    or digest({k: v for k, v in row.items() if k != "source_record_sha256"}) != row["source_record_sha256"]):
                raise ValueError("source record/group witness mismatch")
            if row["source_group_id"] in seen:
                raise ValueError("source group crosses shared-student roles")
            seen.add(row["source_group_id"])
            closure.add(digest(["shared-student-source-group.v1", row["source_group_id"]]))
            closure.update(v for k, v in row.items() if k.endswith("sha256"))
        if (cohorts[name].sample_digests != tuple(r["source_record_sha256"] for r in rows)
                or cohorts[name].expected_source_sha256 != digest(rows)):
            raise ValueError("teacher shard/ordered raw source binding differs")
    if any(type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
           for value in closure):
        raise ValueError("invalid shared-student provenance closure")
    return sorted(closure)


def _checked_file(directory, name, limit, expected):
    root = Path(directory)
    if (root.is_symlink() or not root.is_dir() or type(expected) is not str
            or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected)):
        raise ValueError("real local artifact directory required")
    path = root / name
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
        raise ValueError("shared-student artifact file boundary")
    data = path.read_bytes()
    if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("shared-student artifact byte pin differs")
    return data


class FrozenSharedStudentV1:
    def __init__(self, model, manifest, manifest_sha256):
        self._model = model.eval().requires_grad_(False)
        self._manifest = copy.deepcopy(manifest)
        self.manifest_sha256 = manifest_sha256
        self._identity = SharedStudentScopeV1(manifest["scope_id"])
        self._frontier = copy.deepcopy(manifest["withdrawal_view"])
        self._lock = threading.RLock()

    @property
    def report(self):
        return copy.deepcopy(self._manifest)

    def predict_slots(self, slots, *, role, expected_slots_sha256, withdrawal_provider):
        """Replay a source-bound role; arbitrary new inputs require new evidence."""
        with self._lock:
            def check():
                if (hashlib.sha256(_json_bytes(self._manifest)).hexdigest() != self.manifest_sha256
                        or _state_digest(self._model) != self._manifest["trained_tensor_sha256"]
                        or any(p.requires_grad or p.grad is not None for p in self._model.parameters())):
                    raise ValueError("shared student frozen state changed")
                view = check_sources((), self._identity, withdrawal_provider, self._frontier)
                self._frontier = asdict(view)  # Retain even a newly revoked frontier.
                return check_sources(self._manifest["source_closure"], self._identity, lambda: view)
            before = check()
            if (role not in SPLITS or expected_slots_sha256 !=
                    self._manifest["training"]["paired_split_receipts"][role]["student_slot_sha256"]):
                raise ValueError("student input role or artifact source-slot binding differs")
            if (type(slots) is not torch.Tensor or slots.device.type != "cpu"
                    or slots.dtype != torch.float32 or slots.shape[1:] != (32, 64)
                    or not 1 <= len(slots) <= 8 or not torch.isfinite(slots).all()
                    or slots.requires_grad or slots.grad_fn is not None):
                raise ValueError("bounded frozen independent raw slots required")
            frozen = slots.detach().clone()
            if tensor_sha(frozen) != expected_slots_sha256:
                raise ValueError("independent input slots differ from owner pin")
            with torch.inference_mode():
                encoded = self._model["student"](frozen)
                prediction = self._model["readout"](encoded.mean(1))
            if check() != before or tensor_sha(slots) != expected_slots_sha256:
                raise ValueError("input or source frontier changed; discard shared output")
            return {"shared_slots": encoded.clone(), "teacher_prediction": prediction.clone(),
                    "shared_model_manifest_sha256": self.manifest_sha256,
                    "input_manifest_sha256": self._manifest["input_manifest_sha256"],
                    "source_record_digests": [r["source_record_sha256"] for r in self._manifest["records"][role]],
                    "authority": "DENY_ALL"}


def load_shared_student(directory, *, expected_manifest_sha256, withdrawal_provider):
    data = _checked_file(directory, "manifest.json", 2 * 1024 * 1024, expected_manifest_sha256)
    manifest = json.loads(data)
    if (manifest["schema"] != "hepta.shared-tiny-student-artifact.v1" or manifest["model_id"] != MODEL_ID
            or manifest["authority"] != "DENY_ALL" or manifest["production_activation_allowed"] is not False
            or manifest["mode"] != "SHADOW_ONLY" or manifest["purpose"] != "research"
            or manifest["shared_model_generation"] != 1 or manifest["old_cell_or_feature_generation_reuse_allowed"] is not False
            or type(manifest["source_closure"]) is not list or not 1 <= len(manifest["source_closure"]) <= 512
            or manifest["source_closure"] != sorted(set(manifest["source_closure"]))
            or any(type(v) is not str or len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
                   for v in manifest["source_closure"])
            or manifest["parameter_count"] != 133312 or manifest["resident_tensor_bytes"] != 533248):
        raise ValueError("invalid shared-student profile or authority")
    identity = SharedStudentScopeV1(manifest["scope_id"])
    check_sources(manifest["source_closure"], identity, withdrawal_provider, manifest["withdrawal_view"])
    raw = _checked_file(directory, "weights.npz", 2 * 1024 * 1024, manifest["weights_npz_sha256"])
    model = new_student(manifest["seed"])
    expected = model.state_dict()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if (len(archive.infolist()) != len(expected)
                or sum(v.file_size for v in archive.infolist()) > 1024 * 1024):
            raise ValueError("unbounded shared-student NPZ")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        if set(archive.files) != set(expected):
            raise ValueError("shared-student tensor roster mismatch")
        state = {}
        for name, tensor in expected.items():
            value = archive[name]
            if value.dtype != np.float32 or tuple(value.shape) != tuple(tensor.shape) or not np.isfinite(value).all():
                raise ValueError("shared-student tensor shape or values differ")
            state[name] = torch.from_numpy(value.copy())
    model.load_state_dict(state, strict=True)
    if _state_digest(model) != manifest["trained_tensor_sha256"]:
        raise ValueError("shared-student trained tensor hash differs")
    return FrozenSharedStudentV1(model, manifest, expected_manifest_sha256)


def train_shared_student(cohorts, records, directory, withdrawal_provider, *, seed,
                         teacher_bank_sha256, input_manifest_sha256, scope_id,
                         steps=20, learning_rate=0.05):
    if (type(steps) is not int or not 1 <= steps <= 100
            or type(learning_rate) not in (float, int) or not 0 < learning_rate <= 0.1):
        raise ValueError("bounded slow shared update required")
    closure = validate_replay(cohorts, records, teacher_bank_sha256=teacher_bank_sha256,
                              input_manifest_sha256=input_manifest_sha256)
    identity = SharedStudentScopeV1(scope_id)
    frontier = check_sources(closure, identity, withdrawal_provider)
    pairs, _ = _prepare(cohorts, teacher_candidate=TEACHER, teacher_revision=TEACHER_REVISION,
        checkpoint_inventory_sha256=TEACHER_INVENTORY, student_width=64, target_width=1536)
    # Keep scoring and training inputs independent of caller-owned mutable slots.
    cohorts = {name: replace(cohorts[name], slots=pairs[name][0]) for name in SPLITS}
    model = new_student(seed)
    initial_hash = _state_digest(model)
    initial_parts = {name: _state_digest(module) for name, module in model.items()}
    optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate)
    counts = {"student_module_forwards": 0, "student_example_calls": 0,
              "readout_module_forwards": 0, "readout_example_calls": 0}
    phase, phase_counts = ["initial"], {}
    def observe(name):
        def hook(module, inputs):
            counts[name + "_module_forwards"] += 1
            counts[name + "_example_calls"] += len(inputs[0])
            stage = ("optimizer_train" if torch.is_grad_enabled() else "objective_before_after") if phase[0] == "distillation" else phase[0]
            observed = phase_counts.setdefault(stage, {k: 0 for k in counts})
            observed[name + "_module_forwards"] += 1
            observed[name + "_example_calls"] += len(inputs[0])
        return hook
    handles = [model[name].register_forward_pre_hook(observe(name)) for name in ("student", "readout")]
    predictions = {}
    def collect(stage):
        phase[0] = "prediction_" + stage
        model.eval()
        with torch.no_grad():
            for name in SPLITS:
                slots = cohorts[name].slots.detach().clone()
                prediction = model["readout"](model["student"](slots).mean(1))
                predictions[stage + ":" + name] = prediction.detach().numpy().copy()
    try:
        collect("before")
        phase[0] = "distillation"
        training = run_offline_distillation(student=model["student"], readout=model["readout"], optimizer=optimizer,
            cohorts=cohorts, student_candidate=MODEL_ID, teacher_candidate=TEACHER,
            teacher_revision=TEACHER_REVISION, checkpoint_inventory_sha256=TEACHER_INVENTORY,
            student_width=64, target_width=1536, steps=steps)
        collect("after")
    finally:
        for handle in handles:
            handle.remove()
    trained_parts = {name: _state_digest(module) for name, module in model.items()}
    if optimizer.state or any(initial_parts[name] == trained_parts[name] for name in initial_parts):
        raise ValueError("expected real shared-backbone and readout updates with zero optimizer state")
    gradient_bytes = sum(p.grad.numel() * p.grad.element_size() for p in model.parameters() if p.grad is not None)
    optimizer.zero_grad(set_to_none=True)
    if check_sources(closure, identity, withdrawal_provider, asdict(frontier)) != frontier:
        raise ValueError("source frontier changed during shared training; discard artifact")
    target = Path(directory)
    target.mkdir(parents=False, exist_ok=False)
    with (target / "weights.npz").open("xb") as stream:
        np.savez(stream, **{name: tensor.detach().numpy() for name, tensor in model.state_dict().items()})
    manifest = {"schema": "hepta.shared-tiny-student-artifact.v1", "model_id": MODEL_ID,
        "seed": seed, "scope_id": scope_id, "purpose": "research", "shared_model_generation": 1,
        "teacher_bank_sha256": teacher_bank_sha256, "input_manifest_sha256": input_manifest_sha256,
        "initial_tensor_sha256": initial_hash, "trained_tensor_sha256": _state_digest(model),
        "initial_component_sha256": initial_parts, "trained_component_sha256": trained_parts,
        "weights_npz_sha256": hashlib.sha256((target / "weights.npz").read_bytes()).hexdigest(),
        "source_closure": closure, "withdrawal_view": asdict(frontier), "records": records,
        "source_closure_policy": "conservative union of training and evaluated evidence; no teacher pretraining erasure claim",
        "training": training, "observed_forwards": counts, "observed_forwards_by_phase": phase_counts,
        "gradient_bytes_before_clear": gradient_bytes,
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "resident_tensor_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
        "parameter_example_updates": sum(p.numel() for p in model.parameters()) * len(cohorts["train"].sample_digests) * steps,
        "optimizer_state_bytes": 0, "head_training_steps": 0, "pretrained_encoder_training_steps": 0,
        "new_shared_student_optimizer_steps": steps, "learning_rate": learning_rate,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False,
        "old_cell_or_feature_generation_reuse_allowed": False}
    raw = _json_bytes(manifest)
    with (target / "manifest.json").open("xb") as stream:
        stream.write(raw)
    return load_shared_student(target, expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                               withdrawal_provider=withdrawal_provider), predictions
