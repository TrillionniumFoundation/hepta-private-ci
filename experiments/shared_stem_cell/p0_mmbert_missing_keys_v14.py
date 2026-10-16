"""Bounded, research-only diagnostics for failed mmBERT fixed-MLM checkpoint loads.

No LFS weight/source content, labels, env vars or path strings enter this report.
The 2026-10-16 original mmBERT Runner failed before inference. Never waive the
pretrained MLM missing-parameter gate on an unexamined library incompatibility.
"""
from __future__ import annotations
import hashlib
import json
import re

_SAFE = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,119}\Z")
_ALIASES = frozenset({"decoder.weight", "model.embeddings.tok_embeddings.weight"})


class Invalid(ValueError):
    pass


def fail_unverified_pretrained_missing_keys(info):
    """Accept only one verified tied alias; all other reported misses abort.

    The caller must still run independent whole-checkpoint-byte verification
    *after* this check; a valid alias is never treated as proof of model origin.
    """
    if type(info) is not dict:
        raise Invalid("pretrained model loading report missing")
    for category in ("unexpected_keys", "mismatched_keys", "error_msgs"):
        value = info.get(category, [])
        if type(value) not in (list,tuple) or value:
            raise Invalid("unsafe or incomplete pretrained model loading: " + category)
    missing=info.get("missing_keys", [])
    if type(missing) not in (list,tuple) or len(missing)>512 or any(type(k) is not str for k in missing):
        raise Invalid("unbounded pretrained MLM missing-key report")
    unsupported=sorted({k for k in missing if k not in _ALIASES})
    if len(missing)>1 or unsupported:
        # Model parameter names are non-secret constant identifiers. Restrict
        # visibility to checked lexical names, with a bounded diagnostic; keep
        # an exact canonical digest for subsequent source/shape adjudication.
        visible=[name for name in unsupported[:16] if _SAFE.fullmatch(name)]
        digest=hashlib.sha256(json.dumps(sorted(missing),sort_keys=True,
                                         separators=(',',':')).encode()).hexdigest()
        raise Invalid("non-tied pretrained MLM parameter initialized randomly; "
                      f"unverified_count={len(unsupported)}; keys={visible}; "
                      f"missing_name_set_sha256={digest}")
    return {"allowed_single_tied_missing_alias":missing[0] if missing else None,
            "all_other_unverified_missing_parameters_rejected":True,
            "complete_checkpoint_byte_verification_still_required":True,
            "authority":"DENY_ALL"}
