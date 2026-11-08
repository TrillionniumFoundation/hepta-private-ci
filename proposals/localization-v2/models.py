"""Real baseline adapters for the bounded localization interface study.

Each forward starts a fresh episode. Widths are interface fixtures, not a
capacity-matched or sufficiently trained benchmark. No missing-model fallback.
"""

import hashlib
from importlib import metadata as package_metadata
import importlib.util
import inspect
import math
from pathlib import Path
import subprocess
import sys

import torch
from torch import nn

S4_COMMIT = "e757cef57d89e448c413de7325ed5601aceaac13"
S4_FILES = ("models/s4/s4d.py", "src/models/nn/__init__.py", "src/models/nn/linear.py",
            "src/models/nn/activation.py", "src/models/nn/normalization.py", "src/models/nn/dropout.py")
ARMS = ("gru", "cfc", "snn_plif", "ssm_s4d", "attention")


def _require_version(package, expected):
    try:
        observed = package_metadata.version(package)
    except package_metadata.PackageNotFoundError as error:
        raise ImportError(f"missing official dependency: {package}=={expected}") from error
    if observed != expected:
        raise ImportError(f"requires {package}=={expected}; installed {observed}")


def _inputs(x, dt):
    if (x.ndim != 3 or x.shape[-1] != 25 or min(x.shape[:2]) < 1
            or dt.shape != x.shape[:2] or x.dtype != torch.float64 or dt.dtype != x.dtype
            or x.device.type != "cpu" or dt.device.type != "cpu"):
        raise ValueError("requires nonempty CPU FP64 x[B,T,25] and dt[B,T]")
    if not bool(torch.isfinite(x).all()) or not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
        raise ValueError("nonfinite input or negative elapsed time")


class GRUModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.core = nn.GRU(25, 4, batch_first=True)
        self.head = nn.Linear(4, 11)

    def forward(self, x, dt):
        _inputs(x, dt)
        return self.head(self.core(x, x.new_zeros(1, x.shape[0], 4))[0])


class CfCModel(nn.Module):
    def __init__(self):
        super().__init__()
        _require_version("ncps", "1.0.1")
        from ncps.torch import CfC
        self.core = CfC(25, 4, proj_size=11, batch_first=True, return_sequences=True,
                        mixed_memory=False, mode="default", backbone_units=16,
                        backbone_layers=1, backbone_dropout=0.)

    def forward(self, x, dt):
        _inputs(x, dt)
        # Upstream squeezes the timespan batch axis. Per-sample dispatch keeps
        # real dt and FP64 hx correct even when the caller batches examples.
        return torch.cat([self.core(x[i:i + 1], hx=x.new_zeros(1, 4),
                                    timespans=dt[i:i + 1])[0]
                          for i in range(x.shape[0])], dim=0)


class RecurrentPLIF(nn.Module):
    def __init__(self):
        super().__init__()
        _require_version("spikingjelly", "0.0.0.0.14")
        from spikingjelly.activation_based import functional, neuron, surrogate
        self.input = nn.Linear(25, 4)
        self.recurrent = nn.Linear(4, 4, bias=False)
        self.node = neuron.ParametricLIFNode(init_tau=2., decay_input=False,
                    v_threshold=1., v_reset=None, surrogate_function=surrogate.ATan(alpha=2.),
                    detach_reset=True, step_mode="s", backend="torch")
        self.head = nn.Linear(4, 11)
        self._reset = functional.reset_net
        self._extra_sources = [inspect.getsourcefile(functional.reset_net)]
        self.last_spike_fraction = None
        self.last_diagnostics = {}

    def forward(self, x, dt):
        _inputs(x, dt)
        self._reset(self)
        spikes, outputs, current = [], [], x.new_zeros(x.shape[0], 4)
        for observation in x.unbind(1):
            current = self.node(self.input(observation) + self.recurrent(current))
            spikes.append(current)
            outputs.append(self.head(current))
        self.last_spike_fraction = float(torch.stack(spikes).detach().mean())
        self.last_diagnostics = {"spike_fraction": self.last_spike_fraction,
                                 "learned_tau": float((1. / self.node.w.detach().sigmoid()).cpu())}
        return torch.stack(outputs, dim=1)


