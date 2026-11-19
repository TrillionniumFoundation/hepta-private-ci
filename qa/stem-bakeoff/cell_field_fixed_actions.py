"""Source-only development candidate; does not execute models or load datasets."""
import hashlib
import math

DOMAIN = b"hepta-cell-fixed-library-development-20261025-v1"


def fixed_library(parameters):
    """49 bounded impulses, independent of checkpoint, losses and optimizers.

    Eight fixed SHA-256 sign directions, their antipodes, three amplitudes,
    and zero. The exact float arrays must be sealed before any branch run.
    """
    if type(parameters) is not int or parameters not in (36, 52):
        raise ValueError("only registered Linear36/Gated52 dimensions allowed")
    bound = 1.0 / math.sqrt(parameters)
    rows = [("zero", (0.0,) * parameters)]
    for direction in range(8):
        signs = tuple(1 if hashlib.sha256(
            DOMAIN + f"/{parameters}/{direction}/{j}".encode("ascii")
        ).digest()[0] & 1 else -1 for j in range(parameters))
        for numerator, denominator in ((1, 8), (1, 2), (1, 1)):
            for polarity in (-1, 1):
                name = f"d{direction}:a{numerator}/{denominator}:s{polarity}"
                rows.append((name, tuple(polarity * s * bound * numerator / denominator
                                         for s in signs)))
    if len(set(vector for _, vector in rows)) != 49:
        raise ValueError("registered directions collided; do not silently reseed")
    return tuple(rows)


def development_role_admission(roles):
    """Deny validation/final/past final roles, even though now publicly exposed."""
    allowed = {"old_train", "old_probe", "current_train", "current_probe"}
    if not isinstance(roles, (list, tuple)) or not roles:
        raise ValueError("explicit nonempty role list required")
    if any(type(role) is not str or role not in allowed for role in roles):
        raise ValueError("development stage admits original training/probe roles only")
    if len(set(roles)) != len(roles):
        raise ValueError("duplicate role")
    return tuple(roles)
