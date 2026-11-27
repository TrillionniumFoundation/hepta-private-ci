"""Instrumentation of the exact public Hybrid/SmallHCSN, with no replacement rollout."""
from dataclasses import asdict
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np
import torch

from static_support import sha

ALLOWED = ("body.input_drive.weight", "body.input_drive.bias")
EXPECTED_PROFILE = dict(input_size=9, neurons=8, bins=6, stages=3, dt=.48,
    extent=2., sigma=.55, base_drift=-.2, drift_scale=.15, discount=.3,
    refractory=.2, reset_absolute=1.2, gain=.8, maintenance=.25, cost=.15,
    cost_span=.02, boundary_span=.1, write_fraction=.5, slow_every=2,
    boundary_mode="qvi", message_mode="boundary", feature_bank="value_risk",
    feature_normalization="none", precision="mixed", backend="dense")


def tensor_bytes(tensor):
    return tensor.detach().cpu().contiguous().numpy().tobytes()


def load_data(prepared, manifest):
    contract_raw = (prepared / "data_contract.json").read_bytes()
    if sha(contract_raw) != manifest["data_contract"]["sha256"]:
        raise ValueError("source-integrity contract identity")
    result = {}
    for split, count in (("train", 80), ("dev", 32), ("retain", 32)):
        path = prepared / "source/data" / (split + ".npz")
        expected = next(row for row in manifest["payload_members"] if row["path"] == "data/" + split + ".npz")
        if sha(path.read_bytes()) != expected["sha256"]:
            raise ValueError("raw public cache identity")
        with np.load(path, allow_pickle=False) as archive:
            shared = archive["x"][:, :, [0, 1, 2, 3, 4, 5, 7]]
            baseline = archive["read_scores"].astype("float32")
            audio = archive["scores"]
            visual = 2 * archive["read_scores"] - audio
            inputs = np.concatenate((np.broadcast_to(shared[:, :, None, :], (*baseline.shape, 7)),
                                     audio[..., None], visual[..., None]), axis=-1).astype("float32")
            row = dict(x=inputs, baseline=baseline, y=archive["target"].astype("int64"),
                       groups=archive["group"].copy(), query_id=archive["query_id"].copy(),
                       gallery_id=archive["gallery_id"].copy())
        if inputs.shape != (count, 6, 2, 9) or row["y"].shape != (count,):
            raise ValueError("fixed six-tick paired-query data shape")
        for group, query, gallery in zip(row["groups"], row["query_id"], row["gallery_id"]):
            actor = group.rsplit("-", 1)[-1]
            if any(str(item).rsplit("-", 1)[-1].split(".")[0] != actor for item in [query, *gallery]):
                raise ValueError("query/gallery actor declaration differs")
        if split == "retain":
            excluded = [i for i, name in enumerate(row["query_id"]) if str(name).split("-")[2] == "03" and str(name).endswith("-07.mp4")]
            if excluded != [4, 5, 6, 7]:
                raise ValueError("public source-integrity erratum differs")
            keep = [i for i in range(count) if i not in excluded]
            row = {key: value[keep] for key, value in row.items()}
        result[split] = row
    train = result["train"]
    mu, sd = train["x"].mean(axis=(0, 1, 2)), np.maximum(train["x"].std(axis=(0, 1, 2)), .001)
    scale = np.float32(max(train["baseline"][:, -1].std(), .001))
    normalization = np.concatenate((mu, sd, np.array([scale], dtype="float32"))).astype("<f4").tobytes()
    if sha(normalization) != manifest["normalizer_sha256"] or normalization.hex() != manifest["normalizer_f32_le_hex"]:
        raise ValueError("public train-only normalizer changed")
    for row in result.values():
        row["x"] = ((row["x"] - mu) / sd).astype("float32")
        row["baseline"] = (row["baseline"][:, -1] / scale).astype("float32")
    return result


def take(data, ids):
    return {key: value[ids] for key, value in data.items()}


def combine(left, right):
    return {key: np.concatenate((left[key], right[key]), axis=0) for key in left}


