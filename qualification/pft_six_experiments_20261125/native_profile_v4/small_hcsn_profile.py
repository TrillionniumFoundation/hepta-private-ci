"""Complete frozen SmallHCSN research profile; no production owner capability.

Framework and physical-model imports occur only in load_profile. The model,
ScaledReadout, population evolution, QVI, reset and remap all come from the
original verified capsule/scientific sources, not an alternate implementation.
"""
from dataclasses import asdict
import hashlib
import io
import math
from pathlib import Path
import zipfile

from profile_io import canonical, digest, fields, parse, read_named, read_pin, require, sha, write_new
from source_binding import FrozenSources, RUNTIME

SCHEMA = "hepta.smallhcsn.numeric-profile.v1"
FAMILY = "hepta.smallhcsn.population"
EDIT_SCHEMA = "hepta.smallhcsn.research-candidate.v1"
STATE_SCHEMA = "hepta.smallhcsn.population-state.v1"
FORMATS = ("actual_hcsn_v2_selected", "actual_p2p_v2_full", "research_candidate_v1")
STATE_FIELDS = ("density", "boundary", "drift", "cost", "message")
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
MAX_BATCH = 16
MAX_STEPS = 64


def tensor_state_sha256(state):
    """Exact existing actual_hcsn_v2.runner.tensor_digest byte convention."""
    result = hashlib.sha256()
    for name, value in sorted(state.items()):
        array = value.detach().cpu().numpy()
        result.update(name.encode())
        result.update(str((array.dtype.str, array.shape)).encode())
        result.update(array.tobytes())
    return result.hexdigest()


def _torch_payload(torch, raw):
    # All admitted existing torch.save artifacts use ZIP serialization.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= 4096 and len({x.filename for x in entries}) == len(entries),
                "checkpoint archive entry bound")
        require(sum(x.file_size for x in entries) <= MAX_CHECKPOINT_BYTES
                and all(x.file_size >= 0 and not x.flag_bits & 1 for x in entries),
                "checkpoint expanded byte bound")
    return torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)


def _state_dict_check(torch, model, state):
    expected = model.state_dict()
    require(isinstance(state, dict) and set(state) == set(expected), "complete model tensor roster required")
    require(sum(value.numel() for value in expected.values()) <= 1_000_000, "model tensor bound")
    for name, reference in expected.items():
        value = state[name]
        require(isinstance(value, torch.Tensor) and value.layout == torch.strided
                and value.device.type == "cpu" and value.dtype == reference.dtype
                and value.shape == reference.shape and bool(torch.isfinite(value).all()),
                "model tensor shape, dtype, device or finite value differs: " + name)


def _construct(common, optimized, constructor, config, state):
    require(constructor in ("cached_scaled", "plain_linear"), "unsupported SmallHCSN constructor")
    require(isinstance(config, dict) and set(config) == set(common.ModelConfig.__dataclass_fields__),
            "complete physical ModelConfig required")
    canonical(config)  # Refuse nonfinite configuration before constructing physics.
    require(config["input_size"] == 6 and config["precision"] == "float64"
            and config["backend"] == "dense", "profile admits six-input dense float64 physics")
    model_class = optimized.CachedSmallHCSN if constructor == "cached_scaled" else common.SmallHCSN
    model = model_class(common.ModelConfig(**config))
    if constructor == "cached_scaled":
        required = ("readout.mean", "readout.scale", "readout.linear.weight", "readout.linear.bias")
        require(isinstance(state, dict) and all(key in state for key in required), "complete ScaledReadout required")
        torch = common.torch
        for key in required:
            value = state[key]
            require(isinstance(value, torch.Tensor) and value.device.type == "cpu"
                    and value.dtype == torch.float64 and value.layout == torch.strided
                    and bool(torch.isfinite(value).all()), "scaled head tensor contract")
        size = model.feature_dim
        require(state["readout.mean"].shape == (size,) and state["readout.scale"].shape == (size,)
                and state["readout.linear.weight"].shape == (2, size)
                and state["readout.linear.bias"].shape == (2,)
                and bool((state["readout.scale"] > 0).all()), "scaled head dimensions or scale")
        # Reuse the original class. All its buffers and parameters are loaded
        # again with strict=True below; no original fitted scale is discarded.
        model.readout = common.ScaledReadout({
            "mean": state["readout.mean"].detach().numpy(), "scale": state["readout.scale"].detach().numpy(),
            "weight": state["readout.linear.weight"].detach().numpy().T,
            "bias": state["readout.linear.bias"].detach().numpy(),
        })
    _state_dict_check(common.torch, model, state)
    model.load_state_dict(state, strict=True)
    require(tensor_state_sha256(model.state_dict()) == tensor_state_sha256(state),
            "full physical model reload differs")
    model.eval()
    return model


