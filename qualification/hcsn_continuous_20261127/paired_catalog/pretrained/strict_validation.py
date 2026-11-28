"""Fail-closed validation shared by the pretrained catalog entry points."""


def require_integrity(condition: bool, message: str) -> None:
    """Raise explicitly when a sealed-input or result invariant is violated."""
    if not condition:
        raise ValueError(message)
