"""Bind guard-marker refreshes to the actual formatter's pinned before/after."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import sys


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
OLD = WORKSPACE / "profile-central-callers-proposal-v1/inputs/05-version-v4.json"
NEW = ROOT / "CALLERS_DELTA_PLAN.json"
FORMAT = WORKSPACE / "profile-evaluated-version-formatted-v4"
INPUT = WORKSPACE / "profile-evaluated-version-format-v4/input-payload.json"
SPEC = importlib.util.spec_from_file_location(
    "profile_guard_actual_format_review", ROOT / "overlay/scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


def meta(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def code(text):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(text))


assert meta(OLD.read_bytes())["sha256"] == "f92123daeded33f2f2c8e17d36d7c6d58e9882ba2417a1e55276767a84428af4"
assert meta((FORMAT / "manifest.json").read_bytes())["sha256"] == "cabe1d4baa76eeef490db21181f935988da28950610be26625cbaa94cb05a35e"
assert meta((FORMAT / "format-only.patch").read_bytes())["sha256"] == "719250f816e43288c8eae48090c89990dad5fa71ea9a2c1c950cb8db9ac3303d"
old, new = json.loads(OLD.read_bytes()), json.loads(NEW.read_bytes())
source_inputs = {row["path"]: row for row in json.loads(INPUT.read_bytes())["files"]}
actual = {row["path"]: row for row in json.loads((FORMAT / "manifest.json").read_bytes())["files"]}
changes = []


def walk(before, after, path=()):
    assert type(before) is type(after), path
    if isinstance(before, dict):
        assert before.keys() == after.keys(), path
        for key in before:
            walk(before[key], after[key], path + (key,))
    elif isinstance(before, list):
        assert len(before) == len(after), path
        for index, (left, right) in enumerate(zip(before, after)):
            walk(left, right, path + (index,))
    elif before != after:
        assert isinstance(before, str), path
        assert path[0] == "protected_changes" and path[2] == "after", path
        assert path[3] in {"required_function_order", "required_order"}, path
        row_index = path[1]
        source_path = new["protected_changes"][row_index]["after"]["path"]
        assert source_path == old["protected_changes"][row_index]["after"]["path"]
        original = source_inputs[source_path]
        before_bytes = original["before_utf8"].encode()
        after_bytes = (FORMAT / "actual-derived-postimages" / source_path).read_bytes()
        assert meta(before_bytes) == actual[source_path]["before"], source_path
        assert meta(after_bytes) == actual[source_path]["after"], source_path
        assert before in code(before_bytes.decode()), (path, "before source")
        assert after in code(after_bytes.decode()), (path, "after source")
        # Rustfmt may wrap a match arm in braces or add a trailing comma. This
        # diagnostic does not infer source equivalence: exact original formatter
        # provenance and full before/after hashes above are the authority here.
        punctuation = lambda value: re.sub(r"[\s{},]", "", value)
        assert punctuation(before) == punctuation(after), (path, "non-format token change")
        changes.append({
            "plan_path": list(path), "source_path": source_path,
            "before_marker": before, "after_marker": after,
            "kind": "whitespace" if re.sub(r"\s", "", before) == re.sub(r"\s", "", after)
            else "actual_rustfmt_braces_commas_and_layout",
            "before_source": meta(before_bytes), "after_source": meta(after_bytes),
        })


walk(old, new)
assert len(changes) == 33
report = {
    "status": "ACTUAL_FORMAT_MARKER_REFRESH_VERIFIED",
    "old_plan": meta(OLD.read_bytes()), "actual_plan": meta(NEW.read_bytes()),
    "actual_format_manifest": meta((FORMAT / "manifest.json").read_bytes()),
    "actual_format_patch": meta((FORMAT / "format-only.patch").read_bytes()),
    "source_verifier": meta((ROOT / "overlay/scripts/verify_hepta_callers.py").read_bytes()),
    "changes": changes,
    "all_boundary_caller_inventory_forbidden_data_unchanged": True,
    "changes_only_refresh_actual_source_function_markers": True,
    "source_qa": "NOT_RUN_BY_THIS_REVIEW", "native": "UNRUN", "ordinary_qualification": 0,
}
target = ROOT / "evidence/GUARD_ACTUAL_FORMAT_TRANSITION.json"
assert not target.exists()
target.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"status": report["status"], "changes": len(changes),
                  "actual_plan": report["actual_plan"], "report": meta(target.read_bytes())}))
