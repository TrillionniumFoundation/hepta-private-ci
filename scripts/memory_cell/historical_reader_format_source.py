"""Replay exposed 2026-10-15 reader-format evidence with ORIGINAL code bytes.

Ruff formatting newer branch sources does not mutate historical preregistration.
These repository-owned immutable plaintext snapshots are hash verified before
their original functions execute. No unverified fallback is permitted.
"""

import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path

SOURCE_PINS = {
    "prompt_representation_probe.py": (
        "reader_format_20261015_prompt.py.txt",
        "84952869d55069d0830add604883750929efd22e1f93bcf34dbc01b40890bcd5",
    ),
    "offline_smol_reader.py": (
        "reader_format_20261015_smol.py.txt",
        "1c43e120fcb8c2510e9ce4ff7cfa1ab71ee00a21e4d076e47ae0f70eeac034d8",
    ),
}


def locked_reader_format(snapshot_dir=None):
    """Return pinned original modules and source digests, never current HEAD."""
    root = (
        Path(snapshot_dir)
        if snapshot_dir is not None
        else Path(__file__).parent / "frozen_source"
    )
    loaded = {}
    hashes = {}
    for original_name, (snapshot_name, expected_sha) in SOURCE_PINS.items():
        path = root / snapshot_name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
            raise ValueError("missing or unsafe historical source snapshot")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha:
            raise ValueError("historical original source bytes changed")
        loader = importlib.machinery.SourceFileLoader(
            "hepta_frozen_" + original_name.replace(".", "_"), str(path)
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        loaded[original_name] = module
        hashes[original_name] = actual
    prompt = loaded["prompt_representation_probe.py"]
    reader = loaded["offline_smol_reader.py"]
    if (
        tuple(prompt.STYLES) != ("verbatim", "normalized")
        or tuple(prompt.ARMS)
        != ("empty", "hybrid", "organized", "without_prerequisite")
        or not callable(prompt.build_messages)
        or not callable(prompt.strict_answer)
        or not callable(reader.ByteLevel)
    ):
        raise ValueError("historical reader source API has drifted")
    return prompt, reader, hashes
