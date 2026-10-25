"""Trusted-controller executable identities; never supplied by a candidate."""

import hashlib
import json
from pathlib import Path
import re


def load_runtime(spec, contract_sha256, profile=None, profile_sha256=None):
    if (profile is None) != (profile_sha256 is None):
        raise ValueError("runtime profile requires both file and exact SHA256")
    if profile is None:
        value = {
            "schema": "hepta.memory-cell.runtime-profile.v1",
            "task_contract_sha256": contract_sha256,
            "tools": spec["tools"],
        }
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    else:
        path = Path(profile)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            raise ValueError("runtime profile must be a bounded regular file")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != profile_sha256:
            raise ValueError("runtime profile hash drift")
        value = json.loads(raw)
    if (
        set(value) != {"schema", "task_contract_sha256", "tools"}
        or value["schema"] != "hepta.memory-cell.runtime-profile.v1"
        or value["task_contract_sha256"] != contract_sha256
        or set(value["tools"]) != set(spec["tools"])
    ):
        raise ValueError("runtime profile does not bind this task and exact tool set")
    for pin in value["tools"].values():
        if (
            set(pin) != {"bytes", "sha256"}
            or type(pin["bytes"]) is not int
            or pin["bytes"] <= 0
            or not isinstance(pin["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None
        ):
            raise ValueError("invalid runtime executable pin")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "tools": value["tools"],
        "mode": "default_local" if profile is None else "controller_supplied",
        "qualification_proven_by_profile_alone": False,
    }
