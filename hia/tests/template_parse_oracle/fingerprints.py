"""Follow the actual lib-test fingerprint to its three genuine dev-dependency units."""
import json
from pathlib import Path
import re

from .common import require, verify
from .original import catalog


def owner_dependencies(graph, packages):
    records, cache = {}, {}

    def inspect(unit):
        identity = unit["fingerprint"]["identity_file"]
        encoded = unit["fingerprint"]["json_file"]
        key = identity["path"]
        if key in cache:
            return cache[key]
        verify(identity)
        verify(encoded)
        raw = Path(key).read_bytes()
        require(re.fullmatch(rb"[0-9a-f]{16}", raw) is not None, "invalid actual fingerprint identity")
        body = json.loads(Path(encoded["path"]).read_bytes())
        require(json.loads(body["features"]) == unit["features"], "actual fingerprint features differ")
        dependencies = {}
        for dep in body["deps"]:
            require(len(dep) == 4 and isinstance(dep[1], str) and type(dep[3]) is int
                    and 0 <= dep[3] < 2**64 and dep[1] not in dependencies,
                    "ambiguous actual fingerprint dependency")
            dependencies[dep[1]] = dep[3]
        records[key], records[encoded["path"]] = identity, encoded
        result = {"identity": int.from_bytes(bytes.fromhex(raw.decode()), "little"),
                  "deps": dependencies, "unit": unit}
        cache[key] = result
        return result

    def select(name, identity):
        matches = [inspect(unit) for unit in graph["units"] if unit["target"]["name"] == name
                   and inspect(unit)["identity"] == identity]
        require(len(matches) == 1, "missing/ambiguous actual consumed dependency: " + name)
        actual = matches[0]
        require(actual["unit"] == graph["direct"][name]["unit"], "selected unit is not the direct admitted rlib")
        spec = catalog()["registry_packages"].get(actual["unit"]["package_id"])
        require(spec is not None and actual["unit"]["features"] == spec["features"],
                "real consumed registry package/features differ")
        package = packages[actual["unit"]["package_id"]]
        require(package["name"] == spec["lock"]["name"] and package["version"] == spec["lock"]["version"],
                "actual consumed package metadata differs")
        return actual

    owner = inspect(graph["direct"]["codex_utils_template"]["unit"])
    test = inspect(graph["owner_test"])
    require(set(owner["deps"]) == {"build_script_build"}, "ordinary std-only owner dependency set differs")
    require(set(test["deps"]) == {"pretty_assertions", "build_script_build"},
            "whole lib-test must consume the genuine pretty_assertions unit")
    require(owner["deps"]["build_script_build"] == test["deps"]["build_script_build"],
            "ordinary library and lib-test use different build-script outputs")
    pretty = select("pretty_assertions", test["deps"]["pretty_assertions"])
    require(set(pretty["deps"]) == {"diff", "yansi"}, "complete assertion dependency closure differs")
    selected = {"pretty_assertions": pretty}
    for name in ("diff", "yansi"):
        selected[name] = select(name, pretty["deps"][name])
        require(selected[name]["deps"] == {}, "unexpected transitive assertion dependency")
    return {"ordinary_owner": owner, "actual_lib_test": test, "consumed_registry_units": selected,
            "fingerprint_files": list(records.values()),
            "test_dependencies_selected_from_actual_test_unit": True}


def verify_fingerprints(record):
    for item in record["fingerprint_files"]:
        verify(item)