class Adapter:
    def __init__(self, prepared, manifest, ledger):
        self.ledger, self.current = ledger, None
        source = prepared / "source"
        for item in manifest["payload_members"]:
            if item["path"].endswith(".py") and sha((source / item["path"]).read_bytes()) != item["sha256"]:
                raise ValueError("original Python source identity")
        sys.path.insert(0, str(source))
        spec = importlib.util.spec_from_file_location("pinned_public_hcsn_benchmark", source / "benchmark.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        allowed_sources = {(source / row["path"]).resolve(): row["sha256"]
                           for row in manifest["payload_members"] if row["path"].endswith(".py")}
        self.loaded_sources = {str((source / "benchmark.py").resolve()): sha((source / "benchmark.py").read_bytes())}
        for name, loaded in tuple(sys.modules.items()):
            if name == "qualification" or name.startswith("qualification."):
                filename = getattr(loaded, "__file__", None)
                if filename is None:
                    if not all(Path(path).resolve().is_relative_to(source) for path in loaded.__path__):
                        raise ValueError("unexpected qualification namespace search path")
                    continue
                actual = Path(filename).resolve()
                if actual not in allowed_sources or sha(actual.read_bytes()) != allowed_sources[actual]:
                    raise ValueError("actual imported original module differs: " + name)
                self.loaded_sources[str(actual)] = allowed_sources[actual]
        torch.manual_seed(47)
        self.model = module.Hybrid("centered").cpu().eval()
        path = prepared / "parent.pt"
        if sha(path.read_bytes()) != manifest["checkpoint"]["sha256"]:
            raise ValueError("selected public parent bytes")
        self.model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
        current = self.model.state_dict()
        if set(current) != set(manifest["tensor_profile"]):
            raise ValueError("registered tensor names differ")
        self.original = {}
        for name, tensor in current.items():
            expected = manifest["tensor_profile"][name]
            raw = tensor_bytes(tensor)
            if list(tensor.shape) != expected["shape"] or str(tensor.numpy().dtype) != expected["dtype"] or sha(raw) != expected["sha256"]:
                raise ValueError("original tensor/buffer identity: " + name)
            self.original[name] = raw
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.model.body.input_drive.weight.requires_grad_(True)
        self.model.body.input_drive.bias.requires_grad_(True)
        self.parent = self.theta()
        self.profile = asdict(self.model.body.config)
        if self.profile != EXPECTED_PROFILE or self.model.arm != "centered" or self.model.body.feature_dim != 20:
            raise ValueError("unsupported physical producer profile")
        self.model.body.register_forward_pre_hook(self.before_body, with_kwargs=True)
        self.model.body.input_drive.register_forward_hook(self.drive_output)
        self.model.body.register_forward_hook(self.after_body, with_kwargs=True)
        original_flow = self.model.body._flow

        def traced_flow(*args, **kwargs):
            output = original_flow(*args, **kwargs)
            if self.current is not None:
                self.current["receiver_first_hit_f64"].append(output[3][:, 4:].detach().numpy().copy())
                self.current["receiver_value_f64"].append(output[2][:, 4:].detach().numpy().copy())
                risk = output[3].detach()
                self.flow_diagnostics = dict(risk_min=float(risk.min()), risk_max=float(risk.max()),
                    risk_count_excess=float((risk - output[1].detach()[..., 0]).max()))
            return output

        self.model.body._flow = traced_flow
        self.verify_scope()
        self.ledger.event("original_model_initialized", complete_rollout_calls=0,
                          initialization_qvi_is_costed=True, tensor_names=sorted(current),
                          loaded_sources=self.loaded_sources, profile=self.profile)

    def theta(self):
        return np.concatenate((self.model.body.input_drive.weight.detach().numpy().reshape(-1),
                               self.model.body.input_drive.bias.detach().numpy())).astype("<f4")

    def set_theta(self, values):
        values = np.asarray(values, dtype="<f4")
        if values.shape != (40,) or not np.isfinite(values).all():
            raise ValueError("invalid actual F32 sender parameters")
        with torch.no_grad():
            self.model.body.input_drive.weight.copy_(torch.from_numpy(values[:36].copy()).reshape(4, 9))
            self.model.body.input_drive.bias.copy_(torch.from_numpy(values[36:].copy()))
        self.verify_scope()

    def load_candidate(self, path, expected_sha, theta):
        """Evaluate values reloaded from the sealed full checkpoint, not a second delta copy."""
        raw = Path(path).read_bytes()
        if sha(raw) != expected_sha:
            raise ValueError("sealed checkpoint file identity changed")
        state = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
        registered = self.model.state_dict()
        if set(state) != set(self.original):
            raise ValueError("saved candidate tensor coverage changed")
        expected = dict(self.original)
        expected[ALLOWED[0]] = np.asarray(theta[:36], dtype="<f4").tobytes()
        expected[ALLOWED[1]] = np.asarray(theta[36:], dtype="<f4").tobytes()
        for name, tensor in state.items():
            if (tensor.shape != registered[name].shape or tensor.dtype != registered[name].dtype or
                    tensor_bytes(tensor) != expected[name]):
                raise ValueError("saved candidate tensor/buffer/scope mismatch: " + name)
        for left, right in (("head.weight", "body.readout.weight"), ("head.bias", "body.readout.bias")):
            if state[left].data_ptr() != state[right].data_ptr():
                raise ValueError("saved candidate storage alias lost")
        self.model.load_state_dict(state, strict=True)
        self.verify_scope()
        if self.theta().tobytes() != np.asarray(theta, dtype="<f4").tobytes():
            raise ValueError("reloaded actual sender values differ")
        self.ledger.event("sealed_full_checkpoint_loaded", sha256=expected_sha, complete_rollout_calls=0)

    def verify_scope(self):
        current = self.model.state_dict()
        if set(current) != set(self.original):
            raise ValueError("registered tensor or buffer coverage changed")
        if self.model.head is not self.model.body.readout:
            raise ValueError("readout object alias lost")
        for left, right in (("head.weight", "body.readout.weight"), ("head.bias", "body.readout.bias")):
            if current[left].data_ptr() != current[right].data_ptr():
                raise ValueError("original registered readout alias lost")
        for name, tensor in current.items():
            if name not in ALLOWED and tensor_bytes(tensor) != self.original[name]:
                raise ValueError("out-of-scope parameter or buffer changed: " + name)

    def before_body(self, module, args, kwargs):
        self.ledger.charge("body_ticks")
        self.ledger.event("body_tick_started", label=self.label, tick=len(self.current["receiver_features"]))
        self.old_state = kwargs.get("state")
        self.inputs = args[0][0]

    def drive_output(self, module, args, output):
        self.drive = output.detach()

    def after_body(self, module, args, kwargs, output):
        _, features, state = output
        self.current["receiver_features"].append(features[0].detach().numpy().copy())
        if (state.step - 1) % 2 == 0:
            for name in ("drift", "cost", "boundary"):
                self.current["sender_" + name].append(getattr(state, name)[:, :4].detach().numpy().copy())
            if self.compile_trace:
                self.ledger.charge("trace_linear_replays")
                with torch.no_grad():
                    if self.old_state is None:
                        rec = torch.zeros_like(self.drive)
                    else:
                        message = self.old_state.message.to(self.inputs)
                        mask = self.inputs.new_tensor((1., 0., 0.))
                        rec = torch.nn.functional.linear((message * mask[None, :, None]).flatten(1),
                                                          module.recurrent.weight * module.synaptic_mask)[:, :4]
                    z = self.drive + rec
                    drift = (module.config.base_drift + module.config.drift_scale * z.tanh()).to(state.drift)
                    cost = (module.config.cost + module.config.cost_span * (module.raw_cost[:4] + .15 * z).tanh()).to(state.cost)
                    if not torch.equal(drift, state.drift[:, :4]) or not torch.equal(cost, state.cost[:, :4]):
                        raise ValueError("trace preactivation does not reproduce actual F32 drift/cost bits")
                    keys = torch.cat((self.inputs, torch.ones_like(self.inputs[:, :1])), dim=1)
                    self.current["sender_keys"].append(keys.detach().numpy().copy())
                    self.current["sender_z"].append(z.detach().numpy().copy())
        diag = dict(module.last_diagnostics, **self.flow_diagnostics)
        violations = [diag["mass_error"], -diag["probability_min"], diag["mark_excess"],
                      -diag["risk_min"], diag["risk_max"] - 1., diag["risk_count_excess"]]
        if not diag["all_finite"] or max(violations) > 2e-9:
            raise ValueError("original complete-population physical gate failed")
        self.current["diagnostics"].append(dict(diag))
        self.ledger.event("body_tick_completed", label=self.label, diagnostics=diag)

    def run(self, data, label, gradient=False, compile_trace=False):
        self.verify_scope()
        self.label, self.compile_trace = label, compile_trace
        fields = ("receiver_features", "receiver_first_hit_f64", "receiver_value_f64", "sender_drift",
                  "sender_cost", "sender_boundary", "sender_keys", "sender_z", "diagnostics")
        self.current = {name: [] for name in fields}
        with self.ledger.forward(label, len(data["y"])):
            with torch.set_grad_enabled(gradient):
                scores = self.model(torch.from_numpy(data["x"]), torch.from_numpy(data["baseline"]))
            trace = {name: np.stack(values) for name, values in self.current.items() if values and name != "diagnostics"}
            diagnostics = self.current["diagnostics"]
            self.verify_scope()
        self.current = None
        if scores.dtype != torch.float32 or tuple(scores.shape) != (len(data["y"]), 2) or not torch.isfinite(scores).all():
            raise ValueError("actual binary-choice output type/domain")
        return scores, trace, diagnostics
