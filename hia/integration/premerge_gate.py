"""Fail-closed offline audit of two independent HIA Draft PR source inventories.

This script never certifies a combined Git tree, native library or product.
"""
import argparse
import json
import re
from pathlib import Path

OWNERS = ("prefix17", "render19")
PINS = ("schema", "repository", "revision", "codex_baseline",
        "target", "borrowed_buffer_capacity")
OID = re.compile(r"[0-9a-f]{40}\Z")
PATHS = {".github/workflows/codex-hia-native.yml", "hia/toolchain.json",
         "hia/tests/test_installed_codex.py", "hia/README.md",
         "hia/migration.json", "hia/verification.json", "hia/template_render.hepta"}


def audit(s):
    if s.get("schema") != "hepta.hia.premerge-input.v1" or set(s.get("owners", {})) != set(OWNERS):
        raise ValueError("invalid snapshot or owners")
    a, b = (s["owners"][x] for x in OWNERS)
    for label, owner in s["owners"].items():
        if not isinstance(owner.get("pr"), int) or owner["pr"] < 1:
            raise ValueError("invalid PR")
        if any(not isinstance(owner.get(k), str) or not OID.fullmatch(owner[k])
               for k in ("head", "toolchain_sha")):
            raise ValueError("invalid pinned Git object")
        tc = owner["toolchain"]
        names = tc.get("modules")
        if not isinstance(names, list) or not names or any(
            not isinstance(n, str) or not n or "/" in n for n in names
        ) or len(names) != len(set(names)):
            raise ValueError("invalid or duplicate modules")
        profiles = tc.get("entry_profiles")
        if not isinstance(profiles, dict) or any(
            n not in names or not isinstance(v, str) or not v
            for n, v in profiles.items()
        ):
            raise ValueError("invalid scalar entry profiles")
    for field in PINS:
        if field not in a["toolchain"] or a["toolchain"][field] != b["toolchain"].get(field):
            raise ValueError("immutable pin mismatch: " + field)
    am, bm = a["toolchain"]["modules"], b["toolchain"]["modules"]
    both = sorted(set(am) & set(bm))
    union = am + [name for name in bm if name not in set(am)]
    scalar = dict(a["toolchain"]["entry_profiles"])
    for key, value in b["toolchain"]["entry_profiles"].items():
        if key in scalar and scalar[key] != value:
            raise ValueError("incompatible scalar ABI: " + key)
        scalar[key] = value
    if not {"prefix_admission", "token_budget"} <= set(scalar):
        raise ValueError("both independently required scalar ABIs must be present")
    paths = s.get("path_blobs")
    if not isinstance(paths, dict) or not PATHS <= set(paths):
        raise ValueError("missing repository source collision inventory")
    different = {}
    for path, pair in paths.items():
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("unsafe path")
        if not isinstance(pair, dict) or set(pair) != set(OWNERS):
            raise ValueError("missing path owners")
        if any(not isinstance(v, str) or not OID.fullmatch(v) for v in pair.values()):
            raise ValueError("invalid source blob identity")
        if pair[OWNERS[0]] != pair[OWNERS[1]]:
            different[path] = pair
    if "template_render" not in both or "hia/template_render.hepta" not in different:
        raise ValueError("native render ABI collision requires explicit fresh review")
    return {
        "schema": "hepta.hia.premerge-hold.v1",
        "result": "HOLD",
        "module_names": union,
        "module_count": len(union),
        "shared_names": both,
        "unresolved_paths": different,
        "entry_profiles": scalar,
        "parents": {name: {"pr": o["pr"], "head": o["head"],
                           "toolchain_sha": o["toolchain_sha"]}
                    for name, o in s["owners"].items()},
        "qualification": {gate: False for gate in
                          ("combined_git_tree", "combined_native_link", "original_public_oracle",
                           "default_native_consumers", "required_platforms", "performance",
                           "default_native_release", "whole_codex", "retire_rust")},
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("snapshot", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit(json.loads(args.snapshot.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("HOLD: no combined tree; " + str(result["module_count"]) + " module names; " +
          str(len(result["unresolved_paths"])) + " divergent paths")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
