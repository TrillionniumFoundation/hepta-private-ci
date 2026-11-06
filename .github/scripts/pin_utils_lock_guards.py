"""Reject unrelated Bazel lock facts in the fixed five-version proposal."""

from copy import deepcopy
import json

from pin_utils_proposal_evidence import require


def normalized_fact(raw):
    fact = json.loads(raw)
    require(set(fact) == {"dependencies", "features"}, "UNEXPECTED_CRATE_FACT_FIELDS")
    dependencies = []
    for original in fact["dependencies"]:
        dependency = deepcopy(original)
        dependency.setdefault("kind", "normal")
        dependency.setdefault("target", None)
        dependency.setdefault("default_features", True)
        dependency.setdefault("optional", False)
        dependency.setdefault("features", [])
        dependency["features"].sort()
        requirement = dependency["req"]
        if requirement and requirement[0].isdigit():
            dependency["req"] = "^" + requirement
        dependencies.append(dependency)
    fact["dependencies"] = sorted(dependencies, key=lambda item: json.dumps(item, sort_keys=True))
    fact["features"] = {name: sorted(values) for name, values in fact["features"].items()}
    return fact


def module_guard(before_raw, after_raw, spec):
    before, after = (json.loads(raw) for raw in (before_raw, after_raw))
    section = "@@rules_rs+//rs:extensions.bzl%crate"
    original = before["facts"][section]
    generated = after["facts"][section]
    old_keys = {crate["name"] + "_" + crate["version"] for crate in spec["crates"]}
    pin_key = "pin-utils_" + spec["pin_utils"]["version"]
    old_keys.add(pin_key)
    new_keys = {"path+crates/" + crate["vendor"].removeprefix("codex-rs/") + "_" + crate["name"]
                for crate in spec["crates"]}
    require(len(old_keys) == 6 and len(new_keys) == 5, "MODULE_CRATE_ROSTER_MISMATCH")
    require(original.keys() - generated.keys() == old_keys, "MODULE_REMOVED_FACTS_MISMATCH")
    require(generated.keys() - original.keys() == new_keys, "MODULE_ADDED_FACTS_MISMATCH")
    require(normalized_fact(original[pin_key]) == {"dependencies": [], "features": {}},
            "UNEXPECTED_PIN_UTILS_FACT")
    checks = []
    for crate in spec["crates"]:
        old_key = crate["name"] + "_" + crate["version"]
        new_key = "path+crates/" + crate["vendor"].removeprefix("codex-rs/") + "_" + crate["name"]
        expected = normalized_fact(original[old_key])
        removed = [dependency for dependency in expected["dependencies"] if dependency["name"] == "pin-utils"]
        require(len(removed) == 1, "MODULE_PIN_EDGE_MISMATCH")
        expected["dependencies"].remove(removed[0])
        if crate["name"] == "loom":
            expected["features"]["pin-utils"] = []
        if crate["name"] == "hyper":
            expected["features"]["http1"].remove("dep:pin-utils")
        require(normalized_fact(generated[new_key]) == expected, "MODULE_CRATE_FACT_DRIFT")
        checks.append({"old_key": old_key, "new_key": new_key,
                       "original_dependency_and_feature_semantics_preserved_except_pin_removal": True})
    for key in old_keys:
        del original[key]
    for key in new_keys:
        del generated[key]
    require(before == after, "UNRELATED_MODULE_LOCK_DRIFT")
    return {"removed_registry_facts": sorted(old_keys), "added_path_facts": sorted(new_keys),
            "crate_checks": checks, "all_other_module_fields_identical": True}
