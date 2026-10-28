"""CPU/SGD record adapter; no scientific model, kernel, assets or study runner."""

from collections import defaultdict
from dataclasses import asdict, fields, is_dataclass
import hashlib
import os
from pathlib import Path
import random
import sys

import numpy as np
import torch

FOUNDATION = {
    "codec.py": "75b2be74e5a9bf7ff474e74f5e25f3f6dc3758c09d07ff78a1417537ddc772fb",
    "branch_state.py": "332080139de3a15a74d6ee5fad907fef661a1866551a0e23689884587d73cf82",
}


def verify_foundation():
    directory = Path(__file__).resolve().parent.parent / "field_bridge_v6_preparation_20261028"
    for name, expected in FOUNDATION.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen foundation source differs: " + name)


verify_foundation()
from ..field_bridge_v6_preparation_20261028 import branch_state, codec

require = codec.require


def runtime_descriptor():
    return {"python": sys.version, "torch": str(torch.__version__), "numpy": np.__version__,
            "torch_build": torch.__config__.show(), "cpu_capability": torch.backends.cpu.get_cpu_capability(),
            "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
            "default_dtype": str(torch.get_default_dtype()), "grad_enabled": torch.is_grad_enabled(),
            "inference_mode": torch.is_inference_mode_enabled(), "autocast_cpu": torch.is_autocast_enabled("cpu"),
            "deterministic": torch.are_deterministic_algorithms_enabled(),
            "matmul_precision": torch.get_float32_matmul_precision(), "mkldnn": torch.backends.mkldnn.enabled,
            "environment": {key: os.environ.get(key) for key in ("ATEN_CPU_CAPABILITY", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}


def array(tensor):
    require(type(tensor) in (torch.Tensor, torch.nn.Parameter) and tensor.device.type == "cpu"
            and tensor.layout == torch.strided and tensor.is_contiguous() and not tensor.is_conj()
            and not tensor.is_neg(), "Only ordinary contiguous CPU tensors are supported")
    require(not getattr(tensor, "_backward_hooks", None) and not getattr(tensor, "_post_accumulate_grad_hooks", None),
            "Tensor hooks are unsupported")
    require(not (set(vars(tensor)) - {"_backward_hooks", "_post_accumulate_grad_hooks"}), "Custom tensor attributes are unsupported")
    try:
        value = tensor.detach().numpy().copy(order="C")
    except (TypeError, RuntimeError) as error:
        raise ValueError("Unsupported tensor dtype") from error
    require(value.dtype.kind in "buif", "Unsupported tensor numeric type")
    return value


def native(value):
    if isinstance(value, torch.Tensor):
        return array(value)
    if isinstance(value, np.ndarray):
        require(type(value) is np.ndarray, "NumPy array subclasses need a different state contract")
        return value.copy(order="C")
    if isinstance(value, np.generic):
        return value.item()
    if is_dataclass(value) and not isinstance(value, type):
        return native(asdict(value))
    if type(value) in (list, tuple):
        return type(value)(native(v) for v in value)
    if isinstance(value, dict):
        return {key: native(item) for key, item in value.items()}
    require(value is None or type(value) in (str, bool, int, float), "Undeclared Python state type")
    return value


def storage_leaves(value):
    if isinstance(value, (torch.Tensor, np.ndarray)):
        yield value
    elif isinstance(value, dict):
        for item in value.values(): yield from storage_leaves(item)
    elif type(value) in (list, tuple):
        for item in value: yield from storage_leaves(item)
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value): yield from storage_leaves(getattr(value, field.name))


def independent(tensors):
    spans = []
    for value in tensors:
        if isinstance(value, torch.Tensor):
            array(value)
            pointer, size = value.untyped_storage().data_ptr(), value.untyped_storage().nbytes()
        else:
            require(isinstance(value, np.ndarray) and value.flags.c_contiguous, "Immutable arrays must be contiguous")
            pointer, size = value.ctypes.data, value.nbytes
        if size:
            require(not any(pointer < end and start < pointer + size for start, end in spans), "Shared tensor storage is outside this schema")
            spans.append((pointer, pointer + size))


def model_parts(model):
    require(isinstance(model, torch.nn.Module), "Expected a Module")
    modules = list(model.named_modules(remove_duplicate=False))
    require(len({id(module) for unused, module in modules}) == len(modules), "Shared module aliases are unsupported")
    structural, modes = {}, {}
    for name, module in modules:
        attrs = vars(module)
        require(not any(value for key, value in attrs.items() if "hooks" in key), "Module hooks are unsupported")
        excluded = {"training", "_parameters", "_buffers", "_modules", "_non_persistent_buffers_set", "_is_full_backward_hook"}
        raw_extra = {key: value for key, value in attrs.items() if key not in excluded and "hooks" not in key}
        require(not list(storage_leaves(raw_extra)), "Array module attributes must be registered parameters or buffers")
        extra = native(raw_extra)
        require(type(module.training) is bool, "Invalid module mode")
        modes[name] = module.training
        structural[name] = {"class": type(module).__module__ + "." + type(module).__qualname__, "attributes": extra,
                            "nonpersistent_buffers": sorted(module._non_persistent_buffers_set),
                            "none_parameters": sorted(key for key, value in module._parameters.items() if value is None),
                            "none_buffers": sorted(key for key, value in module._buffers.items() if value is None)}
    params, buffers = list(model.named_parameters(remove_duplicate=False)), list(model.named_buffers(remove_duplicate=False))
    require(len({id(value) for unused, value in params + buffers}) == len(params + buffers), "Named tensor aliases are unsupported")
    require(all(not b.requires_grad and b.grad_fn is None and b.grad is None for unused, b in buffers), "Buffer autograd state is unsupported")
    independent(value for unused, value in params + buffers)
    return dict(params), dict(buffers), modes, structural


def module_identity(model):
    params, buffers, modes, structural = model_parts(model)
    require(all(not p.requires_grad and p.grad is None for p in params.values())
            and not any(modes.values()), "Immutable reference models must be frozen and in eval mode")
    return codec.digest({"parameters": native(params), "buffers": native(buffers), "modes": modes, "structure": structural})


def generator_kind(generator):
    if type(generator) is torch.Generator:
        require(generator.device.type == "cpu" and generator is not torch.default_generator, "Named generator must be separate CPU RNG")
        return "torch_cpu"
    if type(generator) is random.Random:
        require(generator is not random._inst, "Named RNG aliases global Python RNG")
        return "python"
    if type(generator) is np.random.RandomState:
        require(generator is not np.random.mtrand._rand, "Named RNG aliases global NumPy RNG")
        return "numpy_randomstate"
    require(type(generator) is np.random.Generator, "Unsupported named generator type")
    name = type(generator.bit_generator).__name__
    require(name in ("PCG64", "PCG64DXSM", "MT19937", "Philox", "SFC64")
            and type(generator.bit_generator) is getattr(np.random, name), "Unsupported NumPy bit generator")
    return "numpy_generator:" + name


def generator_owner(generator):
    if type(generator) is np.random.Generator: return generator.bit_generator
    if type(generator) is np.random.RandomState: return generator._bit_generator
    return generator


def generator_state(generator, kind):
    if kind == "torch_cpu": return array(generator.get_state())
    if kind == "python": return generator.getstate()
    if kind == "numpy_randomstate": return native(generator.get_state())
    return native(generator.bit_generator.state)


def set_generator(generator, kind, value):
    if kind == "torch_cpu": generator.set_state(torch.from_numpy(value.copy()))
    elif kind == "python": generator.setstate(value)
    elif kind == "numpy_randomstate": generator.set_state(value)
    else: generator.bit_generator.state = value


def prepare_generator(kind, value):
    if kind == "torch_cpu": target = torch.Generator(device="cpu")
    elif kind == "python": target = random.Random(0)
    elif kind == "numpy_randomstate": target = np.random.RandomState(0)
    else: target = np.random.Generator(getattr(np.random, kind.split(":", 1)[1])(0))
    try:
        set_generator(target, kind, value)
        require(codec.digest(generator_state(target, kind)) == codec.digest(value), "RNG setter normalized or changed recorded bytes")
    except (ValueError, TypeError, IndexError, KeyError, RuntimeError) as error:
        raise ValueError("Invalid recorded RNG state: " + kind) from error


class RestoreError(RuntimeError):
    def __init__(self, cause, rollback_equal, versions_equal):
        super().__init__("Apply failed; public-state rollback=" + str(rollback_equal) + "; autograd versions=" + str(versions_equal))
        self.original_error = repr(cause)
        self.rollback_equal = rollback_equal
        self.versions_equal = versions_equal


class Adapter:
    """Use only between steps, without a pending autograd graph or concurrent writer."""

    def __init__(self, model, optimizer, *, binding, architecture, original_generator, reward_observer,
                 context_inputs, guard_baseline, named_generators):
        verify_foundation()
        self.model, self.optimizer = model, optimizer
        self.binding = native(binding)
        self.architecture, self.context_inputs, self.guard_baseline = architecture, context_inputs, guard_baseline
        self.references = {"original_generator": original_generator, "reward_observer": reward_observer}
        self.generators = dict(named_generators)
        self.fixed = self._description()
        self.environment_sha256 = codec.digest({"binding": self.binding, "immutable": self.fixed})

    def _parts(self):
        require(type(self.optimizer) is torch.optim.SGD, "Only the stock SGD optimizer is supported")
        require(not any(value for key, value in vars(self.optimizer).items() if "hooks" in key), "Optimizer hooks are unsupported")
        for namespace in (vars(torch.nn.modules.module), vars(sys.modules[torch.optim.Optimizer.__module__])):
            require(not any(value for key, value in namespace.items() if key.startswith("_global_") and "hooks" in key), "Global hooks are unsupported")
        params, buffers, modes, structure = model_parts(self.model)
        require(all(parameter.is_leaf for parameter in params.values()), "Parameters must be autograd leaves")
        group_params = [p for group in self.optimizer.param_groups for p in group["params"]]
        require(len(group_params) == len({id(p) for p in group_params}), "Optimizer duplicates a parameter")
        by_id = {id(p): name for name, p in params.items()}
        require(group_params and all(id(p) in by_id for p in group_params), "Optimizer contains a foreign parameter")
        mutable = {by_id[id(p)]: p for p in group_params}
        frozen = {name: p for name, p in params.items() if name not in mutable}
        require(all(not p.requires_grad and p.grad is None for p in frozen.values()), "Untracked trainable parameter or frozen gradient")
        saved = self.optimizer.state_dict()
        names = {index: by_id[id(parameter)] for group, live in zip(saved["param_groups"], self.optimizer.param_groups, strict=True)
                 for index, parameter in zip(group["params"], live["params"], strict=True)}
        require(len(names) == len(mutable) and all(type(index) is int for index in names), "SGD ID/name mapping differs")
        for group in saved["param_groups"]:
            require(group["differentiable"] is False and group["fused"] is not True, "Differentiable or fused SGD needs a different state contract")
        tensors = list(params.values()) + list(buffers.values())
        for parameter in mutable.values():
            if parameter.grad is not None:
                require(not parameter.grad.requires_grad and parameter.grad.grad_fn is None and parameter.grad.grad is None,
                        "Gradient graph is not serializable")
                tensors.append(parameter.grad)
        for fields in self.optimizer.state.values():
            require(type(fields) is dict and set(fields) <= {"momentum_buffer"}, "Unknown SGD state field")
            require(all(type(value) is torch.Tensor and not value.requires_grad and value.grad_fn is None and value.grad is None
                        for value in fields.values()), "Momentum autograd state is unsupported")
            tensors.extend(fields.values())
        require(len({id(self.model), *(id(model) for model in self.references.values())}) == 3, "Reference model objects must be separate")
        for reference in self.references.values():
            reference_params, reference_buffers, unused_modes, unused_structure = model_parts(reference)
            tensors.extend(reference_params.values()); tensors.extend(reference_buffers.values())
        tensors.extend(storage_leaves((self.context_inputs, self.guard_baseline, self.architecture)))
        independent(tensors)
        owners = [generator_owner(g) for g in self.generators.values()]
        require(len(owners) == len({id(owner) for owner in owners}) and all(owner is not np.random.mtrand._rand._bit_generator for owner in owners),
                "Named RNG objects or underlying BitGenerators alias")
        kinds = {name: generator_kind(g) for name, g in self.generators.items()}
        require(all(type(name) is str and name for name in kinds), "Named RNG names must be nonempty strings")
        return mutable, frozen, buffers, modes, structure, saved, names, kinds

    def _description(self):
        mutable, frozen, buffers, modes, structure, saved, names, kinds = self._parts()
        runtime = runtime_descriptor()
        require(not runtime["inference_mode"] and not runtime["autocast_cpu"], "Inference/autocast boundary is unsupported")
        require(self.binding["runtime_sha256"] == codec.digest(runtime), "Runtime binding differs")
        raw_optimizer_extra = {key: value for key, value in vars(self.optimizer).items()
                               if key not in ("state", "param_groups") and "hooks" not in key}
        require(not list(storage_leaves(raw_optimizer_extra)), "Array optimizer attributes are unsupported")
        extra_optimizer = native(raw_optimizer_extra)
        config = {"device": "cpu", "module_training": modes, "named_rngs": sorted(kinds),
                  "parameters": {name: {"dtype": array(p).dtype.str, "shape": list(p.shape), "requires_grad": p.requires_grad} for name, p in mutable.items()},
                  "buffers": {name: {"dtype": array(b).dtype.str, "shape": list(b.shape)} for name, b in buffers.items()},
                  "architecture_sha256": codec.digest({"declared": native(self.architecture), "structure": structure,
                      "optimizer_static": extra_optimizer, "group_names": [[names[i] for i in g["params"]] for g in saved["param_groups"]],
                      "generator_kinds": kinds})}
        return {"model_refs": {"frozen_base": codec.digest(native(frozen)), **{key: module_identity(model) for key, model in self.references.items()}},
                "model_configuration": config, "source_roles": list(branch_state.ROLES),
                "context_input_sha256": codec.digest(native(self.context_inputs)), "guard_baseline": native(self.guard_baseline)}

    def _mutable(self):
        mutable, unused, buffers, unused_modes, unused_structure, saved, names, kinds = self._parts()
        return {"parameters": native(mutable), "buffers": native(buffers), "requires_grad": {name: p.requires_grad for name, p in mutable.items()},
                "optimizer": {"kind": "SGD", **native(saved)}, "optimizer_parameter_names": names,
                "gradients": {name: None if p.grad is None else array(p.grad) for name, p in mutable.items()},
                "rng": {"torch_cpu": array(torch.get_rng_state()), "python": random.getstate(), "numpy": native(np.random.get_state()),
                        "named": {name: {"kind": kinds[name], "state": generator_state(g, kinds[name])} for name, g in self.generators.items()}}}

    def capture(self, cursor, remaining_schedule):
        verify_foundation()
        require(codec.digest(self._description()) == codec.digest(self.fixed), "Immutable model/context/configuration changed")
        record = {"schema": branch_state.SCHEMA, "binding": native(self.binding), "immutable": native(self.fixed),
                  **self._mutable(), "cursor": native(cursor), "remaining_schedule": native(remaining_schedule)}
        branch_state.validate(record, self.environment_sha256)
        return record

    def _prepare(self, record):
        mutable, unused, buffers, unused_modes, unused_structure, live, names, kinds = self._parts()
        require(record["optimizer_parameter_names"] == names
                and [g["params"] for g in record["optimizer"]["param_groups"]] == [g["params"] for g in live["param_groups"]], "Target optimizer parameter order differs")
        for group in record["optimizer"]["param_groups"]:
            require(group["differentiable"] is False and group["fused"] is not True, "Unsupported recorded SGD flags")
            # Stock constructor validates each group independently, without stepping.
            torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))], **{key: value for key, value in group.items() if key != "params"})
        rng = record["rng"]
        for kind, value in (("torch_cpu", rng["torch_cpu"]), ("python", rng["python"]), ("numpy_randomstate", rng["numpy"])):
            prepare_generator(kind, value)
        for name, entry in rng["named"].items():
            require(set(entry) == {"kind", "state"} and entry["kind"] == kinds[name], "Named RNG type differs")
            prepare_generator(kinds[name], entry["state"])
        parameters = {name: torch.from_numpy(value.copy()) for name, value in record["parameters"].items()}
        buffer_values = {name: torch.from_numpy(value.copy()) for name, value in record["buffers"].items()}
        gradients = {name: None if value is None else torch.from_numpy(value.copy()) for name, value in record["gradients"].items()}
        state = defaultdict(dict, {mutable[names[index]]: {key: torch.from_numpy(value.copy()) for key, value in fields.items()}
                                  for index, fields in record["optimizer"]["state"].items()})
        groups = [{**{key: value for key, value in group.items() if key != "params"},
                   "params": [mutable[names[index]] for index in group["params"]]} for group in record["optimizer"]["param_groups"]]
        return {"targets": (mutable, buffers), "parameters": parameters, "buffers": buffer_values,
                "gradients": gradients, "optimizer_state": state, "optimizer_groups": groups, "rng": rng}

    def _apply(self, prepared):
        mutable, buffers = prepared["targets"]
        with torch.no_grad():
            for name, parameter in mutable.items(): parameter.copy_(prepared["parameters"][name])
            for name, buffer in buffers.items(): buffer.copy_(prepared["buffers"][name])
        for name, parameter in mutable.items(): parameter.grad = prepared["gradients"][name]
        self.optimizer.state, self.optimizer.param_groups = prepared["optimizer_state"], prepared["optimizer_groups"]
        rng = prepared["rng"]
        torch.set_rng_state(torch.from_numpy(rng["torch_cpu"].copy()))
        random.setstate(rng["python"])
        np.random.set_state(rng["numpy"])
        for name, entry in rng["named"].items(): set_generator(self.generators[name], entry["kind"], entry["state"])

    def restore(self, raw, expected_sha256, maximum_bytes):
        verify_foundation()
        record = branch_state.restore(raw, expected_sha256, self.environment_sha256, maximum_bytes)
        require(codec.digest(self._description()) == codec.digest(self.fixed), "Target immutable dependencies or configuration changed")
        prepared = self._prepare(record)
        before = self.capture(record["cursor"], record["remaining_schedule"])
        rollback = self._prepare(before)
        mutable, buffers = rollback["targets"]
        # Preserve original Python objects on failure; apply only replaces these fields.
        rollback["optimizer_state"], rollback["optimizer_groups"] = self.optimizer.state, self.optimizer.param_groups
        rollback["gradients"] = {name: p.grad for name, p in mutable.items()}
        versions = {name: value._version for name, value in {**mutable, **buffers}.items()}
        try:
            self._apply(prepared)
            observed = self.capture(record["cursor"], record["remaining_schedule"])
            require(codec.dumps(observed) == raw, "Restored live state differs from the literal record")
        except BaseException as error:
            equal = False
            try:
                self._apply(rollback)
                equal = codec.dumps(self.capture(record["cursor"], record["remaining_schedule"])) == codec.dumps(before)
            except BaseException:
                pass
            versions_equal = versions == {name: value._version for name, value in {**mutable, **buffers}.items()}
            raise RestoreError(error, equal, versions_equal) from error
        return {"state_sha256": expected_sha256, "environment_sha256": self.environment_sha256,
                "cursor": native(record["cursor"]), "remaining_schedule": native(record["remaining_schedule"]),
                "autograd_version_counters_restored": False, "scientific_kernel_replay": False}
