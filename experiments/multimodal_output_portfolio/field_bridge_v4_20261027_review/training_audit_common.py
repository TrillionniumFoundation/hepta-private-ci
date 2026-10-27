"""Shared independent-auditor constants and finite-value/hash contracts."""
import hashlib
import json
from pathlib import Path
import re

import numpy as np

HERE = Path(__file__).resolve().parent
PORTFOLIO = HERE.parent
SCIENCE = PORTFOLIO / "field_bridge_v4_20261027"
SEEDS = (17, 29, 43)
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", "raw_field",
           "origin_field", "origin_generic", "origin_richer", "origin_h7")
SCHEDULES = (14000, 14001, 14002, 14003)
PANEL = (0, 1, 2, 3, 12, 13, 14, 15, 24, 25, 26, 27, 28, 29)
ROLES = tuple("qualification_" + suffix for suffix in ("gradient", "rehearsal", "probe", "guard"))
OLD_PROTOCOL_SHA = "a267e91deb23aff25bdb27cf23f8274b5bfa8217c51ee962f3360297f6daa7c7"
NAMES = ("current_hard_value", "adapt_image_bce", "adapt_text_ce", "clean_joint_loss",
         "effective_operator_displacement", "momentum_rms", "normalized_learning_time",
         "next_weighted_clipped_gradient_rms", "gradient_momentum_cosine",
         "response_image_bce_derivative_along_v", "response_text_ce_derivative_along_v",
         "clean_joint_loss_derivative_along_v", "adapt_digit_ce", "clean_image_bce",
         "clean_text_ce", "clean_digit_ce", *tuple("module_displacement_"+str(i) for i in range(8)),
         "text_margin_mean", "text_margin_q10", "image_margin_mean", "image_margin_q10",
         "text_margin_below_025", "image_margin_below_01")
TIMING_KEYS = ("policy_control_wall_ns", "policy_control_cpu_ns", "checkpoint_serialization_wall_ns")

SOURCE_MODULES = ('training_qualification_audit.py', 'training_audit_common.py', 'training_audit_trace.py', 'training_audit_checkpoints.py', 'training_audit_run.py', 'training_audit_contracts.py')

def need(condition, reason):
    if not condition:
        raise ValueError(reason)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def object_sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

def vector(value, size, label):
    result = np.asarray(value, dtype=np.float64)
    need(result.shape == (size,) and np.isfinite(result).all(), label + " shape/nonfinite")
    return result

def near(actual, expected, label, atol=1e-12):
    a, b = np.asarray(actual, dtype=np.float64), np.asarray(expected, dtype=np.float64)
    need(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), label + " invalid values")
    error = float(np.max(np.abs(a-b))) if a.size else 0.
    need(error <= atol, label + f" differs by {error}")
    return error

def identity(value, label):
    need(isinstance(value, dict) and set(value) == {"parameters", "optimizer"}
         and all(valid_hash(v) for v in value.values()), label + " invalid identity")


def source_identity():
    """Bind the complete executable auditor and synthetic-contract source set."""
    names = SOURCE_MODULES
    sources = {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names}
    return {"source_files": sources, "source_set_sha256": object_sha(sources)}
