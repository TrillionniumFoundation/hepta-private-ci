#!/usr/bin/env python3
"""Prepare CALLERS and scope metadata from an exact isolated overlay.

Only the original source discovery/lexical predicates are loaded. No verify(),
QA method, source gate, Rust executable, formatter, or native command is run.
"""
from pathlib import Path
import ast
import copy
import hashlib
import importlib.util
import json
import re
import sys
import tomllib

sys.dont_write_bytecode = True
R = Path(__file__).resolve().parent
VIEW = R / "view-root86"
INPUTS = R / "SOURCE_VIEW_ROOT86_INPUTS.json"
INSPECTION = R / "OVERLAY_CALL_EDGE_INSPECTION_ROOT86.json"
NEW_BOUNDARIES = R / "NEW_BOUNDARY_PREPARATION_ROOT86.json"
OUT = R / "candidate-registration-root86-v1"

def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def write(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, indent=2) + "\n"
    with path.open("x") as f:
        f.write(text)
    return pin(text.encode())

def toml(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, list):
        return "[" + ", ".join(toml(x) for x in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(k + " = " + toml(v) for k, v in value.items()) + " }"
    if isinstance(value, int):
        return str(value)
    raise TypeError(type(value))

def table(kind, data):
    return "[[" + kind + "]]\n" + "\n".join(k + " = " + toml(v) for k, v in data.items()) + "\n\n"

spec = importlib.util.spec_from_file_location("registration_original_predicates", R / "before/scripts/verify_hepta_callers.py")
PROOF = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = PROOF
spec.loader.exec_module(PROOF)

# Load only the already reviewed pure scope functions, not any QA class/main.
scope_source = (R / "before/qa/b4-no-bypass/test_evaluated_published_read_source_closure.py").read_text()
scope_tree = ast.parse(scope_source)
scope_defs = [n for n in scope_tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("ordinary_")]
scope_namespace = {"PROOF": PROOF, "re": re}
exec(compile(ast.Module(body=scope_defs, type_ignores=[]), "unchanged_ordinary_scope_definitions", "exec"), scope_namespace)
depth_at = scope_namespace["ordinary_depth_at"]
root_containers = scope_namespace["ordinary_root_containers"]
select_scope = scope_namespace["ordinary_select_scope"]

original_bytes = (R / "before/CALLERS.toml").read_bytes()
assert pin(original_bytes)["git_blob"] == "db00e6d39c00e67b2454ee0bba05151aa4e1fac1"
original = tomllib.loads(original_bytes.decode())
inspection = json.loads(INSPECTION.read_text())
new_boundaries = json.loads(NEW_BOUNDARIES.read_text())
inputs = json.loads(INPUTS.read_text())
assert inspection["uncertainties"] == new_boundaries["uncertainties"] == []
assert inspection["old_boundary_removed_in_view"] == []
ignored = tuple(original["ignored_path_fragments"])
raw = {}
for row in inputs["rows"]:
    p = row["path"]
    if not p.endswith(".rs") or PROOF._is_ignored(p, ignored):
        continue
    body = (VIEW / p).read_bytes()
    assert all(pin(body)[key] == row[key] for key in pin(body)), p
    raw[p] = body.decode()
code = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(s)) for p, s in raw.items()}

def type_spans(p):
    result = []
    pattern = r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(struct|enum|trait)\s+(\w+)\b"
    for found in re.finditer(pattern, code[p]):
        start = found.start()
        while code[p][start].isspace():
            start += 1
        if depth_at(code[p], start) != (0, 0, 0):
            continue
        selector = {"kind": "root_type", "item_kind": found.group(1), "name": found.group(2)}
        span = select_scope(PROOF, code[p], selector)
        result.append({**span, "selector": selector})
    return result

def function_spans(p):
    result = []
    containers = root_containers(PROOF, code[p])
    for found in re.finditer(r"\bfn\s+(\w+)\s*(?=[(<])", code[p]):
        start = found.start()
        end = PROOF._rust_item_end(code[p], start)
        assert end is not None, (p, found.group(1))
        if code[p][end] != "}":
            continue  # A trait prototype is protected with its complete trait.
        parents = [x for x in containers if x["opening"] < start and end < x["end"]]
        depth = depth_at(code[p], start)
        if not parents and depth != (0, 0, 0):
            continue  # Named nested functions are contained in their actual parent.
        if parents and (len(parents) != 1 or depth != (1, 0, 0)):
            continue
        result.append({"start": start, "end": end + 1, "name": found.group(1),
                       "owner": parents[0]["header"] if parents else None,
                       "body": code[p][start:end + 1]})
    return result

