"""Resolve one exact, already-started merge; never run Rust or a full proof."""
from collections import Counter
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / "issuer-integration-audit-v1"
REFS = {
    "base": "6d900c56b330089f0de380b28c7f57bb8072be30",
    "left": "7832eef16022f1af233e2a48ef46fb1ac61dcd8f",
    "right": "4993c1fe99dc412067f34f122912c90fcc3af403",
}
FORMAT = "514fe5f53cfdc254477667f8862d652ea756c807"
PREFORMAT = "619f3ea4ee34096c467da1c15c4a8836fc231113"
AGENT = "codex-rs/hepta-agentd/src/"
RUST = [AGENT + "circuit_retained_version_" + name + ".rs"
        for name in ("client", "effect", "host", "service")]
WORKFLOW = ".github/workflows/hepta-daemon-learning-native.yml"
QA = "qa/b4-no-bypass/test_resident_root_source_closure.py"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def content(ref, path):
    return git("show", ref + ":" + path)


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(text):
    raw = text.encode()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def functions(text):
    found = {}
    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + node.name] = ast.dump(node, include_attributes=False)
    visit(ast.parse(text).body)
    return found


assert git("rev-parse", "HEAD").strip() == REFS["left"]
assert git("rev-parse", "MERGE_HEAD").strip() == REFS["right"]
assert git("merge-base", "--all", REFS["left"], REFS["right"]).splitlines() == [REFS["base"]]
conflicts = git("diff", "--name-only", "--diff-filter=U").splitlines()
assert set(conflicts) == {"CALLERS.toml", WORKFLOW, *RUST}, conflicts
AUDIT.mkdir(exist_ok=False)
report = {"refs": REFS, "conflicts": conflicts, "rust_resolution": [],
          "scope": "source integration and canonical preservation only; no fmt, Rust, native or full source qualification"}
for path in conflicts:
    out = AUDIT / "initial-conflicts" / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text((ROOT / path).read_text())

# The four left versions are exactly the known formatter postimages. All
# semantic changes on these paths belong to the right. Preserve them verbatim.
for path in RUST:
    base = content(REFS["base"], path)
    left = content(REFS["left"], path)
    right = content(REFS["right"], path)
    assert base == content(PREFORMAT, path), path
    assert left == content(FORMAT, path), path
    (ROOT / path).write_text(right)
    report["rust_resolution"].append({"path": path, "base": digest(base),
        "left_formatter_postimage": digest(left), "selected_right": digest(right),
        "base_equals_619": True, "left_equals_514": True})

texts = {side: content(ref, "CALLERS.toml") for side, ref in REFS.items()}
manifests = {side: tomllib.loads(text) for side, text in texts.items()}
for key in manifests["base"]:
    if key not in {"boundary", "protected_file", "privileged_inventory"}:
        assert manifests["base"][key] == manifests["left"][key] == manifests["right"][key], key
for side, expected in (("base", (462, 360)), ("left", (480, 368)), ("right", (465, 365))):
    assert (len(manifests[side]["boundary"]), len(manifests[side]["protected_file"])) == expected
by_id = {side: {row["id"]: row for row in value["boundary"]}
         for side, value in manifests.items()}
for side in by_id:
    assert len(by_id[side]) == len(manifests[side]["boundary"])
selected = {}
for identifier in dict.fromkeys([*by_id["left"], *by_id["right"]]):
    base, left, right = [by_id[side].get(identifier) for side in ("base", "left", "right")]
    if left == right:
        result = left
    elif left == base:
        result = right
    elif right == base:
        result = left
    else:
        raise AssertionError(("unreviewed boundary conflict", identifier, base, left, right))
    if result is not None:
        selected[identifier] = result
new_ids = set(by_id["right"]) - set(by_id["base"])
assert new_ids == {
    "learning_retained_version_original_issuer_attenuation",
    "learning_retained_version_original_issuer_request",
    "learning_retained_version_original_issuer_worker",
}
changed_existing = {key for key in by_id["base"] if by_id["right"].get(key) != by_id["base"][key]}
assert changed_existing == {"learning_retained_version_original_final_use"}
final_use = selected["learning_retained_version_original_final_use"]
assert final_use["product_callers"] == [AGENT + "circuit_retained_version_issuer.rs"]
assert {k: v for k, v in final_use.items() if k != "product_callers"} == {
    k: v for k, v in by_id["base"][final_use["id"]].items() if k != "product_callers"}