def _checkpoint_parts(payload, format_name, origin):
    if format_name == "actual_hcsn_v2_selected":
        fields(payload, ("schema", "protocol_sha256", "case", "config", "initial_weights",
                         "selected_weights", "last_weights", "baseline_fits", "selected_step",
                         "updates", "status"), "formal candidate")
        require(payload["schema"] == "actual-hcsn-v2-candidate-v1"
                and payload["protocol_sha256"] == origin["protocol_sha256"], "formal checkpoint identity")
        require(payload["status"] in ("COMPLETED_MAX_UPDATES", "CENSORED_BUDGET")
                and type(payload["selected_step"]) is int and type(payload["updates"]) is int
                and 0 <= payload["selected_step"] <= payload["updates"], "unusable formal candidate")
        case, config = payload["case"], payload["config"]
        require(case["width"] == config["neurons"] and case["bank"] == config["feature_bank"]
                and case["message"] == config["message_mode"]
                and case["connection"] in ("learned", "fixed"), "formal model profile differs")
        return "cached_scaled", config, payload["selected_weights"]
    if format_name == "actual_p2p_v2_full":
        fields(payload, ("config", "state_dict", "candidate_sha256"), "P2P model checkpoint")
        require(payload["candidate_sha256"] == origin["coordinate_candidate_sha256"],
                "P2P coordinate candidate differs")
        return "plain_linear", payload["config"], payload["state_dict"]
    fields(payload, ("schema", "config", "constructor", "state_dict", "state_sha256", "requires_grad",
                     "source_binding_sha256", "parent_profile_sha256", "parent_candidate_sha256",
                     "parent_state_sha256", "edit_receipt_sha256", "coordinates"), "research edit candidate")
    require(payload["schema"] == EDIT_SCHEMA, "research candidate schema")
    for key in ("state_sha256", "source_binding_sha256", "parent_profile_sha256", "parent_candidate_sha256",
                "parent_state_sha256", "edit_receipt_sha256"):
        digest(payload[key])
    require(tensor_state_sha256(payload["state_dict"]) == payload["state_sha256"],
            "research candidate state identity differs")
    return payload["constructor"], payload["config"], payload["state_dict"]


