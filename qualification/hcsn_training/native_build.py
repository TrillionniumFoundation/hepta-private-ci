"""Resolve the exact libraries reported by one successful Cargo build."""

import json
import hashlib
from pathlib import Path


def native_libraries(deps, names, artifacts=None):
    deps = Path(deps).resolve()
    if artifacts is None:
        # Compatibility with an isolated, previously built development target.
        matches = {name: list(deps.glob(f"lib{name}-*.rlib")) for name in names}
    else:
        records = {name: [] for name in names}
        finished = False
        with Path(artifacts).open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                if item.get("reason") == "build-finished":
                    if finished or item.get("success") is not True:
                        raise ValueError("Cargo artifact stream is not one successful build")
                    finished = True
                elif finished:
                    raise ValueError("Cargo artifact records follow build completion")
                elif item.get("reason") == "compiler-artifact":
                    name = item["target"]["name"]
                    if name in records and not item["profile"]["test"]:
                        records[name].append([Path(p).resolve() for p in item["filenames"]])
        if not finished:
            raise ValueError("Cargo build completion is missing")
        matches = {}
        for name, entries in records.items():
            # Explicitly selected Cargo packages have a top-level .rlib and a
            # hashed .rmeta. Build-host variants have only paths inside deps.
            primary = deps.parent/f"lib{name}.rlib"
            selected = [entry for entry in entries if primary in entry]
            if selected:
                matches[name] = []
                for entry in selected:
                    metadata = [p for p in entry if p.parent == deps
                                and p.name.startswith(f"lib{name}-") and p.suffix == ".rmeta"]
                    if len(metadata) != 1:
                        raise ValueError(f"Cargo selected library metadata is ambiguous: {name}")
                    library = metadata[0].with_suffix(".rlib")
                    if (not library.is_file() or not primary.is_file()
                            or hashlib.sha256(library.read_bytes()).digest()
                            != hashlib.sha256(primary.read_bytes()).digest()):
                        raise ValueError(f"Cargo selected library alias changed: {name}")
                    matches[name].append(library)
            else:
                raise ValueError(f"Cargo explicit target record is missing: {name}")
    libraries = {}
    for name, paths in matches.items():
        paths = list(dict.fromkeys(p.resolve() for p in paths))
        if len(paths) != 1 or paths[0].parent != deps or not paths[0].is_file():
            raise ValueError(f"expected one retained {name} rlib in {deps}, found {paths}")
        if not paths[0].name.startswith(f"lib{name}-"):
            raise ValueError(f"Cargo library name differs for {name}")
        libraries[name] = paths[0]
    return libraries