counts = {side: Counter(canon(row) for row in value["protected_file"])
          for side, value in manifests.items()}
desired_rows = ((counts["base"] & counts["left"] & counts["right"])
                + ((counts["left"] - counts["base"]) | (counts["right"] - counts["base"])))
assert sum(desired_rows.values()) == 373
assert len(selected) == 483
header = re.compile(r"(?m)^[ \t]*(?:\[\[[ \t]*(boundary|protected_file)[ \t]*\]\]|\[[ \t]*(privileged_inventory|authority)[ \t]*\])[ \t]*(?:#[^\n]*)?$")
def chunks(text):
    matches = list(header.finditer(text))
    result = [("metadata", text[:matches[0].start()], None)]
    for index, match in enumerate(matches):
        raw = text[match.start():matches[index+1].start() if index+1 < len(matches) else len(text)]
        kind = match.group(1) or match.group(2)
        parsed = tomllib.loads(raw)[kind]
        result.append((kind, raw, parsed[0] if kind in {"boundary", "protected_file"} else parsed))
    return result
pieces = {side: chunks(text) for side, text in texts.items()}
raw_boundaries = {canon(row): raw for side in ("right", "left")
                  for kind, raw, row in pieces[side] if kind == "boundary"}
inventory = [identifier for identifier in dict.fromkeys(
    manifests["left"]["privileged_inventory"]["required_boundary_ids"]
    + manifests["right"]["privileged_inventory"]["required_boundary_ids"])
    if identifier in selected]
assert len(inventory) == len(set(inventory)) == len(selected)
assert set(inventory) == set(selected)
remaining = desired_rows.copy()
emitted = set()
output = []
for kind, raw, row in pieces["left"]:
    if kind in {"metadata", "authority"}:
        output.append(raw)
    elif kind == "privileged_inventory":
        assert set(row) == {"required_boundary_ids"}
        assignment = re.search(r"required_boundary_ids\s*=\s*(\[[\s\S]*?\])", raw)
        assert assignment
        output.append(raw[:assignment.start(1)] + json.dumps(inventory)
                      + raw[assignment.end(1):])
    elif kind == "boundary":
        if row["id"] in selected:
            output.append(raw_boundaries[canon(selected[row["id"]])])
            emitted.add(row["id"])
    else:
        key = canon(row)
        if remaining[key]:
            output.append(raw)
            remaining[key] -= 1
for kind, raw, row in pieces["right"]:
    if kind == "boundary" and row["id"] in selected and row["id"] not in emitted:
        output.append(raw_boundaries[canon(selected[row["id"]])])
        emitted.add(row["id"])
    elif kind == "protected_file" and remaining[canon(row)]:
        output.append(raw)
        remaining[canon(row)] -= 1
assert not any(remaining.values())
merged = "".join(output).rstrip() + "\n"
parsed = tomllib.loads(merged)
assert {row["id"]: row for row in parsed["boundary"]} == selected
assert Counter(canon(row) for row in parsed["protected_file"]) == desired_rows
for key in parsed:
    if key not in {"boundary", "protected_file", "privileged_inventory"}:
        assert parsed[key] == manifests["left"][key]
(ROOT / "CALLERS.toml").write_text(merged)
report["manifest"] = {"before_counts": {side: [len(m["boundary"]), len(m["protected_file"])]
                     for side, m in manifests.items()}, "after_counts": [483, 373],
                     "metadata_unchanged": True, "full_row_multiset": True,
                     "new_boundary_ids": sorted(new_ids), "changed_existing_boundary": final_use,
                     "right_added_protected_rows": [json.loads(row) for row in
                         (counts["right"] - counts["base"]).elements()], **digest(merged)}