class LoadedProfile:
    def __init__(self, manifest, profile_sha256, root, sources, common, physical, model, constructor):
        self.manifest = manifest
        self.profile_sha256 = profile_sha256
        self.candidate_sha256 = manifest["checkpoint"]["sha256"]
        self.source_binding_sha256 = sources.identity
        self.model_state_sha256 = tensor_state_sha256(model.state_dict())
        self.model = model
        self.constructor = constructor
        self.material_root = Path(root)
        self.torch = common.torch
        self.PopulationState = physical.PopulationState
        self.config = asdict(model.config)
        self.parameter_trainability = {name: parameter.requires_grad for name, parameter in model.named_parameters()}
        self._model_class = type(model)
        self._constructor = constructor

    def current_state_sha256(self):
        return tensor_state_sha256(self.model.state_dict())

    def require_frozen(self):
        require(self.current_state_sha256() == self.model_state_sha256
                and asdict(self.model.config) == self.config
                and type(self.model) is self._model_class and self.constructor == self._constructor
                and {name: value.requires_grad for name, value in self.model.named_parameters()}
                == self.parameter_trainability, "loaded candidate, constructor or trainability changed")

    def initial_state(self, batch_size, initial_margin=None):
        self.require_frozen()
        require(type(batch_size) is int and 1 <= batch_size <= MAX_BATCH, "profile batch bound")
        state = self.model.initial_state(batch_size, initial_margin)
        self.check_population(state)
        return state

    def check_population(self, state):
        torch, c = self.torch, self.model.config
        require(isinstance(state, self.PopulationState) and state.config == c
                and type(state.step) is int and 0 <= state.step < 2**32, "population config or clock differs")
        require(isinstance(state.density, torch.Tensor) and state.density.ndim == 4,
                "population density dimensions")
        batch = state.density.shape[0]
        shapes = {"density": (batch, c.neurons, 2, c.bins + c.stages + 1),
                  "boundary": (batch, c.neurons), "drift": (batch, c.neurons),
                  "cost": (batch, c.neurons), "message": (batch, 3, c.neurons)}
        require(1 <= batch <= MAX_BATCH, "population batch bound")
        for name, shape in shapes.items():
            value = getattr(state, name)
            require(isinstance(value, torch.Tensor) and value.layout == torch.strided
                    and value.shape == shape and value.dtype == torch.float64
                    and value.device.type == "cpu" and bool(torch.isfinite(value).all()),
                    "complete population tensor contract: " + name)
        probability, mark = state.density[:, :, 0], state.density[:, :, 1]
        tolerance = 2e-9
        require(bool((probability >= -tolerance).all())
                and bool((mark.abs() <= probability + tolerance).all())
                and bool(((probability.sum(-1) - 1).abs() <= tolerance).all())
                and bool(((state.drift - c.base_drift).abs() <= c.drift_scale + 1e-6).all())
                and bool(((state.cost - c.cost).abs() <= c.cost_span + 1e-6).all()),
                "population violates physical domain; no normalization applied")

    def forward(self, x, state):
        self.require_frozen()
        self.check_population(state)
        require(isinstance(x, self.torch.Tensor) and x.layout == self.torch.strided
                and x.dtype == self.torch.float64 and x.device.type == "cpu"
                and bool(self.torch.isfinite(x).all())
                and x.ndim == 3 and 1 <= x.shape[0] <= MAX_STEPS
                and x.shape[1] == state.density.shape[0] and x.shape[2] == 6
                and state.step + x.shape[0] < 2**32, "numeric chunk shape or clock bound")
        # Deliberately no no_grad here: the same actual model also supports the
        # separately registered first-order sensitivity research caller.
        logits, features, final_state = self.model(x, state=state, return_features=True)
        self.check_population(final_state)
        self.require_frozen()
        require(bool(self.torch.isfinite(logits).all()) and bool(self.torch.isfinite(features).all()),
                "nonfinite actual prediction")
        return logits, features, final_state

    def _population_identity(self, state):
        return sha(canonical({"config": asdict(state.config), "step": state.step,
                              "tensors": tensor_state_sha256({k: getattr(state, k) for k in STATE_FIELDS})}))

    def save_state(self, state, output):
        self.require_frozen()
        self.check_population(state)
        payload = {"schema": STATE_SCHEMA, "profile_sha256": self.profile_sha256,
                   "candidate_sha256": self.candidate_sha256, "model_state_sha256": self.model_state_sha256,
                   "source_binding_sha256": self.source_binding_sha256, "runtime": dict(RUNTIME),
                   "config": asdict(state.config), "step": state.step,
                   "tensors": {k: getattr(state, k).detach().cpu().contiguous().clone() for k in STATE_FIELDS},
                   "state_sha256": self._population_identity(state)}
        buffer = io.BytesIO()
        self.torch.save(payload, buffer)
        return write_new(output, buffer.getvalue(), MAX_CHECKPOINT_BYTES)

    def load_state(self, pin, root=None):
        self.require_frozen()
        raw = read_pin(self.material_root if root is None else root, pin, MAX_CHECKPOINT_BYTES)
        payload = _torch_payload(self.torch, raw)
        fields(payload, ("schema", "profile_sha256", "candidate_sha256", "model_state_sha256",
                         "source_binding_sha256", "runtime", "config", "step", "tensors", "state_sha256"),
               "population checkpoint")
        require(payload["schema"] == STATE_SCHEMA and payload["profile_sha256"] == self.profile_sha256
                and payload["candidate_sha256"] == self.candidate_sha256
                and payload["model_state_sha256"] == self.model_state_sha256
                and payload["source_binding_sha256"] == self.source_binding_sha256
                and payload["runtime"] == RUNTIME and payload["config"] == self.config,
                "population belongs to a different candidate, source, runtime or config")
        fields(payload["tensors"], STATE_FIELDS, "all five population tensors")
        state = self.PopulationState(*(payload["tensors"][name] for name in STATE_FIELDS),
                                     payload["step"], self.model.config)
        self.check_population(state)
        require(self._population_identity(state) == digest(payload["state_sha256"]),
                "complete population identity differs")
        return state


