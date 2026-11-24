"""Label-free weight programs for the small HCSN comparison.

These functions construct complete candidate state dictionaries without changing
the caller's model. They never fit labels, call a model, estimate an objective's
derivative, or select candidates using a development/test outcome. A candidate
still needs the caller's common preservation and task checks.

Two exact but limited rules are admitted: replacement of a classification label
schema, and migration of every declared direct input Linear to a new affine
sensor interface. Neither rule creates a new discrimination capability. The
delayed-information capability arm abstains unless an identifiable construction
is supplied; ridge or label-dependent coordinate search must not be called here.
"""

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import time

import torch
from torch import nn


_DEFAULT_HEAD = ("readout.weight", "readout.bias")


def _snapshot(values):
    if not isinstance(values, Mapping) or not values:
        raise ValueError("a nonempty tensor state dictionary is required")
    result = {}
    for name, value in values.items():
        if not isinstance(name, str) or not isinstance(value, torch.Tensor):
            raise TypeError("state names and values must be strings and tensors")
        if value.is_complex():
            raise ValueError("these programs require real model tensors")
        if value.is_floating_point() and not bool(torch.isfinite(value).all()):
            raise ValueError("source state contains a nonfinite tensor")
        result[name] = value.detach().clone()
    return result


def tensor_digest(values):
    """Bind tensor names, dtypes, shapes and complete bytes, including buffers."""
    digest = hashlib.sha256()
    for name, value in sorted(values.items()):
        tensor = value.detach().cpu().contiguous()
        descriptor = json.dumps([name, str(tensor.dtype), list(tensor.shape)],
                                separators=(",", ":")).encode()
        digest.update(len(descriptor).to_bytes(8, "big"))
        digest.update(descriptor)
        digest.update(tensor.reshape(-1).view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def _limits(max_l2, max_linf):
    for value in (max_l2, max_linf):
        if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
            raise ValueError("edit norm bounds must be finite and nonnegative")


def _finish(source, candidate, *, started, cpu_started, program, status, reason,
            allowed_support, max_l2, max_linf, details=None, linear_solves=0):
    changed, l2_squared, linf, invalid_norm = {}, 0.0, 0.0, False
    if candidate.keys() != source.keys():
        raise ValueError("a weight program cannot add or remove state fields")
    for name, before in source.items():
        after = candidate[name]
        if (after.shape != before.shape or after.dtype != before.dtype or after.device != before.device):
            raise ValueError("a weight program cannot change tensor schema")
        if after.is_floating_point() and not bool(torch.isfinite(after).all()):
            status, reason = "ABSTAIN", "nonfinite_constructed_candidate"
            invalid_norm = True
            break
        count = int(torch.count_nonzero(after != before))
        if count:
            if name not in allowed_support:
                raise ValueError("weight program touched a protected state field")
            difference = after.double() - before.double()
            changed[name] = count
            l2_squared += float(difference.square().sum())
            linf = max(linf, float(difference.abs().max()))
    invalid_norm = invalid_norm or not math.isfinite(l2_squared) or not math.isfinite(linf)
    if invalid_norm:
        if status != "ABSTAIN":
            status, reason = "ABSTAIN", "nonfinite_edit_norm"
        proposed_l2, proposed_linf = None, None
    else:
        proposed_l2, proposed_linf = math.sqrt(l2_squared), linf
    if status != "ABSTAIN" and ((max_l2 is not None and proposed_l2 > max_l2)
                                or (max_linf is not None and linf > max_linf)):
        status, reason = "ABSTAIN", "declared_edit_norm_exceeded"
    if status == "ABSTAIN":
        candidate = {name: value.clone() for name, value in source.items()}
        accepted_changed, actual_l2, actual_linf = {}, 0.0, 0.0
    else:
        accepted_changed, actual_l2, actual_linf = changed, proposed_l2, linf
        status = "CANDIDATE" if changed else "KEEP"
        if not changed:
            reason = "identity_rule_leaves_original_weights"
    source_digest = tensor_digest(source)
    candidate_digest = tensor_digest(candidate)
    receipt = {
        "schema": "hcsn-strict-weight-program-v1",
        "program": program,
        "status": status,
        "reason": reason,
        "source_digest": source_digest,
        "candidate_digest": candidate_digest,
        "allowed_support": sorted(allowed_support),
        "changed_parameters": accepted_changed,
        "changed_scalar_count": sum(accepted_changed.values()),
        "delta_l2": actual_l2,
        "delta_linf": actual_linf,
        "proposed_delta_l2": proposed_l2,
        "proposed_delta_linf": proposed_linf,
        "limits": {"max_l2": max_l2, "max_linf": max_linf},
        "adoption_decision": "not_evaluated",
        "protocol": {"label_fitting": False, "label_accesses": 0,
                     "network_forward_calls": 0, "backward_calls": 0,
                     "objective_finite_differences": 0, "candidate_selection_queries": 0},
        "details": details or {},
        "cost": {
            "linear_system_solves": linear_solves,
            "input_state_bytes": sum(t.numel() * t.element_size() for t in source.values()),
            "output_state_bytes": sum(t.numel() * t.element_size() for t in candidate.values()),
            "boundary": "function entry through validation and hashing; caller evaluation/serialization excluded",
            "program_discovery_cost": "not_instrumented; do not infer total learning-time speedup",
        },
    }
    receipt["cost"].update(wall_seconds=time.perf_counter() - started,
                           cpu_seconds=time.process_time() - cpu_started)
    return candidate, receipt


def propose(model, *, rule=None, editable_names=_DEFAULT_HEAD, max_l2=None, max_linf=None):
    """Construct a strict head-only proposal, or honestly abstain.

    A class rule is ``dict(kind='class_permutation', old_to_new=[...],
    scope='replacement_label_schema')``. New row ``old_to_new[i]`` receives old
    row ``i``. It changes the output convention, not the learned discrimination.
    Simultaneously retaining both contradictory label conventions through the
    same unconditional head is unsupported and is refused.
    """
    started, cpu_started = time.perf_counter(), time.process_time()
    _limits(max_l2, max_linf)
    if not isinstance(model, nn.Module) or not isinstance(getattr(model, "readout", None), nn.Linear):
        raise TypeError("model.readout must be the declared nn.Linear head")
    source = _snapshot(model.state_dict())
    names = tuple(editable_names)
    if model.readout.bias is None and names == _DEFAULT_HEAD:
        names = ("readout.weight",)
    if (not names or len(names) != len(set(names))
            or any(name not in _DEFAULT_HEAD or name not in source for name in names)):
        raise ValueError("head program requires a nonempty declared readout parameter mask")
    candidate = {name: value.clone() for name, value in source.items()}
    common = dict(started=started, cpu_started=cpu_started, allowed_support=names,
                  max_l2=max_l2, max_linf=max_linf)
    if rule is None or not isinstance(rule, Mapping) or rule.get("kind") != "class_permutation":
        return _finish(source, candidate, program="capability_rule_unidentified",
                       status="ABSTAIN", reason="no_identifiable_label_free_head_construction",
                       details={"claim": "absence of a supported construction, not proof that WSP is impossible"},
                       **common)
    if (rule.get("scope") != "replacement_label_schema"
            or rule.get("preserve_original_labels", False)
            or rule.get("simultaneous_old_and_new", False)):
        return _finish(source, candidate, program="class_permutation", status="ABSTAIN",
                       reason="conflicting_unconditional_label_schemas_need_an_observed_task_condition",
                       **common)
    size = model.readout.out_features
    mapping = rule.get("old_to_new")
    if (not isinstance(mapping, (list, tuple)) or len(mapping) != size or size < 2
            or any(type(i) is not int for i in mapping) or sorted(mapping) != list(range(size))):
        raise ValueError("old_to_new must be an exact permutation of the existing output classes")
    required = ["readout.weight"] + (["readout.bias"] if model.readout.bias is not None else [])
    if any(name not in names for name in required):
        return _finish(source, candidate, program="class_permutation", status="ABSTAIN",
                       reason="declared_head_mask_cannot_encode_the_complete_rule", **common)
    indices = torch.as_tensor(mapping, dtype=torch.long, device=source["readout.weight"].device)
    for name in required:
        candidate[name][indices] = source[name]
    return _finish(source, candidate, program="class_permutation", status="CANDIDATE",
                   reason="compiled_declared_output_schema", details={
                       "old_to_new": list(mapping), "scope": "replacement_label_schema",
                       "retention": "same semantic predictions after inverse output relabeling; not simultaneous old labels",
                       "capability_claim": "label-interface rule only; no new discrimination claimed"}, **common)


def interface_program(state_dict, linear_paths, transform, *, max_l2=None, max_linf=None):
    """Compile a declared affine input interface into existing Linear weights.

    Convention: column vectors obey ``x_new = A @ x_old + offset``. ``transform``
    is either A or ``{'matrix': A, 'offset': c, 'max_condition': 1e8}``. Every
    direct raw-input Linear must be in ``linear_paths``. For each, W'=W A^-1 and
    b'=b-W'c. The caller owns the completeness of that graph declaration and
    must check full-model equivalence on fresh episodes, including controllers.
    Missing bias with nonzero W'c is unsupported; no architecture is expanded.
    """
    started, cpu_started = time.perf_counter(), time.process_time()
    _limits(max_l2, max_linf)
    source = _snapshot(state_dict)
    candidate = {name: value.clone() for name, value in source.items()}
    if isinstance(linear_paths, str) or not isinstance(linear_paths, Sequence):
        raise TypeError("linear_paths must be the explicit sequence of raw-input Linear module paths")
    paths = tuple(linear_paths)
    if (not paths or len(paths) != len(set(paths))
            or any(not isinstance(path, str) or not path or any(not p for p in path.split('.')) for path in paths)):
        raise ValueError("nonempty unique Linear module paths required")
    allowed = []
    for path in paths:
        weight = source.get(path + ".weight")
        if (weight is None or weight.ndim != 2 or weight.dtype not in (torch.float32, torch.float64)):
            raise ValueError("each declared input Linear must have an FP32/FP64 matrix weight")
        allowed.append(path + ".weight")
        bias = source.get(path + ".bias")
        if bias is not None:
            if bias.shape != (weight.shape[0],) or bias.dtype != weight.dtype or bias.device != weight.device:
                raise ValueError("input Linear bias is incompatible with its weight")
            allowed.append(path + ".bias")
    reference = source[paths[0] + ".weight"]
    size = reference.shape[1]
    if any(source[path + ".weight"].shape[1] != size for path in paths):
        raise ValueError("all declared raw-input branches must share the input dimension")
    specification = transform if isinstance(transform, Mapping) else {"matrix": transform}
    if "matrix" not in specification:
        raise ValueError("the affine interface matrix is required")
    matrix = torch.as_tensor(specification["matrix"], dtype=torch.float64, device=reference.device)
    offset = torch.as_tensor(specification.get("offset", [0.] * size), dtype=torch.float64,
                             device=reference.device)
    if (matrix.shape != (size, size) or offset.shape != (size,)
            or not bool(torch.isfinite(matrix).all()) or not bool(torch.isfinite(offset).all())):
        raise ValueError("finite square input transform and matching offset required")
    condition_limit = specification.get("max_condition", 1e8)
    if isinstance(condition_limit, bool) or not math.isfinite(condition_limit) or condition_limit < 1:
        raise ValueError("finite condition limit at least one required")
    common = dict(started=started, cpu_started=cpu_started, program="affine_input_interface",
                  allowed_support=allowed, max_l2=max_l2, max_linf=max_linf)
    condition = float(torch.linalg.cond(matrix))
    details = {"paths": list(paths), "input_dimension": size,
               "condition_limit": condition_limit,
               "condition_number": condition if math.isfinite(condition) else None,
               "input_rule": "x_new = matrix @ x_old + offset",
               "coverage": "caller-declared direct input branches; full-model equivalence still required",
               "retention": "under the new sensor encoding of the same semantic inputs",
               "capability_claim": "interface migration, not new task competence"}
    if not math.isfinite(condition) or condition > condition_limit:
        return _finish(source, candidate, status="ABSTAIN", reason="singular_or_ill_conditioned_input_rule",
                       details=details, **common)
    solves = 0
    for path in paths:
        old_weight = source[path + ".weight"]
        local_matrix, local_offset = matrix.to(old_weight.device), offset.to(old_weight.device)
        solved = torch.linalg.solve(local_matrix.T, old_weight.double().T).T
        solves += 1
        correction = solved @ local_offset
        bias_key = path + ".bias"
        if bias_key not in source and bool((correction != 0).any()):
            return _finish(source, candidate, status="ABSTAIN", reason="input_offset_requires_unavailable_bias",
                           details=details, linear_solves=solves, **common)
        candidate[path + ".weight"] = solved.to(old_weight)
        if bias_key in source:
            candidate[bias_key] = (source[bias_key].double() - correction).to(source[bias_key])
    return _finish(source, candidate, status="CANDIDATE", reason="compiled_declared_input_interface",
                   details=details, linear_solves=solves, **common)
