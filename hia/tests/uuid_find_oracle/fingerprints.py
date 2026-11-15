"""Resolve the exact serde/regex units consumed by the real owner artifact."""
import json
from pathlib import Path
import re

from .common import binding, require, verify


def owner_dependencies(graph, packages):
    records, cache = {}, {}

    def inspect(unit):
        key = (unit["package_id"], tuple(unit["files"]))
        if key in cache:
            return cache[key]
        names = [name for name in unit["files"] if name.endswith(".rlib")]
        require(len(names) == 1, "unit must identify exactly one real rlib")
        artifact = graph["files"][names[0]]
        source = Path(artifact["source"])
        suffix = source.stem.rsplit("-", 1)[-1]
        require(re.fullmatch(r"[0-9a-f]{16}", suffix) is not None, "invalid actual Cargo library suffix")
        package = packages[unit["package_id"]]
        base = source.parent.parent / ".fingerprint" / (package["name"] + "-" + suffix) / ("lib-" + unit["target"]["name"])
        json_path = base.with_suffix(".json")
        raw = base.read_bytes()
        require(re.fullmatch(rb"[0-9a-f]{16}", raw) is not None, "invalid actual Cargo fingerprint identity")
        encoded = binding(json_path)
        require(encoded["sha256"] == unit["fingerprint_sha256"], "admitted fingerprint changed")
        body = json.loads(json_path.read_bytes())
        require(json.loads(body["features"]) == unit["features"], "actual fingerprint features differ")
        dependencies = {}
        for dep in body["deps"]:
            require(len(dep) == 4 and isinstance(dep[1], str) and type(dep[3]) is int
                    and 0 <= dep[3] < 2**64 and dep[1] not in dependencies,
                    "ambiguous actual fingerprint dependency")
            dependencies[dep[1]] = dep[3]
        records[str(base)] = binding(base)
        records[str(json_path)] = encoded
        result = {"identity": int.from_bytes(bytes.fromhex(raw.decode()), "little"),
                  "deps": dependencies, "unit": unit}
        cache[key] = result
        return result

    def select(name, identity):
        matches = [inspect(unit) for unit in graph["units"] if unit["target"]["name"] == name
                   and inspect(unit)["identity"] == identity]
        require(len(matches) == 1, "missing/ambiguous actual dependency identity: " + name)
        return matches[0]

    owner = inspect(graph["direct"]["codex_utils_string"]["unit"])
    selected = {name: select(name, owner["deps"][name]) for name in ("serde", "serde_json", "regex_lite")}
    for name, unit in selected.items():
        require(unit["unit"] == graph["direct"][name]["unit"], "direct library does not match the owner's real dependency: " + name)
    require(selected["serde"]["deps"]["serde_core"] == selected["serde_json"]["deps"]["serde_core"],
            "serde and serde_json use different actual serde_core identities")
    core = select("serde_core", selected["serde"]["deps"]["serde_core"])
    regex = selected["regex_lite"]["unit"]
    require(regex["package_id"] == "registry+https://github.com/rust-lang/crates.io-index#regex-lite@0.1.8"
            and regex["features"] == ["default", "std", "string"], "actual regex package/features differ")
    return {"owner": owner, "direct": selected, "serde_core": core,
            "fingerprint_files": list(records.values())}


def verify_fingerprints(record):
    for item in record["fingerprint_files"]:
        verify(item)
