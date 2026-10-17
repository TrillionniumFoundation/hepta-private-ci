"""Verify historical MemoryCell generator bytes survive development formatting.

The four original research scripts must retain their exact Git object hashes. The
active Python files may be reformatted, but their syntax trees remain equivalent.
This is source provenance only, not model attestation or production admission.
"""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PINS = {
    "locomo_blind_sufficiency.py": (
        "5e90ff826c95607fbb40d8da39bf32e3dd00cb53",
        "d0239ffee607b5431c3cfff9a6ef47bb17b37ab6a5686394d12221fb50ac5e07",
    ),
    "locomo_format_trial.py": (
        "78859c6f617c28297f5f03f13fa7c443de49bedc",
        "3cf5329c6d5fc500a4252e5cdbdae1f3e281dfac0cb48bc1c15b85a27bfc6ed3",
    ),
    "locomo_reader_four_regimes.py": (
        "72ec79ef98f3916c86390db8d8f9725446301ff1",
        "86c081e3da7198acfe4df6bd8ff2e5c53c1eb6d0e613aa83edca8be8e248745a",
    ),
    "locomo_reader_replay.py": (
        "4da31dfac6f2eb806c252548e719a5107193121a",
        "bba625840ec4f3c58bac164f7f78c7f4dd83fd18b9201b176ce1450859948f00",
    ),
}


def object_ids(content):
    return (
        hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest(),
        hashlib.sha256(content).hexdigest(),
    )


def verify_archive(root=ROOT):
    """Fail if an archived original changed, or a formatted copy changed semantics."""
    root = Path(root)
    for name, original_ids in PINS.items():
        original = root / "frozen_source" / (name + ".source")
        live = root / name
        for path in (original, live):
            if (
                path.is_symlink()
                or not path.is_file()
                or not 0 < path.stat().st_size < 100_000
            ):
                raise ValueError("regular, bounded historical code required")
        sealed = original.read_bytes()
        if object_ids(sealed) != original_ids:
            raise ValueError("historical generating Git object changed: " + name)
        if ast.dump(ast.parse(sealed), include_attributes=False) != ast.dump(
            ast.parse(live.read_bytes()), include_attributes=False
        ):
            raise ValueError("formatted development script changed behavior: " + name)
    from locomo_real_evidence_gate import SOURCES
    from locomo_format_result_gate import TRIAL, SOURCE_SHA256

    for key, basename in (
        ("trial", "locomo_reader_four_regimes.py"),
        ("replay", "locomo_reader_replay.py"),
    ):
        expected = "frozen_source/" + basename + ".source"
        if SOURCES[key] != (expected, PINS[basename][0]):
            raise ValueError("model audit no longer references original code: " + key)
    format_source = root / "frozen_source" / "locomo_format_trial.py.source"
    if (
        TRIAL.resolve() != format_source.resolve()
        or SOURCE_SHA256 != PINS["locomo_format_trial.py"][1]
    ):
        raise ValueError("format audit no longer references original code")
    return {
        "schema": "hepta.memory.immutable-generating-code-integrity.v1",
        "original_git_objects": {name: git for name, (git, _) in PINS.items()},
        "byte_identical_original_generators": len(PINS),
        "syntax_tree_equivalent_development_copies": len(PINS),
        "new_model_calls": 0,
        "human_semantic_review": False,
        "production_accepted": False,
        "decision": "DENY_ALL",
    }


if __name__ == "__main__":
    print(json.dumps(verify_archive(), sort_keys=True, indent=2))
