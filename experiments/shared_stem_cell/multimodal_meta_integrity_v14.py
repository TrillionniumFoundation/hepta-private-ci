"""Fail-closed diagnosis for unmaterialized HF parameters and buffers.

A model containing meta tensors has not completed physical weight loading.
Provide a bounded, names-only report; never materialize, randomize, resize,
or authorize a partially loaded pretrained checkpoint.
"""
from __future__ import annotations

class UnmaterializedCheckpoint(ValueError):
    pass

def require_materialized(loaded, info: dict) -> None:
    if type(info) is not dict:
        raise UnmaterializedCheckpoint("a full loading-info dictionary is required")
    try:
        parameters = list(loaded.named_parameters(remove_duplicate=False))
        buffers = list(loaded.named_buffers(remove_duplicate=False))
    except (TypeError, AttributeError) as error:
        raise UnmaterializedCheckpoint("model has no verifiable parameter inventory") from error
    meta = sorted(name for name, tensor in [*parameters, *buffers]
                  if bool(getattr(tensor, "is_meta", False)))
    if not meta:
        return
    missing = info.get("missing_keys", ())
    if type(missing) not in (list, tuple):
        missing = ()
    def bounded(items):
        # Names originate from a concrete loaded model, not user-supplied
        # file paths. Keep the diagnostic compact and finite.
        return ",".join(str(x)[:96] for x in list(items)[:8])
    raise UnmaterializedCheckpoint(
        f"meta_tensor_count={len(meta)}; "
        f"meta_names=[{bounded(meta)}]; "
        f"loader_missing_count={len(missing)}; "
        f"loader_missing_names=[{bounded(missing)}]"
    )