def load_profile(manifest_path, expected_manifest_sha256, material_root):
    raw = read_named(manifest_path, expected_manifest_sha256, 1024 * 1024)
    manifest = parse(raw)
    fields(manifest, ("schema", "family", "scope", "format", "checkpoint", "capsule",
                      "scientific_sources", "runtime", "origin"), "numeric profile")
    require(manifest["schema"] == SCHEMA and manifest["family"] == FAMILY
            and manifest["scope"] == "research_numeric_inference"
            and manifest["format"] in FORMATS and manifest["runtime"] == RUNTIME,
            "unsupported research profile or numerical runtime")
    fields(manifest["origin"], ("protocol_sha256", "coordinate_candidate_sha256"), "research origin")
    for value in manifest["origin"].values():
        if value is not None:
            digest(value)
    if manifest["format"] == "actual_hcsn_v2_selected":
        digest(manifest["origin"]["protocol_sha256"])
    if manifest["format"] == "actual_p2p_v2_full":
        digest(manifest["origin"]["coordinate_candidate_sha256"])
    checkpoint = read_pin(material_root, manifest["checkpoint"], MAX_CHECKPOINT_BYTES)
    sources = FrozenSources(material_root, manifest)
    common, optimized, physical = sources.load()
    payload = _torch_payload(common.torch, checkpoint)
    constructor, config, state = _checkpoint_parts(payload, manifest["format"], manifest["origin"])
    model = _construct(common, optimized, constructor, config, state)
    if manifest["format"] == "actual_hcsn_v2_selected":
        model.recurrent.weight.requires_grad_(payload["case"]["connection"] == "learned")
    elif manifest["format"] == "research_candidate_v1":
        require(payload["source_binding_sha256"] == sources.identity, "edited candidate physical source differs")
        flags = payload["requires_grad"]
        fields(flags, dict(model.named_parameters()), "parameter trainability")
        for name, parameter in model.named_parameters():
            require(type(flags[name]) is bool, "parameter trainability must be Boolean")
            parameter.requires_grad_(flags[name])
    return LoadedProfile(manifest, sha(raw), material_root, sources, common, physical, model, constructor)


def export_candidate(parent_profile, state_dict, edit_receipt_sha256, output, *, coordinates):
    """Publish a complete research candidate; never update a service pointer."""
    parent_profile.require_frozen()
    digest(edit_receipt_sha256)
    torch, model = parent_profile.torch, parent_profile.model
    _state_dict_check(torch, model, state_dict)
    require(isinstance(coordinates, list) and 1 <= len(coordinates) <= 32, "bounded coordinate roster")
    parameters = dict(model.named_parameters())
    allowed = {}
    clean = []
    for coordinate in coordinates:
        fields(coordinate, ("name", "flat_index", "scale"), "edit coordinate")
        name, index, scale = coordinate["name"], coordinate["flat_index"], coordinate["scale"]
        require(name in parameters and parameters[name].requires_grad
                and type(index) is int and 0 <= index < parameters[name].numel()
                and type(scale) in (int, float) and math.isfinite(scale) and scale > 0,
                "invalid declared parameter coordinate")
        require(index not in allowed.setdefault(name, set()), "duplicate parameter coordinate")
        allowed[name].add(index)
        clean.append(dict(coordinate))
    changed = 0
    original = model.state_dict()
    for name, before in original.items():
        indices = torch.nonzero(state_dict[name].reshape(-1) != before.reshape(-1), as_tuple=False).flatten().tolist()
        require(set(indices) <= allowed.get(name, set()), "unregistered parameter or buffer change")
        changed += len(indices)
    require(changed > 0, "no physical parameter change: retain parent")
    copied = {name: value.detach().cpu().contiguous().clone() for name, value in state_dict.items()}
    payload = {"schema": EDIT_SCHEMA, "config": dict(parent_profile.config),
               "constructor": parent_profile.constructor, "state_dict": copied,
               "state_sha256": tensor_state_sha256(copied),
               "requires_grad": {name: value.requires_grad for name, value in model.named_parameters()},
               "source_binding_sha256": parent_profile.source_binding_sha256,
               "parent_profile_sha256": parent_profile.profile_sha256,
               "parent_candidate_sha256": parent_profile.candidate_sha256,
               "parent_state_sha256": parent_profile.model_state_sha256,
               "edit_receipt_sha256": edit_receipt_sha256, "coordinates": clean}
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    artifact = write_new(output, buffer.getvalue(), MAX_CHECKPOINT_BYTES)
    parent_profile.require_frozen()
    return {"artifact": artifact, "model_state_sha256": payload["state_sha256"],
            "parent_candidate_sha256": parent_profile.candidate_sha256,
            "changed_parameter_elements": changed, "production_adoption": False}
