"""AST-only review of existing N256 candidate and oracle source surfaces.

The module never imports the reviewed sources.  In particular it cannot cross
their numerical admission boundaries or execute NumPy, SciPy, model, or Torch
work.
"""

import ast
from pathlib import Path


NUMERICAL_ROOTS = {"jax", "numpy", "scipy", "tensorflow", "torch"}


def _parse(path):
    path = Path(path)
    return ast.parse(path.read_text(), filename=str(path))


def _class_fields(tree, name):
    node = next(
        item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == name
    )
    return tuple(
        item.target.id
        for item in node.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    )


def _function(tree, name):
    return next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )


def _argument_names(function):
    return tuple(argument.arg for argument in function.args.args)


def _loaded_names(node):
    return {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    }


def _attributes(node):
    return {
        item.attr
        for item in ast.walk(node)
        if isinstance(item, ast.Attribute)
    }


def _imports(tree):
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return tuple(sorted(modules))


def inspect_candidate(path):
    tree = _parse(path)
    packet_fields = _class_fields(tree, "Packet")
    advance = _function(tree, "_advance")
    run_lane = _function(tree, "_run_lane")
    template = _function(tree, "_template")
    capsule_fields = _class_fields(tree, "Capsule")
    return {
        "packet_fields": packet_fields,
        "packet_has_output": "output" in packet_fields,
        "advance_accepts_pending": "pending" in _argument_names(advance),
        "template_reads_packet_output": "output" in _attributes(template),
        "run_lane_accepts_pending": "pending" in _argument_names(run_lane),
        "capsule_has_packets": "packets" in capsule_fields,
    }


def inspect_legacy_oracle(path):
    tree = _parse(path)
    packet_fields = _class_fields(tree, "OraclePacket")
    advance = _function(tree, "_advance_segment")
    run_lane = _function(tree, "_run_lane")
    coordinates = _function(tree, "_coordinate_stream")
    coordinate_names = _loaded_names(coordinates) | _attributes(coordinates)
    imports = _imports(tree)
    return {
        "packet_fields": packet_fields,
        "packet_has_output": "output" in packet_fields,
        "advance_accepts_pending": "pending" in _argument_names(advance),
        "run_lane_accepts_pending": "pending" in _argument_names(run_lane),
        "coordinate_stream_mentions_packet": bool(
            {"packet", "packets", "pending"} & coordinate_names
        ),
        "imports_serializer": any("serializer" in module for module in imports),
        "imports": imports,
    }


def inspect_adapter(path):
    tree = _parse(path)
    functions = tuple(
        item.name for item in tree.body if isinstance(item, ast.FunctionDef)
    )
    roots = {module.split(".")[0] for module in _imports(tree)}
    dynamic_names = {
        "advance",
        "advance_segment",
        "expm",
        "expm_multiply",
        "propagate",
        "run_oracle",
        "solve",
    }
    return {
        "functions": functions,
        "numerical_import_roots": tuple(sorted(roots & NUMERICAL_ROOTS)),
        "has_numeric_propagation_entry": bool(dynamic_names & set(functions)),
    }


def review(candidate_path, adapter_path, legacy_oracle_path):
    candidate = inspect_candidate(candidate_path)
    adapter = inspect_adapter(adapter_path)
    legacy = inspect_legacy_oracle(legacy_oracle_path)
    compatible = all(
        (
            legacy["packet_has_output"],
            legacy["advance_accepts_pending"],
            legacy["run_lane_accepts_pending"],
            legacy["coordinate_stream_mentions_packet"],
        )
    )
    return {
        "candidate": candidate,
        "adapter": adapter,
        "legacy_oracle": legacy,
        "legacy_oracle_current_state_compatible": compatible,
    }