def _official_s4(repo):
    if repo is None:
        raise ImportError("ssm_s4d requires --s4-repo with the pinned official checkout")
    root = Path(repo).resolve()
    try:
        def git(*args):
            return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        if git("rev-parse", "HEAD").decode().strip() != S4_COMMIT:
            raise ImportError(f"S4 checkout must be at {S4_COMMIT}")
        for relative in S4_FILES:
            if (root / relative).read_bytes() != git("show", f"{S4_COMMIT}:{relative}"):
                raise ImportError(f"modified official S4 source: {relative}")
        if any((root / p).exists() for p in ("src/__init__.py", "src/models/__init__.py")):
            raise ImportError("unexpected Python initializer in upstream S4 namespace packages")
    except (OSError, subprocess.CalledProcessError) as error:
        raise ImportError("missing/incomplete pinned official S4 checkout") from error
    for name in ("src", "src.models", "src.models.nn"):
        loaded = sys.modules.get(name)
        paths = list(getattr(loaded, "__path__", [])) if loaded else []
        if any(not Path(path).resolve().is_relative_to(root) for path in paths):
            raise ImportError(f"existing {name} belongs to another checkout; use a fresh worker")
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("_hcsn_v2_official_s4d", root / S4_FILES[0])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.S4D, [str(root / relative) for relative in S4_FILES]


class OfficialS4D(nn.Module):
    def __init__(self, repo):
        super().__init__()
        s4d, self._extra_sources = _official_s4(repo)
        self.input = nn.Linear(25, 4)
        self.core = s4d(d_model=4, d_state=16, dropout=0., transposed=False)
        self.head = nn.Linear(4, 11)

    def forward(self, x, dt):
        _inputs(x, dt)
        return self.head(self.core(self.input(x))[0])


class CausalAttention(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(25, 8)
        layer = nn.TransformerEncoderLayer(8, 2, dim_feedforward=32, dropout=0.,
                                            activation="gelu", batch_first=True)
        self.core = nn.TransformerEncoder(layer, 1, enable_nested_tensor=False)
        self.head = nn.Linear(8, 11)

    def forward(self, x, dt):
        _inputs(x, dt)
        position = torch.arange(x.shape[1], dtype=x.dtype, device=x.device)[:, None]
        frequency = torch.exp(torch.arange(0, 8, 2, dtype=x.dtype, device=x.device) * (-math.log(10000.) / 8))
        encoding = x.new_zeros(x.shape[1], 8)
        encoding[:, 0::2], encoding[:, 1::2] = torch.sin(position * frequency), torch.cos(position * frequency)
        mask = torch.ones(x.shape[1], x.shape[1], dtype=torch.bool, device=x.device).triu(1)
        return self.head(self.core(self.input(x) + encoding, mask=mask))


def build_model(name, s4_repo=None):
    constructors = {"gru": GRUModel, "cfc": CfCModel, "snn_plif": RecurrentPLIF,
                    "attention": CausalAttention}
    if name == "ssm_s4d":
        model = OfficialS4D(s4_repo)
    elif name in constructors:
        model = constructors[name]()
    else:
        raise ValueError(f"unknown baseline {name}; HCSN requires the separate numerical admission")
    model._arm = name
    return model.cpu().double()


def metadata(model):
    files = {str(Path(__file__).resolve()), *getattr(model, "_extra_sources", [])}
    for module in model.modules():
        try:
            source = inspect.getsourcefile(type(module))
        except (TypeError, OSError):
            source = None
        if source:
            files.add(str(Path(source).resolve()))
    packages = {"torch": torch.__version__}
    for package in {"cfc": ("ncps", "numpy"), "snn_plif": ("spikingjelly",),
                    "ssm_s4d": ("einops",)}.get(model._arm, ()):
        packages[package] = package_metadata.version(package)
    time_semantics = {"cfc": "official CfC receives real timespans",
                     "snn_plif": "event-indexed PLIF; log1p(real dt) input; no variable-dt decay claim",
                     "ssm_s4d": "official causal S4D-Lin FFT on event index; real dt feature; not Mamba"}
    result = {"arm": model._arm, "packages": packages, "torch_git_version": torch.version.git_version,
              "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
              "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
              "dtype": "float64", "device": "cpu", "episode_state": "fresh for every forward",
              "time_semantics": time_semantics.get(model._arm, "causal event sequence with shared real-dt feature"),
              "source_files_sha256": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in sorted(files)},
              "source_hash_scope": "Python module definitions/helpers; native libraries identified by Torch build version",
              "claim_boundary": "Tiny interface fixture; unequal capacities; four updates do not establish adequate training."}
    if model._arm == "ssm_s4d":
        result.update(verified_checkout_commit=S4_COMMIT, persistent_state_interface="not exposed by upstream FFT forward")
    if model._arm == "snn_plif":
        result.update(last_forward_spike_fraction=model.last_spike_fraction,
                      learned_tau=float((1. / model.node.w.detach().sigmoid()).cpu()))
    return result
