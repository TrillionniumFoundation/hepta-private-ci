"""Operational numerical integrity guard for the unchanged frozen choose.

This module is an overlay, not a replacement scientific head. Register it and
its integration in a new operational freeze before using it on scientific data.
An integrity failure stops the phase; it never becomes a baseline fallback.
"""

from contextlib import contextmanager
import hashlib
from pathlib import Path
from types import FunctionType

import numpy as np


FROZEN_HEADS_SHA256 = "19254959a30e3719024841dc91376d1ecdfa018c30427b962a265e3b3d4647f7"
GUARD_SCHEMA = "hepta.fullstudy.operational-finite-head-guard.1"


class HeadIntegrityError(ValueError):
    """A numerical head contract failed before an action may be applied."""


def _array(value, name, shape=None):
    result = np.asarray(value, dtype=np.float64)
    if (shape is not None and result.shape != shape) or not np.isfinite(result).all():
        raise HeadIntegrityError("Invalid finite head array: " + name)
    return result


def _scalar(value, name):
    result = _array(value, name, ())
    return float(result)


def validate_head(head):
    """Read-only admission validation; no clipping, refitting, or gate change."""
    baseline = head["baseline"]
    if type(baseline) is not int or baseline not in range(4):
        raise HeadIntegrityError("Invalid head baseline")
    mean = _array(head["mean"], "mean")
    if mean.ndim != 1 or mean.size == 0:
        raise HeadIntegrityError("Invalid head dimension")
    if "dimension" in head and head["dimension"] != mean.size:
        raise HeadIntegrityError("Head dimension metadata differs")
    scale = _array(head["scale"], "scale", mean.shape)
    coefficients = _array(head["coefficients"], "coefficients", (mean.size, 4))
    intercept = _array(head["intercept"], "intercept", (4,))
    if not (scale > 0).all():
        raise HeadIntegrityError("Head scale must be strictly positive")
    if np.any(coefficients[:, baseline] != 0) or intercept[baseline] != 0:
        raise HeadIntegrityError("Baseline advantage is not structurally zero")
    if _scalar(head["threshold"], "threshold") < 0:
        raise HeadIntegrityError("Head threshold must be nonnegative")
    if _scalar(head["fit_max_standardized_norm"], "fit norm bound") < 0:
        raise HeadIntegrityError("Head fit norm bound must be nonnegative")
    return mean.shape


def guarded_choose(original_choose, head, feature, baseline=None):
    """Call the frozen chooser once and admit only a finite, valid receipt.

The caller must receive this function's return before calling transition.
The original objects and result are returned unmodified on the finite domain.
The original norm exposes nonfinite standardized coordinates, even on BLAS
builds that do not propagate all arithmetic exceptions through np.seterr.
"""
    shape = validate_head(head)
    _array(feature, "feature", shape)
    if baseline is not None and (type(baseline) is not int or baseline != head["baseline"]):
        raise HeadIntegrityError("Deployment baseline differs")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            result = original_choose(head, feature, baseline)
    except FloatingPointError as error:
        raise HeadIntegrityError("Nonfinite head arithmetic") from error
    action, receipt = result
    _array(receipt["predicted_advantages"], "predicted advantages", (4,))
    _scalar(receipt["predicted_margin"], "predicted margin")
    threshold = _scalar(receipt["threshold"], "receipt threshold")
    norm = _scalar(receipt["standardized_norm"], "standardized norm")
    if threshold != head["threshold"] or norm < 0:
        raise HeadIntegrityError("Invalid head receipt")
    if type(action) is not int or action not in range(4) or receipt["chosen_action"] != action:
        raise HeadIntegrityError("Invalid admitted action")
    return result


def make_guarded_choose(original_choose):
    """Explicit runtime binding; retain this module's provenance for inspection."""
    def checked_choose(head, feature, baseline=None):
        return guarded_choose(original_choose, head, feature, baseline)
    return checked_choose


def _verify_loaded_functions(module, source):
    """Check the two numerical callables against the verified source bytes."""
    reference = {"__name__": module.__name__, "__file__": module.__file__}
    exec(compile(source, module.__file__, "exec"), reference)
    if module.__dict__.get("np") is not np:
        raise HeadIntegrityError("Unexpected frozen NumPy binding")
    for name in ("choose", "predict"):
        actual, expected = getattr(module, name, None), reference[name]
        if (type(actual) is not FunctionType or actual.__globals__ is not module.__dict__
                or actual.__code__ != expected.__code__ or actual.__closure__ is not None
                or actual.__defaults__ != expected.__defaults__
                or actual.__kwdefaults__ != expected.__kwdefaults__):
            raise HeadIntegrityError("Loaded frozen callable differs: " + name)


@contextmanager
def installed_choose_guard(run_module, frozen_heads_module):
    """Explicit, temporary binding for a newly registered operational run.

    Importing this module never installs anything. The caller must bind this
    context, its exact inputs, and this source digest in a new operational freeze.
    This is not evidence that any historical or current experiment used it.
    """
    if run_module is frozen_heads_module:
        raise HeadIntegrityError("Run target and frozen head module must be distinct")
    original = frozen_heads_module.choose
    source = Path(frozen_heads_module.__file__).read_bytes()
    if hashlib.sha256(source).hexdigest() != FROZEN_HEADS_SHA256:
        raise HeadIntegrityError("Frozen chooser source bytes differ")
    _verify_loaded_functions(frozen_heads_module, source)
    if run_module.choose is not original:
        raise HeadIntegrityError("Unexpected preexisting chooser binding")
    receipt = {"schema": GUARD_SCHEMA,
               "frozen_heads_sha256": FROZEN_HEADS_SHA256,
               "overlay_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "attempted_calls": 0, "admitted_calls": 0, "failed_calls": 0,
               "binding_tampered": False}
    def checked_choose(head, feature, baseline=None):
        receipt["attempted_calls"] += 1
        try:
            result = guarded_choose(original, head, feature, baseline)
        except BaseException:
            receipt["failed_calls"] += 1
            raise
        receipt["admitted_calls"] += 1
        return result
    run_module.choose = checked_choose
    try:
        yield receipt
    finally:
        tampered = getattr(run_module, "choose", None) is not checked_choose
        run_module.choose = original
        receipt["binding_tampered"] = tampered
        if tampered:
            raise HeadIntegrityError("Guarded chooser binding changed inside context")
