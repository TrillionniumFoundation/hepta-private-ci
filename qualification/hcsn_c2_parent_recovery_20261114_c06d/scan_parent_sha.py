#!/usr/bin/env python3
"""Read-only archive of the exact selected-domain SHA-256 discovery logic.

This source was committed after the discovery execution. It is not a
precommitted qualification protocol and it does not load Torch.
"""

import hashlib
import json
import os
import stat

HOME = "/home/qian-qi"
TARGETS = {
    "e0c8c946aa8010bfcf4df5b9e155235d2fb6b12a9832e4eaa5db3d9afb154d78",
    "bea446e64571e7cd424411036eff207bb6839af4495a7b60cf0f9df81181ba05",
    "cdbca6e633c6aba5f72f08f259ab08b1c5c2c5745d1dbd2f323a78df876e1e79",
    "b7d162101f18628fcfcabb21e9609499d62c8a26ad6d53b9c375ed2e0439d2f4",
    "17d6ad363d82ba31b006d0a4f55ca9c63453fa2c9c34f7370f022e2ff66a4f5c",
    "736ee7d7afe911a3cf5bb7f7ad97babff4dfb74e28a46ec9c148579160a5075c",
}
SKIP = {
    ".git",
    "node_modules",
    ".cache",
    ".cargo",
    ".rustup",
    "__pycache__",
    ".venv",
    "venv",
    "target",
}
MAX_ENTRIES = 500_000
MAX_CANDIDATES = 5_000
MIN_BYTES = 100_000
MAX_BYTES = 10_000_000


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1_048_576), b""):
            value.update(block)
    return value.hexdigest()


def main():
    roots = []
    for name in os.listdir(HOME):
        path = os.path.join(HOME, name)
        if (
            "hcsn" in name.lower()
            and os.path.isdir(path)
            and not os.path.islink(path)
        ):
            roots.append(path)
    roots.sort()

    entries = 0
    candidates = 0
    hashed = 0
    matches = []
    errors = []
    capped = False

    for root in roots:
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [
                name
                for name in dirs
                if name not in SKIP
                and not os.path.islink(os.path.join(base, name))
            ]
            for name in files:
                entries += 1
                if entries > MAX_ENTRIES:
                    capped = True
                    break
                if not name.endswith(".pt"):
                    continue
                path = os.path.join(base, name)
                try:
                    metadata = os.lstat(path)
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    if not MIN_BYTES <= metadata.st_size <= MAX_BYTES:
                        continue
                    candidates += 1
                    if candidates > MAX_CANDIDATES:
                        capped = True
                        break
                    sha256 = digest(path)
                    hashed += 1
                    if sha256 in TARGETS:
                        matches.append(
                            {
                                "path": path,
                                "sha256": sha256,
                                "size": metadata.st_size,
                                "nlink": metadata.st_nlink,
                            }
                        )
                except OSError as error:
                    errors.append({"path": path, "error": type(error).__name__})
            if capped:
                break
        if capped:
            break

    print(
        json.dumps(
            {
                "selection": (
                    "top-level directory basename contains hcsn, "
                    "symlinks excluded"
                ),
                "root_count": len(roots),
                "entries_seen": entries,
                "candidates": candidates,
                "hashed": hashed,
                "matches": matches,
                "match_count": len(matches),
                "capped": capped,
                "errors": errors[:20],
                "error_count": len(errors),
                "torch_imports": 0,
                "model_executions": 0,
                "optimizer_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