types = {p: type_spans(p) for p in raw}
functions = {p: function_spans(p) for p in raw}
mounts = {}
for p in raw:
    current = []
    old_text = (R / "before" / p).read_text() if (R / "before" / p).exists() else ""
    for found in re.finditer(r'#\[path\s*=\s*"([^"\n]+\.rs)"\]\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;', raw[p]):
        child = str(Path(p).parent / found.group(1))
        if child not in raw or PROOF._is_ignored(child, ignored):
            continue
        if found.group(0) in old_text:
            continue
        spec = {"parent": p, "child": child, "path_literal": json.dumps(found.group(1)), "module_name": found.group(2)}
        actual = scope_namespace["ordinary_mount_span"](PROOF, code[p], raw[p], spec)
        current.append({**spec, "start": actual["start"], "end": actual["end"], "raw": raw[p][actual["start"]:actual["end"]]})
    mounts[p] = current

candidate = copy.deepcopy(original)
changes_by_id = {x["id"]: x["append"] for x in inspection["old_boundary_additions"]}
old_boundary_report = []
for index, row in enumerate(candidate["boundary"]):
    if row["id"] in changes_by_id:
        before = copy.deepcopy(row)
        row["product_callers"] += changes_by_id[row["id"]]
        old_boundary_report.append({"index": index, "id": row["id"],
                                    "before": before["product_callers"], "after": row["product_callers"]})
candidate["boundary"] += new_boundaries["new_boundaries"]
candidate["privileged_inventory"]["required_boundary_ids"] += [b["id"] for b in new_boundaries["new_boundaries"]]

# Six complete type/trait fences changed shape. Identify the same real type;
# preserve every other old module-order sequence, raw requirement and forbidden.
type_replacements = {
    (267, 0, 0): ("struct", "OriginalCircuitLearningReadClientV1", "pub"),
    (279, 4, 1): ("trait", "NextUseSources", "name"),
    (281, 0, 1): ("struct", "OriginalCircuitNextUseCommandOwnerV1", "kind"),
    (300, 1, 1): ("struct", "OriginalCircuitCompletionReadinessClientV1", "kind"),
    (417, 0, 1): ("enum", "OriginalPredecessors", "kind"),
    (419, 0, 1): ("enum", "OriginalPredecessors", "kind"),
}
protected_report = []
special_predecessor_migration = []
for index, row in enumerate(candidate["protected_file"]):
    p = row["path"]
    if p not in raw or p.endswith("/circuit_evaluated_selection_remote.rs"):
        continue
    before = copy.deepcopy(row)
    for (ri, si, mi), (kind, name, part) in type_replacements.items():
        if ri != index:
            continue
        matches = [x for x in types[p] if x["selector"]["item_kind"] == kind and x["selector"]["name"] == name]
        assert len(matches) == 1, (index, name)
        body = code[p][matches[0]["start"]:matches[0]["end"]]
        if part == "kind":
            body = body[body.index(kind + " "):]
        elif part == "name":
            body = body[body.index(name):]
        old = row["required_order"][si][mi]
        assert old not in code[p], (index, name, "unnecessary migration")
        row["required_order"][si][mi] = body
    for guard in row.get("required_function_order", []):
        function = guard["function"]
        name = function[3:-1]
        exact = [x for x in functions[p] if x["name"] == name]
        assert len(exact) == 1 and code[p].count(function) == 1, (index, function)
        original_scope = (R / "before" / p).read_text()
        original_code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(original_scope))
        start = original_code.index(function)
        end = PROOF._rust_item_end(original_code, start)
        old_body = original_code[start:end + 1]
        new_body = exact[0]["body"]
        if old_body != new_body:
            guard["sequence"] = ["fn ", new_body[3:]]
            if index == 279 and name == "predecessors":
                old_top = list(guard.get("top_level", []))
                expected = ["let selector: &LearningIterationEvidenceClientV1 = source.selector();",
                            "let selection = selector\n            .readback("]
                assert all(x in old_top for x in expected), old_top
                top = [x for x in old_top if x not in expected]
                top.insert(top.index("Ok([training, selection])"), "let selection = match source.selector()")
                guard["top_level"] = top
                special_predecessor_migration.append({"row": index, "function": function,
                    "old_top_level": old_top, "new_top_level": top,
                    "preserved_remote_obligation": "OriginalSelectorRead::Remote delegates to the original typed evidence readback with the same snapshot and Selection prior",
                    "added_local_obligation": "Local checks original opaque S, actual readback, full signature/context and current predecessors; T/E remains before S",
                    "other_extra_guards_removed": []})
    # Existing function/type guards stay intact when their source is unchanged.
    # Append exact new functions and newly added root types to this path's first
    # protected row only; the distinct pre-existing rows are never merged.
    first = next(i for i, x in enumerate(candidate["protected_file"]) if x["path"] == p)
    if first == index:
        for mount in mounts[p]:
            if mount["raw"] not in row["required"]:
                row["required"].append(mount["raw"])
        guarded = {x["function"] for other in candidate["protected_file"] if other["path"] == p
                   for x in other.get("required_function_order", [])}
        old_code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((R / "before" / p).read_text()))
        for f in functions[p]:
            marker = "fn " + f["name"] + "("
            if marker in guarded or code[p].count(marker) != 1:
                continue
            if marker in old_code:
                continue
            row.setdefault("required_function_order", []).append({"function": marker, "sequence": ["fn ", f["body"][3:]]})
            guarded.add(marker)
        for item in types[p]:
            selector = item["selector"]
            pattern = r"\b" + selector["item_kind"] + r"\s+" + re.escape(selector["name"]) + r"\b"
            if re.search(pattern, old_code):
                continue
            body = code[p][item["start"]:item["end"]]
            at = body.index(selector["item_kind"])
            # A complete real declaration is split into two ordered tokens for
            # the unchanged original required_order schema.
            split = at + len(selector["item_kind"]) + 1
            row.setdefault("required_order", []).append([body[:split], body[split:]])
    if row != before:
        protected_report.append({"index": index, "path": p,
                                 "before": before, "after": copy.deepcopy(row),
                                 "forbidden_preserved": before["forbidden"] == row["forbidden"],
                                 "old_raw_required_prefix_preserved": row["required"][:len(before["required"])] == before["required"]})

