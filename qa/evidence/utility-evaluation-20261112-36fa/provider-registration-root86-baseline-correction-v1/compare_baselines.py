"""Pure AST/text comparison; never imports or executes QA modules."""
import ast
import hashlib
import json
from pathlib import Path
import difflib

SOURCE = Path("/tmp/hepta-36fa-provider-registration-rebuilt-v3")
OUT = Path("/tmp/hepta-36fa-registration-baseline-correction-v1")
OUT.mkdir(exist_ok=True)
def identity(raw):
    return {"bytes": len(raw), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), "sha256": hashlib.sha256(raw).hexdigest()}
def methods(path):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    rows = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            assert node.name not in rows
            start = min([node.lineno] + [x.lineno for x in node.decorator_list])
            rows[node.name] = "".join(lines[start-1:node.end_lineno])
    return rows
paths = sorted((SOURCE/"before/qa/b4-no-bypass").glob("test_*.py"))
assert len(paths) == 63
views = ["before", "view-root86", "candidate-registration-root86-final"]
maps = []
for view in views:
    rows = {}
    for p in paths:
        rel = p.relative_to(SOURCE/"before")
        candidate = SOURCE/view/rel
        if not candidate.exists():
            candidate = p
        for name, body in methods(candidate).items():
            rows[str(rel)+"::"+name] = body
    maps.append(rows)
assert all(set(x) == set(maps[0]) for x in maps)
assert len(maps[0]) == 590
comparisons = []
for i,j in [(0,1),(1,2),(0,2)]:
    changed = [k for k in sorted(maps[i]) if maps[i][k] != maps[j][k]]
    comparisons.append({"before":views[i], "after":views[j], "existing_methods":590, "byte_identical":590-len(changed), "changed":len(changed), "changed_methods":changed, "added":0, "deleted":0})
assert [r["changed"] for r in comparisons] == [1,3,4]
key = "qa/b4-no-bypass/test_resident_root_source_closure.py::test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof"
assert maps[0][key] != maps[1][key] == maps[2][key]
diff = "".join(difflib.unified_diff(maps[0][key].splitlines(True), maps[1][key].splitlines(True), fromfile="cc57/"+key, tofile="Root86/"+key))
report = {
    "format":"hepta-static-qa-baseline-clarification-v1",
    "status":"CORRECTION_OF_DESCRIPTION_ONLY",
    "canonical_commit":"cc57c7198db6293ccca562253c42fffbe2a04633",
    "frozen_source_packet":"fab488b846bb1b1ef7a42b9b30be5773054e1a6a",
    "frozen_main_placement":"a88a0a4ca78021bcd9f15706ffc1baf01bc9b2d8",
    "unchanged_original_addendum":"527c4fdd3d439d614103faca3c2956ceb89e6d59",
    "corrected_field":"later_prepared_preimage_exception.reason",
    "withdrawn_sentence":"Root86 already prepared test inventory; original method bodies unchanged by that earlier layer",
    "correction":"Root86 already changed one existing Root CI-selection method to read the provider/lifecycle modules and count their registered Root cases. The registration increment preserves that prepared method verbatim. Its 587 unchanged plus 3 changed statistic is relative to the Root86 preimage, not canonical cc57. Relative to cc57 there are 586 unchanged plus 4 changed existing methods.",
    "comparisons":comparisons,
    "prepared_root_method_pins":[{"view":v,**identity((SOURCE/v/"qa/b4-no-bypass/test_resident_root_source_closure.py").read_bytes())} for v in views],
    "earlier_layer_change":"Adds the actual provider and lifecycle mounts and corresponding source selection/counting while retaining the existing assertions. This note records the earlier prepared change, and does not newly approve or execute it.",
    "scope":"Static bytes and AST only; no QA module import, QA method, gate, Rust command, H operation, source modification or ref update.",
    "main_packet_and_original_addendum_unchanged":True,
    "diff_identity":identity(diff.encode())
}
for name, raw in [("EARLIER_ROOT_METHOD.diff",diff.encode()),("REVIEW.json",(json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode())]:
    with (OUT/name).open("xb") as f:
        f.write(raw)
print(json.dumps({"comparisons":comparisons,"review":identity((OUT/"REVIEW.json").read_bytes()),"diff":identity(diff.encode())},indent=2))
