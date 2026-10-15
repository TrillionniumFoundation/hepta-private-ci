"""Fail-closed public Stem identity/profile binding for V5/V10 research callers.

Candidate display names are not security identities. Only a trusted V6 claim
can authorize material use; this additional check prevents supported public
model families from being renamed to bypass their reviewed feature policies.
This module never downloads weights, authenticates publishers, or promotes.
"""
from __future__ import annotations

from multimodal_bridge import ContractError
from public_stem_material_v8 import CATALOG

# Legacy V5 spellings and exact V8/V10 public source spellings are intentionally
# accepted only when they refer to the SAME reviewed publisher model family.
ALIASES = {
    "mmbert_small": "mmbert-small",
    "mmbert-small": "mmbert-small",
    "granite_97m": "granite-97m-r2",
    "granite-97m-r2": "granite-97m-r2",
}


def require_public_native_profile(candidate: str, profile: dict, trusted_policy: dict) -> bool:
    """Require source-anchored pooling for official public-model families.

    Return True for one registered public model; False for other operator-
    approved candidates, which keep all existing V6 signed-material checks.
    Unknown labels cannot disguise an *official* upstream repo. Both this
    function and V6 admission must pass before execution.
    """
    if type(candidate) is not str or type(profile) is not dict or type(trusted_policy) is not dict:
        raise ContractError("invalid public-model policy inputs")
    source = trusted_policy.get("upstream_repo")
    upstream = {v["repo_id"]: k for k, v in CATALOG.items()}
    family = ALIASES.get(candidate)
    if family is None and source not in upstream:
        return False  # Future explicitly reviewed non-public model; V6 still required.
    if family is None or source != CATALOG[family]["repo_id"]:
        raise ContractError("public-model family must match trusted upstream identity")
    definition = CATALOG[family]
    exact = (
        profile.get("candidate") == candidate
        and profile.get("pooling") == definition["pooling"]
        and profile.get("normalization") == definition["normalization"]
        and profile.get("expected_width") == definition["width"]
        and isinstance(profile.get("snapshot"), dict)
        and profile["snapshot"].get("kind") == definition["kind"]
        and trusted_policy.get("expected_width") == definition["width"]
        and trusted_policy.get("kind") == definition["kind"]
    )
    if not exact:
        raise ContractError("pinned public-model feature policy differs from reviewed native profile")
    return True