protected_paths = {row["path"] for row in original["protected_file"]}
new_paths = sorted(p for p in raw if p.startswith("codex-rs/hepta-agentd/src/") and not (R / "before" / p).exists() and p not in protected_paths)
assert all(p.startswith("codex-rs/hepta-agentd/src/") for p in new_paths), new_paths
new_protected = []
common_forbidden = ["SigningKey::generate", "SigningKey::from_bytes", "LearningEvidenceVerifierV1::new",
                    "LearningEvidenceTrustV1", "File::open", "File::create", "UnixStream::connect",
                    "TcpStream::connect", "pub trait OriginalSelectionOwner", "pub(crate) trait OriginalSelectionOwner",
                    "Deref", "into_inner", "permit_all", "if false"]
for p in new_paths:
    row = {"path": p, "required": [], "required_order": [], "required_function_order": [],
           "forbidden": list(common_forbidden)}
    if p.endswith("/root_candidate_stage_handoff.rs"):
        # This new Root handoff intentionally reads the actual /proc boot/start
        # identity in require_process; the whole function and its real literals
        # are fixed below/by QA. No original forbidden array is changed.
        row["forbidden"].remove("File::open")
    row["required"].extend(mount["raw"] for mount in mounts[p])
    for marker in row["forbidden"]:
        pattern = re.escape(marker)
        if marker[0].isalnum() or marker[0] == "_":
            pattern = r"(?<!\w)" + pattern
        if marker[-1].isalnum() or marker[-1] == "_":
            pattern += r"(?!\w)"
        assert re.search(pattern, code[p]) is None, (p, marker)
    for f in functions[p]:
        marker = "fn " + f["name"] + "("
        if code[p].count(marker) == 1:
            row["required_function_order"].append({"function": marker, "sequence": ["fn ", f["body"][3:]]})
    for item in types[p]:
        body = code[p][item["start"]:item["end"]]
        kind = item["selector"]["item_kind"]
        split = body.index(kind) + len(kind) + 1
        row["required_order"].append([body[:split], body[split:]])
    for item in root_containers(PROOF, code[p]):
        body = code[p][item["start"]:item["end"]]
        split = body.index(" ") + 1
        row["required_order"].append([body[:split], body[split:]])
    # Protect module constants (purpose, role order, rights, bounds) in real code.
    for found in re.finditer(r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?const\s+(\w+)\b", code[p]):
        start = found.start()
        while code[p][start].isspace():
            start += 1
        if depth_at(code[p], start) != (0, 0, 0):
            continue
        end = PROOF._rust_item_end(code[p], start)
        body = code[p][start:end + 1]
        split = body.index("const ") + len("const ")
        row["required_order"].append([body[:split], body[split:]])
    candidate["protected_file"].append(row)
    new_protected.append({"index": len(candidate["protected_file"]) - 1, "row": row})

# Preserve every unchanged TOML block byte for byte; old boundary blocks receive
# only their exact product_callers line. Only changed protected rows serialize.
text = original_bytes.decode()
starts = list(re.finditer(r"(?m)^\[\[(boundary|protected_file)\]\]\n", text))
authority_start = text.index("[authority]")
prefix = text[:starts[0].start()]
old_ids = toml(original["privileged_inventory"]["required_boundary_ids"])
new_ids = toml(candidate["privileged_inventory"]["required_boundary_ids"])
assert prefix.count("required_boundary_ids = " + old_ids) == 1
prefix = prefix.replace("required_boundary_ids = " + old_ids, "required_boundary_ids = " + new_ids)
chunks = [prefix]
boundary_index = protected_index = 0
for i, found in enumerate(starts):
    end = starts[i + 1].start() if i + 1 < len(starts) else authority_start
    block = text[found.start():end]
    if found.group(1) == "boundary":
        before = original["boundary"][boundary_index]
        after = candidate["boundary"][boundary_index]
        if before != after:
            old_line = "product_callers = " + toml(before["product_callers"])
            assert block.count(old_line) == 1, before["id"]
            block = block.replace(old_line, "product_callers = " + toml(after["product_callers"]))
        chunks.append(block)
        boundary_index += 1
        if boundary_index == len(original["boundary"]):
            chunks.extend(table("boundary", x) for x in new_boundaries["new_boundaries"])
    else:
        before = original["protected_file"][protected_index]
        after = candidate["protected_file"][protected_index]
        chunks.append(block if before == after else table("protected_file", after))
        protected_index += 1
chunks.extend(table("protected_file", x["row"]) for x in new_protected)
chunks.append(text[authority_start:])
after_text = "".join(chunks)
assert tomllib.loads(after_text) == candidate
assert candidate["authority"] == original["authority"]
assert candidate["protected_file"][411] == original["protected_file"][411]
assert len(candidate["boundary"]) == len(set(b["id"] for b in candidate["boundary"]))

OUT.mkdir()
callers_pin = write("CALLERS.toml", after_text)
write("BOUNDARY_REVIEW.json", {"status": "STATIC_PARTIAL_OVERLAY_PREPARATION_NOT_COMPLETE_GATE", "original_count": len(original["boundary"]),
       "proposed_count": len(candidate["boundary"]), "old_changes": old_boundary_report,
       "new_boundaries": new_boundaries["new_boundaries"], "partial_discovery_uncertainties": [],
       "full_source_scanned": False, "authority": candidate["authority"], "ignored_path_fragments": ignored})
write("PROTECTED_REVIEW.json", {"status": "UNFORMATTED_PROPOSAL_NO_GATE_EXECUTION", "original_count": len(original["protected_file"]),
       "proposed_count": len(candidate["protected_file"]), "old_rows_changed": protected_report,
       "new_rows": new_protected, "type_fence_migrations": [list(k) for k in type_replacements],
       "predecessor_obligation_migration": special_predecessor_migration,
       "all_old_forbidden_arrays_equal": all(a["forbidden"] == b["forbidden"] for a, b in zip(original["protected_file"], candidate["protected_file"])),
       "old_remote_row_411_unchanged": True})
write("SOURCE_SCOPE_INPUTS.json", {"raw": {p: pin(s.encode()) for p, s in raw.items()},
       "types": types, "mounts": mounts,
       "functions": {p: [{k:v for k,v in x.items() if k != "body"} for x in v] for p, v in functions.items()}})
write("BUILD_RESULT.json", {"status": "PREPARED_NOT_QUALIFIED", "callers": callers_pin,
       "old_boundary_changed": len(old_boundary_report), "new_boundaries": len(new_boundaries["new_boundaries"]),
       "old_protected_changed": len(protected_report), "new_protected": len(new_protected),
       "old_protected_unchanged": len(original["protected_file"]) - len(protected_report),
       "product_overlay_paths": len(raw), "complete_source_scans": 0, "qa_methods_executed": 0,
       "rust_executions": 0, "formatter_executions": 0})
print((OUT / "BUILD_RESULT.json").read_text())