# Only the immutable exact Root selection list changes in this workflow.
def root_names(text):
    found = re.search(r"parents = (\[[\s\S]*?\n          \])", text)
    assert found
    return found, ast.literal_eval(found.group(1))
workflows = {side: content(ref, WORKFLOW) for side, ref in REFS.items()}
names = {side: root_names(text)[1] for side, text in workflows.items()}
assert len(names["base"]) == 15 and len(names["left"]) == 16 and len(names["right"]) == 21
issuer_names = [name for name in names["right"] if name not in names["base"]]
assert len(issuer_names) == 6
assert all("::version_issuer::tests::retained_version_issuer_" in name for name in issuer_names)
combined = names["left"] + issuer_names
assert len(combined) == len(set(combined)) == 22
left_match, _ = root_names(workflows["left"])
rhs = "[\n" + "".join("              " + json.dumps(name) + ",\n" for name in combined) + "          ]"
workflow = workflows["left"][:left_match.start(1)] + rhs + workflows["left"][left_match.end(1):]
assert root_names(workflow)[1] == combined
(ROOT / WORKFLOW).write_text(workflow)
report["workflow"] = {"root_names": combined, "added_issuer_names": issuer_names,
                      "only_parents_list_changed_from_left": True, **digest(workflow)}

# Existing Resident methods and negative controls remain. Its exact native
# list accounts for six independently selected issuer cases without treating
# them as Resident source functions or weakening the original ignore checks.
before = (ROOT / QA).read_text()
assert before == content(REFS["left"], QA)
tree = ast.parse(before)
root_node = next(node for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "ROOT_CASES" for t in node.targets))
lines = before.splitlines(keepends=True)
at = sum(map(len, lines[:root_node.end_lineno]))
new_constant = "ROOT_ISSUER_CASES = [\n" + "".join("    " + json.dumps(name) + ",\n" for name in issuer_names) + "]\n"
after = before[:at] + new_constant + before[at:]
old = "        self.assertEqual(len(parents), 7 + len(ROOT_CASES))"
new = ("        self.assertTrue(set(ROOT_ISSUER_CASES).issubset(parents))\n"
       "        self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES))")
assert after.count(old) == 1
after = after.replace(old, new)
expected_functions = functions(before)
actual_functions = functions(after)
assert set(expected_functions) == set(actual_functions)
changed_functions = [name for name in expected_functions if expected_functions[name] != actual_functions[name]]
assert changed_functions == ["ResidentRootSourceClosureTests.test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof"]
assert functions(after.replace(new, old)) == expected_functions
(ROOT / QA).write_text(after)
report["root_inventory_qa"] = {"path": QA, "new_constant": issuer_names,
    "changed_function": changed_functions[0], "all_original_function_bodies_otherwise_preserved": True,
    **digest(after)}

resolved = ["CALLERS.toml", WORKFLOW, QA, *RUST]
subprocess.run(["git", "add", "--", *resolved], cwd=ROOT, check=True)
assert not git("diff", "--name-only", "--diff-filter=U").strip()
subprocess.run(["git", "diff", "--check", "--cached"], cwd=ROOT, check=True)
report["tree"] = git("write-tree").strip()
report["changed_paths"] = git("diff", "--name-only", "--cached", REFS["left"]).splitlines()
report["entries"] = []
for path in report["changed_paths"]:
    mode, blob, stage_path = git("ls-files", "--stage", "--", path).strip().split(maxsplit=2)
    stage, actual_path = stage_path.split("\t", 1)
    assert stage == "0" and actual_path == path
    report["entries"].append({"path": path, "mode": mode, "blob": blob,
                              **digest((ROOT / path).read_text())})
qa_files = sorted((ROOT / "qa/b4-no-bypass").glob("test_*source_closure.py"))
report["source_modules_inventory"] = len(qa_files)
report["source_methods_inventory"] = sum(
    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    for path in qa_files for node in ast.walk(ast.parse(path.read_text())))
assert report["source_methods_inventory"] == 319
(AUDIT / "integration.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({key: value for key, value in report.items()
                  if key in {"refs", "tree", "source_modules_inventory", "source_methods_inventory", "changed_paths", "scope"}}, indent=2))
