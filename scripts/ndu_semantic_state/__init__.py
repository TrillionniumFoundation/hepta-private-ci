"""Versioned public text/image state and byte-bound experimental materials.

These contracts do not certify semantic competence, model execution, or efficacy.
"""

from importlib import import_module

__all__ = [
    "SCHEMA", "MODALITIES", "SemanticState", "actor_binding",
    "check_actor_binding", "check_transition", "from_public_encodings",
    "migrate_v3_latents",
]


def __getattr__(name):
    # Discovery imports packages even when its file pattern excludes their tests.
    # Only explicit use of the state API should require its NumPy dependency.
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(".state", __name__), name)
    globals()[name] = value
    return value
