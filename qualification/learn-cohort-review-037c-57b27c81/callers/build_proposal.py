"""Merge reviewed row deltas into an isolated proposal, never the central registry."""
from collections import Counter, defaultdict
from copy import deepcopy
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import re
import tomllib


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
INPUTS = HERE / "inputs"
INPUTS.mkdir(exist_ok=True)
BASE_SOURCE = WORKSPACE / "profile-evaluated-version-guards-v4-actual/base/CALLERS.toml"
SOURCE = "a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
BASE_SHA = "d1528f92e274a081dd1c77356a10b5ab2944f00f59eb72ef6b0d9d3e95f20903"
BASE_BLOB = "6eb79688b56aca6306bc500b96f3b10654660196"
SPECS = [
    ("01-candidate-v2", "candidate-evaluated-command-guards-a96-v1/CALLERS_DELTA_PLAN_V2.json", "25da7b8438ee06b1027045613441cfce88a1d214b33ab4a2f0c3f1eaa421f577"),
    ("02-binding-forbidden", "candidate-legacy-qa-migration-a96-v1/BINDING_FORBIDDEN_DELTA.json", "2cbfbf7d15b1137c5697a488093fb5108c98e0e7fcdd69166e312bdac1e59928"),
    ("03-current", "candidate-current-protocol-a96-v1/CALLERS-DELTA.json", "3557f035138daa7566d2fde7d4d883bf4a856011dab8112ee6cba2dd885eabd8"),
    ("04-root-v2", "candidate-root-progress-postread-guards-v2/CALLERS.delta.json", "59b685ca143ed69518c4d7f4ec42e00cd7c8c6d7975a368f5f348b90feeae269"),
    ("05-version-v4", "profile-evaluated-version-guards-v4-actual/CALLERS_DELTA_PLAN.json", "1e0091b8e343cba6444a27406f0b4415fdf77aa5821f704b9527b8d0ac6ac0fd"),
    ("06-training-v3-actual", "training-read-transaction-guards-formatted-v3/CALLERS-DELTA.json", "3a780c5f8846c6cd6c637306ea62e1049a5eb67fe86feedf24daaa6d4c8b42c8"),
]


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def meta(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, "immutable proposal output differs: " + str(path)
    else:
        path.write_bytes(data)


base_bytes = BASE_SOURCE.read_bytes()
assert meta(base_bytes)["sha256"] == BASE_SHA and meta(base_bytes)["blob"] == BASE_BLOB
save(INPUTS / "00-a96-CALLERS.toml", base_bytes)
BASE = tomllib.loads(base_bytes.decode())
assert len(BASE["boundary"]) == 541 and len(BASE["protected_file"]) == 389
manifest = deepcopy(BASE)
input_records = []
plans = []
for label, relative, expected in SPECS:
    path = WORKSPACE / relative
    data = path.read_bytes()
    assert meta(data)["sha256"] == expected, label
    frozen = INPUTS / (label + ".json")
    save(frozen, data)
    input_records.append({"label": label, "original_path": str(path),
                          "frozen_path": str(frozen), **meta(data)})
    plan = json.loads(data)
    if label == "03-current":
        assert plan["source_commit"] == SOURCE
        assert plan["base_callers_git_blob"] == BASE_BLOB
        assert plan["base_callers_sha256"] == BASE_SHA
        normalized = {"protected": plan["protected_rows"], "boundary": [],
                      "new_boundary": plan["new_boundaries"],
                      "inventory": plan["required_boundary_ids_add"]}
    elif label == "06-training-v3-actual":
        assert plan["source"] == SOURCE
        assert plan["base_callers_git_blob"] == BASE_BLOB
        assert plan["base_callers_sha256"] == BASE_SHA
        assert [row["index_in_base"] for row in plan["protected_row_replacements"]] == [215, 285]
        normalized = {
            "protected": [dict(row, base_index=row["index_in_base"]) for row in plan["protected_row_replacements"]] + [
                {"before": None, "after": row} for row in plan["new_protected_rows"]],
            "boundary": plan["boundary_changes"],
            "new_boundary": plan["new_boundaries"], "inventory": plan["required_boundary_ids_add"],
        }
    elif label == "04-root-v2":
        assert plan["base_commit"] == SOURCE and plan["base_blob"] == BASE_BLOB
        normalized = {
            "protected": plan["protected_replacements"] + [
                {"before": None, "after": row} for row in plan["new_protected_files"]],
            "boundary": plan["boundary_replacements"],
            "new_boundary": plan["new_boundaries"], "inventory": plan["inventory_additions"],
        }
    elif label == "02-binding-forbidden":
        assert plan["all_other_registry_data_identical"] is True
        assert len(plan["added_forbidden"]) == 17
        normalized = {"protected": plan["protected_changes"], "boundary": [],
                      "new_boundary": [], "inventory": []}
    else:
        assert plan["source_commit"] == SOURCE
        assert plan["base_manifest"]["sha256"] == BASE_SHA
        normalized = {"protected": plan["protected_changes"],
                      "boundary": [row for row in plan["boundary_changes"] if row["before"] is not None],
                      "new_boundary": [row["after"] for row in plan["boundary_changes"] if row["before"] is None],
                      "inventory": plan["new_inventory_ids"]}
    plans.append((label, normalized))

history = []
conflicts = []
boundary_origin = {row["id"]: "base:" + str(index) for index, row in enumerate(BASE["boundary"])}
protected_origin = ["base:" + str(index) for index in range(len(BASE["protected_file"]))]
boundary_sources = defaultdict(list)
protected_sources = defaultdict(list)
inventory_sources = defaultdict(list)


def conflict(kind, key, layer, **context):
    item = {"kind": kind, "key": key, "layer": layer, **context}
    conflicts.append(item)
    (HERE / "CONFLICTS.json").write_bytes(encoded({"status": "BLOCKED_NO_GUESSED_RESOLUTION", "conflicts": conflicts}))
    raise AssertionError(json.dumps({"kind": kind, "key": key, "layer": layer}))


def ordered_subsequence(before, after):
    cursor = iter(after)
    return all(any(candidate == item for candidate in cursor) for item in before)


def changed_fields(before, after):
    return [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def apply_scalar_changes(current, before, after, excluded, kind, key, layer):
    for field in changed_fields(before, after):
        if field in excluded:
            continue
        expected = before.get(field)
        proposed = after.get(field)
        if current.get(field) not in [expected, proposed]:
            conflict("incompatible field update", key, layer, row_kind=kind, field=field,
                     exact_before=before, current_row=current, proposed_after=after)
        if field in after:
            current[field] = deepcopy(after[field])
        else:
            current.pop(field, None)


for layer, plan in plans:
    for ordinal, change in enumerate(plan["protected"]):
        before = change.get("before")
        after = change["after"]
        path = after["path"]
        if before is None:
            if any(row == after for row in manifest["protected_file"]):
                conflict("duplicate proposed new protected row", path, layer, proposed_after=after)
            index = len(manifest["protected_file"])
            manifest["protected_file"].append(deepcopy(after))
            protected_origin.append("new:" + layer + ":" + str(ordinal))
            exact_before_source = "new row; no original row consumed"
            current_before = None
        else:
            if before["path"] != path:
                conflict("protected path rename", path, layer, exact_before=before, proposed_after=after)
            if "base_index" in change:
                index = change["base_index"]
                if index >= len(BASE["protected_file"]) or BASE["protected_file"][index] != before:
                    conflict("base index does not match exact before", path, layer,
                             base_index=index, exact_before=before)
                exact_before_source = "exact a96 protected row index " + str(index)
            else:
                matches = [index for index, row in enumerate(BASE["protected_file"]) if row == before]
                if len(matches) == 1:
                    index = matches[0]
                    exact_before_source = "exact a96 protected row index " + str(index)
                elif len(matches) > 1:
                    conflict("ambiguous identical original protected rows", path, layer,
                             matching_base_indices=matches, exact_before=before)
                else:
                    matches = [index for index, row in enumerate(manifest["protected_file"]) if row == before]
                    if len(matches) != 1:
                        conflict("sequential protected before mismatch", path, layer,
                                 matching_current_indices=matches, exact_before=before,
                                 current_same_path=[row for row in manifest["protected_file"] if row["path"] == path])
                    index = matches[0]
                    exact_before_source = "exact sequential row produced by prior layer: " + protected_origin[index]
            current = manifest["protected_file"][index]
            current_before = deepcopy(current)
            before_forbidden = before.get("forbidden", [])
            after_forbidden = after.get("forbidden", [])
            if not ordered_subsequence(before_forbidden, after_forbidden):
                conflict("removed forbidden marker", path, layer,
                         removed=sorted(set(before_forbidden) - set(after_forbidden)),
                         exact_before=before, proposed_after=after)
            apply_scalar_changes(current, before, after, {"forbidden"}, "protected", path, layer)
            if "forbidden" in before or "forbidden" in after or "forbidden" in current:
                values = current.setdefault("forbidden", [])
                for marker in after_forbidden:
                    if marker not in before_forbidden and marker not in values:
                        values.append(marker)
            assert ordered_subsequence(before_forbidden, current.get("forbidden", []))
        protected_sources[index].append(layer)
        history.append({"kind": "protected", "key": path, "index": index,
                        "identity": protected_origin[index], "layer": layer,
                        "exact_before_source": exact_before_source,
                        "delta_before": before, "current_before": current_before,
                        "proposed_after": after,
                        "merged_after": deepcopy(manifest["protected_file"][index]),
                        "resolution": "exact non-forbidden migration plus append-only forbidden union"})

    for change in plan["boundary"]:
        before = change["before"]
        after = change["after"]
        key = after["id"]
        if before["id"] != key:
            conflict("boundary id rename", key, layer, exact_before=before, proposed_after=after)
        original = [row for row in BASE["boundary"] if row["id"] == key]
        current_rows = [row for row in manifest["boundary"] if row["id"] == key]
        if len(current_rows) != 1:
            conflict("boundary not unique", key, layer, matches=current_rows)
        current = current_rows[0]
        if len(original) == 1 and original[0] == before:
            exact_before_source = "exact a96 boundary " + key
        elif current == before:
            exact_before_source = "exact sequential boundary from prior layer"
        else:
            conflict("boundary before mismatch", key, layer, exact_before=before,
                     original=original, current_row=current, proposed_after=after)
        current_before = deepcopy(current)
        apply_scalar_changes(current, before, after, {"product_callers"}, "boundary", key, layer)
        old_callers = before["product_callers"]
        new_callers = after["product_callers"]
        added = [value for value in new_callers if value not in old_callers]
        removed = [value for value in old_callers if value not in new_callers]
        callers = [value for value in current["product_callers"] if value not in removed]
        for value in added:
            if value not in callers:
                callers.append(value)
        current["product_callers"] = callers
        boundary_sources[key].append(layer)
        history.append({"kind": "boundary", "key": key, "layer": layer,
                        "exact_before_source": exact_before_source,
                        "delta_before": before, "current_before": current_before,
                        "proposed_after": after, "merged_after": deepcopy(current),
                        "caller_additions": added, "caller_removals": removed,
                        "resolution": "apply exact definition migration; merge only caller additions/removals relative to exact delta before"})

    for ordinal, row in enumerate(plan["new_boundary"]):
        key = row["id"]
        if any(current["id"] == key for current in manifest["boundary"]):
            conflict("new boundary id collision", key, layer, proposed_after=row)
        manifest["boundary"].append(deepcopy(row))
        boundary_origin[key] = "new:" + layer + ":" + str(ordinal)
        boundary_sources[key].append(layer)
        history.append({"kind": "boundary", "key": key, "layer": layer,
                        "exact_before_source": "new boundary", "delta_before": None,
                        "current_before": None, "proposed_after": row,
                        "merged_after": deepcopy(row), "resolution": "append exact new row"})
    for key in plan["inventory"]:
        if not any(row["id"] == key for row in manifest["boundary"]):
            conflict("inventory id lacks actual boundary", key, layer)
        if key not in manifest["privileged_inventory"]["required_boundary_ids"]:
            manifest["privileged_inventory"]["required_boundary_ids"].append(key)
        inventory_sources[key].append(layer)


def independent_expected_callers():
    expected = {row["id"]: list(row["product_callers"]) for row in BASE["boundary"]}
    for _layer, plan in plans:
        for change in plan["boundary"]:
            before, after = change["before"], change["after"]
            removed = set(before["product_callers"]) - set(after["product_callers"])
            added = [path for path in after["product_callers"] if path not in before["product_callers"]]
            expected[after["id"]] = [path for path in expected[after["id"]] if path not in removed]
            expected[after["id"]].extend(path for path in added if path not in expected[after["id"]])
        for row in plan["new_boundary"]:
            assert row["id"] not in expected
            expected[row["id"]] = list(row["product_callers"])
    return expected


EXPECTED_CALLERS = independent_expected_callers()
EXPECTED_FINAL_PROTECTED = deepcopy(manifest["protected_file"])
EXPECTED_FINAL_NONCALLER = {row["id"]: {key: value for key, value in row.items() if key != "product_callers"}
                           for row in manifest["boundary"]}
EXPECTED_INVENTORY = list(manifest["privileged_inventory"]["required_boundary_ids"])


def verify(value):
    assert set(value) == set(BASE), "registry top-level shape"
    for key in BASE:
        if key not in {"boundary", "protected_file", "privileged_inventory"}:
            assert value[key] == BASE[key], "unchanged scanner/authority/top-level field: " + key
    for key in BASE["privileged_inventory"]:
        if key != "required_boundary_ids":
            assert value["privileged_inventory"][key] == BASE["privileged_inventory"][key]
    assert value["privileged_inventory"]["required_boundary_ids"] == EXPECTED_INVENTORY
    assert len(EXPECTED_INVENTORY) == len(set(EXPECTED_INVENTORY))
    assert EXPECTED_INVENTORY[:len(BASE["privileged_inventory"]["required_boundary_ids"])] == BASE["privileged_inventory"]["required_boundary_ids"]
    actual = {row["id"]: row for row in value["boundary"]}
    assert len(actual) == len(value["boundary"]) == len(EXPECTED_CALLERS)
    assert set(actual) == set(EXPECTED_CALLERS)
    for key, expected in EXPECTED_CALLERS.items():
        assert actual[key]["product_callers"] == expected, "exact closed caller set: " + key
        assert len(expected) == len(set(expected)), "duplicate product caller"
        assert {field: data for field, data in actual[key].items() if field != "product_callers"} == EXPECTED_FINAL_NONCALLER[key]
    assert value["protected_file"] == EXPECTED_FINAL_PROTECTED, "exact row identity/order and migrated guards"
    assert len(value["protected_file"]) >= len(BASE["protected_file"])
    for index, before in enumerate(BASE["protected_file"]):
        after = value["protected_file"][index]
        assert after["path"] == before["path"]
        assert ordered_subsequence(before.get("forbidden", []), after.get("forbidden", [])), "old forbidden order and multiplicity preserved"


verify(manifest)
mutation_results = []
for name in ["extra_unregistered_caller", "dropped_old_forbidden", "deleted_duplicate_protected_row", "changed_authority", "dropped_inventory_id"]:
    changed = deepcopy(manifest)
    if name == "extra_unregistered_caller":
        changed["boundary"][0]["product_callers"].append("codex-rs/hepta-agentd/src/unregistered_merge.rs")
    elif name == "dropped_old_forbidden":
        index = next(i for i, row in enumerate(BASE["protected_file"]) if row.get("forbidden"))
        changed["protected_file"][index]["forbidden"].remove(BASE["protected_file"][index]["forbidden"][0])
    elif name == "deleted_duplicate_protected_row":
        counts = Counter(row["path"] for row in BASE["protected_file"])
        index = next(i for i, row in enumerate(BASE["protected_file"]) if counts[row["path"]] > 1)
        del changed["protected_file"][index]
    elif name == "changed_authority":
        key = next(iter(changed["authority"]))
        changed["authority"][key] = not changed["authority"][key]
    else:
        changed["privileged_inventory"]["required_boundary_ids"].pop()
    try:
        verify(changed)
    except AssertionError as error:
        mutation_results.append({"mutation": name, "status": "REJECTED", "reason": str(error)})
    else:
        raise AssertionError("unsafe merge mutation accepted: " + name)


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(key + " = " + toml_value(item) for key, item in value.items()) + " }"
    return str(value)


def render_row(kind, row):
    return "[[" + kind + "]]\n" + "\n".join(key + " = " + toml_value(value) for key, value in row.items()) + "\n\n"


# Preserve every untouched original table block byte-for-byte. Only changed
# rows and the inventory table are serialized. Original array-table sections
# interleave, so append each kind's new rows exactly once, after all originals.
original_text = base_bytes.decode()
markers = list(re.finditer(r"(?m)^\[\[(boundary|protected_file)\]\]\s*$", original_text))
assert len(markers) == len(BASE["boundary"]) + len(BASE["protected_file"])
prefix = original_text[:markers[0].start()]
inventory = re.search(r"(?ms)^\[privileged_inventory\]\s*\n.*?(?=^\[|\Z)", prefix)
assert inventory is not None
inventory_text = "[privileged_inventory]\n" + "\n".join(
    key + " = " + toml_value(value) for key, value in manifest["privileged_inventory"].items()
) + "\n\n"
prefix = prefix[:inventory.start()] + inventory_text + prefix[inventory.end():]
pieces = [prefix]
indices = {"boundary": 0, "protected_file": 0}
unchanged_blocks = 0
for position, marker in enumerate(markers):
    kind = marker.group(1)
    index = indices[kind]
    indices[kind] += 1
    end = markers[position + 1].start() if position + 1 < len(markers) else len(original_text)
    if BASE[kind][index] == manifest[kind][index]:
        pieces.append(original_text[marker.start():end])
        unchanged_blocks += 1
    else:
        pieces.append(render_row(kind, manifest[kind][index]))
for kind in ("boundary", "protected_file"):
    for row in manifest[kind][len(BASE[kind]):]:
        pieces.append(render_row(kind, row))
proposal = ("".join(pieces).rstrip("\n") + "\n").encode()
parsed = tomllib.loads(proposal.decode())
if parsed != manifest:
    attempted = HERE / "attempt-01"
    attempted.mkdir(exist_ok=True)
    attempted_report = {
        "status": "FAILED_SERIALIZATION_ONLY_NOT_A_SOURCE_GATE",
        "expected_counts": {key: len(manifest[key]) for key in ("boundary", "protected_file")},
        "actual_counts": {key: len(parsed[key]) for key in ("boundary", "protected_file")},
        "different_top_level_fields": [key for key in sorted(parsed.keys() | manifest.keys()) if parsed.get(key) != manifest.get(key)],
        "candidate_bytes": meta(proposal),
        "reason": "original a96 array-table sections interleave; appending at every kind transition duplicates new rows",
        "central_registry_written": False,
    }
    save(attempted / "serialization-candidate.toml.gz", gzip.compress(proposal, mtime=0))
    save(attempted / "FAILED_SERIALIZATION.json", encoded(attempted_report))
    print(json.dumps(attempted_report, indent=2))
assert parsed == manifest
verify(parsed)
save(HERE / "CALLERS.proposal.toml", proposal)
patch = "".join(difflib.unified_diff(original_text.splitlines(True), proposal.decode().splitlines(True),
                                   fromfile="a/CALLERS.toml", tofile="b/CALLERS.toml")).encode()
save(HERE / "CALLERS.proposal.patch", patch)

duplicates = defaultdict(list)
for index, row in enumerate(BASE["protected_file"]):
    duplicates[row["path"]].append(index)
duplicate_rows = [{"path": path, "original_indices": indices,
                   "final_indices": indices,
                   "original_row_sha256": [meta(canonical(BASE["protected_file"][i]))["sha256"] for i in indices],
                   "final_row_sha256": [meta(canonical(manifest["protected_file"][i]))["sha256"] for i in indices]}
                  for path, indices in duplicates.items() if len(indices) > 1]
row_provenance = {
    "boundary": [{"id": row["id"], "identity": boundary_origin[row["id"]],
                  "layers": boundary_sources[row["id"]], "final_row": meta(canonical(row))}
                 for row in manifest["boundary"]],
    "protected": [{"index": index, "path": row["path"], "identity": protected_origin[index],
                   "layers": protected_sources[index], "final_row": meta(canonical(row))}
                  for index, row in enumerate(manifest["protected_file"])],
    "inventory_additions": [{"id": key, "layers": layers} for key, layers in inventory_sources.items()],
}
history_bytes = encoded({"row_history": history})
save(HERE / "ROW_HISTORY.json.gz", gzip.compress(history_bytes, mtime=0))
save(HERE / "ROW_PROVENANCE.json", encoded(row_provenance))
save(HERE / "INPUTS.json", encoded({"base_original": {"original_path": str(BASE_SOURCE), **meta(base_bytes)}, "deltas": input_records}))
save(HERE / "CONFLICTS.json", encoded({"status": "NO_UNRESOLVED_CONFLICT", "conflicts": [],
                                     "caller_overlap_resolutions": [
                                         {"id": key, "layers": layers,
                                          "resolution": "relative-before additions/removals merged in fixed layer order"}
                                         for key, layers in boundary_sources.items() if len(layers) > 1],
                                     "sequential_forbidden_resolution": "Candidate's exact new binding row receives the 17-marker append-only delta"}))
proof = {
    "status": "ISOLATED_PROPOSAL_MERGE_PROOF_PASS",
    "source_commit": SOURCE, "base": meta(base_bytes),
    "source_scope": "exact Candidate V2 + binding forbidden17 + original Current72732 + Root guards V2 + actual Version V4 markers + actual T47147; actual V4/Root3/T postimages available, source QA recorded separately",
    "layer_order": [label for label, _ in plans],
    "before_counts": {"boundaries": len(BASE["boundary"]), "protected": len(BASE["protected_file"])},
    "after_counts": {"boundaries": len(manifest["boundary"]), "protected": len(manifest["protected_file"])},
    "proposal": meta(proposal), "patch": meta(patch),
    "history_uncompressed": meta(history_bytes), "history_compressed": meta((HERE / "ROW_HISTORY.json.gz").read_bytes()),
    "row_provenance": meta((HERE / "ROW_PROVENANCE.json").read_bytes()),
    "exact_before_matches": len(history),
    "untouched_original_table_blocks_preserved_verbatim": unchanged_blocks,
    "original_duplicate_protected_paths": duplicate_rows,
    "all_old_forbidden_markers_retained_by_original_row_index": True,
    "old_forbidden_order_and_multiplicity_preserved": True,
    "all_other_top_level_registry_data_identical": True,
    "toml_roundtrip_parsed_equal": True,
    "independent_closed_caller_recalculation_matches": True,
    "merge_integrity_mutations": mutation_results,
    "unresolved_conflicts": 0,
    "central_registry_written": False,
    "allowlist_written": False,
    "source_verifier_changed": False,
    "T_v3_included": True,
    "Version_actual_format_marker_transition": {"path": "profile-evaluated-version-guards-v4-actual/evidence/GUARD_ACTUAL_FORMAT_TRANSITION.json", "sha256": "cb7139785685ec73d207a249cc776f17a5e3cf78cf7a94aa20cdf08740f9a50e"},
    "previous_v1_unchanged": True,
    "v1_eof_fix": "serialize one terminal LF; original strict whitespace failure retained in v1",
    "source_qa": "NOT_RUN_BY_THIS_MERGE",
    "native": "UNRUN", "ordinary_qualification": 0,
    "root_adoption": "REQUIRES_ROOT_REVIEW; this is not the central registry",
}
save(HERE / "MERGE_PROOF.json", encoded(proof))
print(json.dumps({key: proof[key] for key in ["status", "before_counts", "after_counts", "proposal", "patch", "exact_before_matches", "untouched_original_table_blocks_preserved_verbatim", "unresolved_conflicts", "central_registry_written", "allowlist_written"]}, indent=2))
