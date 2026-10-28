"""Narrow stock CPU GRU cache inspection; never calls a model or repairs caches."""

import ast
import hashlib
import json
from pathlib import Path
import sys
from types import CodeType, FunctionType
import weakref

import torch

BASE_SHA256 = "59b32cbd4ac52dee2e3b0dec7f1c0b197d2c84dbd6fdf404156ad788d3d38e21"
BASE_PATH = Path(__file__).resolve().parent.parent / "field_bridge_v6_torch_adapter_preparation_20261028/adapter.py"
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA256:
    raise ValueError("Frozen strict adapter source differs")
from ..field_bridge_v6_torch_adapter_preparation_20261028 import adapter as strict

require, codec = strict.require, strict.codec
GRU = torch.nn.GRU
RNN = sys.modules[GRU.__module__]
MODULE = sys.modules[torch.nn.Module.__module__]
PACKAGE_SOURCES = {
    "rnn": (Path(RNN.__file__), "10f560ff680379df780263dd0b09051390359e879e9a2ad6bcffb68dd2ff8d70"),
    "module": (Path(MODULE.__file__), "0cb24956454199a46e8fc37a7cce4fc1cff52130f25fb6eb052745e9eca89067"),
}
METHODS = {
    "rnn": {"GRU": ("__init__", "forward"), "RNNBase": ("__init__", "__setattr__", "_init_flat_weights",
        "flatten_parameters", "_apply", "_weights_have_changed", "_update_flat_weights", "permute_hidden",
        "check_forward_args", "check_input", "get_expected_hidden_size", "check_hidden_size")},
    "module": {"Module": ("__getattr__", "__setattr__", "_wrapped_call_impl", "_call_impl")},
}


def code_value(value):
    """Canonical code fields, independent of marshal reference/intern flags."""
    if isinstance(value, CodeType):
        fields = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals", "co_stacksize", "co_flags",
                  "co_code", "co_consts", "co_names", "co_varnames", "co_filename", "co_name", "co_qualname",
                  "co_firstlineno", "co_linetable", "co_exceptiontable", "co_freevars", "co_cellvars")
        return ["code", {name: code_value(getattr(value, name)) for name in fields}]
    if value is None or value is Ellipsis: return ["none" if value is None else "ellipsis"]
    if type(value) in (bool, int, str): return [type(value).__name__, value]
    if type(value) is float: return ["float", value.hex()]
    if type(value) is complex: return ["complex", value.real.hex(), value.imag.hex()]
    if type(value) is bytes: return ["bytes", value.hex()]
    if type(value) is tuple: return ["tuple", [code_value(item) for item in value]]
    if type(value) is dict: return ["dict", sorted(((code_value(key), code_value(item)) for key, item in value.items()), key=repr)]
    if type(value) is frozenset: return ["frozenset", sorted((code_value(item) for item in value), key=repr)]
    raise ValueError("Unknown code constant type")


def code_sha256(code):
    return hashlib.sha256(json.dumps(code_value(code), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_contracts():
    result = {}
    for key, (path, expected) in PACKAGE_SOURCES.items():
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, "Installed stock module source differs")
        tree = ast.parse(raw, filename=str(path))
        # Compilation only: no code object from this source is executed.
        module_code = compile(raw, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
        for class_name, methods in METHODS[key].items():
            class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
            class_code = next(value for value in module_code.co_consts if isinstance(value, CodeType) and value.co_name == class_name)
            for name in methods:
                node = [node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == name][-1]
                code = [value for value in class_code.co_consts if isinstance(value, CodeType) and value.co_name == name][-1]
                result[(key, class_name, name)] = {"code_sha256": code_sha256(code),
                    "defaults": tuple(ast.literal_eval(value) for value in node.args.defaults) or None,
                    "kwdefaults": {arg.arg: ast.literal_eval(value) for arg, value in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True) if value is not None} or None}
    return result


EXPECTED_METHODS = source_contracts()


def verify_stock_methods():
    require(torch.nn.GRU is GRU and RNN.GRU is GRU, "Stock GRU class identity changed")
    require(hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() == BASE_SHA256, "Frozen strict adapter source changed")
    for path, expected in PACKAGE_SOURCES.values():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "Installed stock source changed")
    for (key, class_name, name), expected in EXPECTED_METHODS.items():
        owner = getattr(RNN if key == "rnn" else MODULE, class_name)
        function = getattr(owner, name)
        require(type(function) is FunctionType and function.__globals__ is vars(RNN if key == "rnn" else MODULE), "Stock GRU/Module method namespace changed")
        require(code_sha256(function.__code__) == expected["code_sha256"]
                and code_value(function.__defaults__) == code_value(expected["defaults"])
                and code_value(function.__kwdefaults__) == code_value(expected["kwdefaults"]), "Stock GRU/Module method code or defaults changed")
        for variable, cell in zip(function.__code__.co_freevars, function.__closure__ or (), strict=True):
            require(variable == "__class__" and cell.cell_contents is owner, "Stock method closure changed")
        if name not in METHODS["rnn"]["GRU"] and (key == "rnn" or name not in METHODS["rnn"]["RNNBase"]):
            require(getattr(GRU, name) is function, "GRU inherited method resolution changed")
    require(GRU.__getattribute__ is object.__getattribute__ and GRU.__getattr__ is MODULE.Module.__getattr__
            and GRU.__call__ is MODULE.Module._wrapped_call_impl, "Stock GRU attribute/call dispatch changed")


def validate_gru(module):
    verify_stock_methods()
    require(type(module) is GRU, "Only exact stock GRU is supported")
    require(type(module.input_size) is int and module.input_size > 0 and type(module.hidden_size) is int and module.hidden_size > 0,
            "Invalid GRU dimension type")
    require(module.mode == "GRU" and type(module.num_layers) is int and module.num_layers == 1 and module.bias is True
            and module.batch_first is True and type(module.dropout) is float and module.dropout == 0.
            and module.bidirectional is False and type(module.proj_size) is int and module.proj_size == 0,
            "Only single-layer unidirectional bias-on batch-first dropout-zero GRU is supported")
    names = ["weight_ih_l0", "weight_hh_l0", "bias_ih_l0", "bias_hh_l0"]
    require(type(module._flat_weights_names) is list and all(type(name) is str for name in module._flat_weights_names)
            and module._flat_weights_names == names and type(module._all_weights) is list and len(module._all_weights) == 1
            and type(module._all_weights[0]) is list and module._all_weights[0] == names
            and all(type(name) is str for name in module._all_weights[0]), "GRU cache names/order differ")
    require(tuple(module._parameters) == tuple(names) and not module._buffers and not module._modules, "Unexpected registered GRU state")
    require(type(module._flat_weights) is list and type(module._flat_weight_refs) is list
            and len(module._flat_weights) == len(module._flat_weight_refs) == 4, "GRU cache count/container differs")
    shapes = [(3 * module.hidden_size, module.input_size), (3 * module.hidden_size, module.hidden_size),
              (3 * module.hidden_size,), (3 * module.hidden_size,)]
    for name, shape, cached, reference in zip(names, shapes, module._flat_weights, module._flat_weight_refs, strict=True):
        parameter = module._parameters[name]
        require(type(parameter) is torch.nn.Parameter and getattr(module, name) is parameter and cached is parameter
                and type(reference) is weakref.ReferenceType and reference.__callback__ is None and reference() is parameter,
                "GRU cached tensor/weakref is not its registered parameter")
        require(parameter.device.type == "cpu" and parameter.dtype == torch.float32 and tuple(parameter.shape) == shape
                and parameter.storage_offset() == 0 and parameter.untyped_storage().nbytes() == parameter.numel() * parameter.element_size(),
                "GRU cache layout differs from the declared CPU float32 profile")
    strict.independent(module._flat_weights)
    method_names = {name for methods in METHODS.values() for values in methods.values() for name in values}
    require(not (set(vars(module)) & method_names), "Instance GRU/Module method override is unsupported")
    return {"contract": "stock-cpu-gru-derived-cache-v1", "source_sha256": PACKAGE_SOURCES["rnn"][1],
            "cached_parameter_names": names, "weakrefs_are_derived_only": True}


def model_parts(model):
    if not any(isinstance(module, GRU) for module in model.modules()):
        return strict.model_parts(model)
    require(isinstance(model, torch.nn.Module), "Expected a Module")
    modules = list(model.named_modules(remove_duplicate=False))
    require(len({id(module) for unused, module in modules}) == len(modules), "Shared module aliases are unsupported")
    structural, modes = {}, {}
    for name, module in modules:
        attrs = vars(module)
        require(not any(value for key, value in attrs.items() if "hooks" in key), "Module hooks are unsupported")
        excluded = {"training", "_parameters", "_buffers", "_modules", "_non_persistent_buffers_set", "_is_full_backward_hook"}
        raw_extra = {key: value for key, value in attrs.items() if key not in excluded and "hooks" not in key}
        if type(module) is GRU:
            verified = validate_gru(module)
            raw_extra = {key: value for key, value in raw_extra.items() if key not in ("_flat_weights", "_flat_weight_refs")}
            raw_extra["validated_derived_gru_cache"] = verified
        require(not list(strict.storage_leaves(raw_extra)), "Array module attributes must be registered parameters or buffers")
        extra = strict.native(raw_extra)
        require(type(module.training) is bool, "Invalid module mode")
        modes[name] = module.training
        structural[name] = {"class": type(module).__module__ + "." + type(module).__qualname__, "attributes": extra,
                            "nonpersistent_buffers": sorted(module._non_persistent_buffers_set),
                            "none_parameters": sorted(key for key, value in module._parameters.items() if value is None),
                            "none_buffers": sorted(key for key, value in module._buffers.items() if value is None)}
    params, buffers = list(model.named_parameters(remove_duplicate=False)), list(model.named_buffers(remove_duplicate=False))
    require(len({id(value) for unused, value in params + buffers}) == len(params + buffers), "Named tensor aliases are unsupported")
    require(all(not b.requires_grad and b.grad_fn is None and b.grad is None for unused, b in buffers), "Buffer autograd state is unsupported")
    strict.independent(value for unused, value in params + buffers)
    return dict(params), dict(buffers), modes, structural


def module_identity(model):
    params, buffers, modes, structural = model_parts(model)
    require(all(not p.requires_grad and p.grad is None for p in params.values())
            and not any(modes.values()), "Immutable reference models must be frozen and in eval mode")
    return codec.digest({"parameters": strict.native(params), "buffers": strict.native(buffers), "modes": modes, "structure": structural})
