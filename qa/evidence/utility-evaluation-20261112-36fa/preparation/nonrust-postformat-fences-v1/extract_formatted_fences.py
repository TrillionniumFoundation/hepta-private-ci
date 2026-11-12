#!/usr/bin/env python3
"""Extract review proposals from a separately approved, actually formatted tree.

This read-only preparation is not source-closure, caller verification, a Rust
test, or deployment qualification. It never edits a repository or adopts new
source bytes. A WAITING contract cannot be executed. Original verifier helpers
are imported only for their source masks and conservative item boundaries.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import traceback

sys.dont_write_bytecode = True
PLAN_SHA256 = "9e83fffb854297f7e70f1b72e9f594c2159c4b81955b64ac2eaeeab669b2eb2d"
PLAN_BLOB = "ffaabdbd254bea8e3d45572c1e8e961625ee5119"
DRIVER_SHA256 = "20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2"
DRIVER_BLOB = "51181866cbbb6e0176aab04117efffa8b6792b31"
SCHEMA = "hepta.utility.postformat-fence-proposals.v1"


class PreconditionRejected(RuntimeError):
    pass


def require(value, reason):
    if not value:
        raise PreconditionRejected(reason)


def identities(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob_sha": hashlib.sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest(),
    }


def read_pinned(path, pin):
    require(path.is_file() and not path.is_symlink(), "regular pinned file: " + str(path))
    raw = path.read_bytes()
    actual = identities(raw)
    for key in ("bytes", "sha256", "git_blob_sha"):
        require(actual[key] == pin[key], "pinned " + key + " differs: " + str(path))
    return raw


def put(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save(path, value):
    put(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def outside(path, root):
    require(path.is_absolute(), "external path must be absolute")
    resolved = path.resolve()
    require(not resolved.is_relative_to(root), "external path lies inside source")
    return resolved


def relative_path(root, relative):
    require(isinstance(relative, str), "relative source path")
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "source path traversal")
    resolved = root / path
    require(resolved.resolve().is_relative_to(root), "source path escapes root")
    require(not resolved.is_symlink(), "source path symlink")
    return resolved


def depth_at(code, end):
    """Delimiter depths in the original literal/comment-masked code."""
    brace = paren = bracket = 0
    for char in code[:end]:
        if char == "{":
            brace += 1
        elif char == "}":
            brace -= 1
        elif char == "(":
            paren += 1
        elif char == ")":
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]":
            bracket -= 1
        require(min(brace, paren, bracket) >= 0, "unbalanced source before scope")
    return brace, paren, bracket


def body_open(code, start, end):
    paren = bracket = 0
    for index in range(start, end + 1):
        char = code[index]
        if char == "(":
            paren += 1
        elif char == ")" and paren:
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]" and bracket:
            bracket -= 1
        elif char == "{" and not (paren or bracket):
            return index
    raise PreconditionRejected("actual body opening required")


def item_end(proof, code, start):
    end = proof._rust_item_end(code, start)
    require(end is not None and end >= start, "complete actual Rust item")
    return end


def root_containers(proof, code):
    found = []
    pattern = (
        r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?"
        r"(?:unsafe\s+)?(?:impl|trait)\b"
    )
    for match in re.finditer(pattern, code):
        start = match.start()
        while start < match.end() and code[start].isspace():
            start += 1
        if depth_at(code, start) != (0, 0, 0):
            continue
        end = item_end(proof, code, start)
        require(code[end] == "}", "actual impl/trait body")
        opening = body_open(code, start, end)
        header = " ".join(code[start:opening].split())
        found.append({"start": start, "end": end + 1, "opening": opening,
                      "header": header})
    return found


def function_location(proof, code, name, lower=0, upper=None):
    upper = len(code) if upper is None else upper
    pattern = r"\bfn\s+" + re.escape(name) + r"\s*(?=[(<])"
    matches = list(re.finditer(pattern, code[lower:upper]))
    require(len(matches) == 1, "unique actual function: " + name)
    start = lower + matches[0].start()
    end = item_end(proof, code, start)
    require(end < upper and code[end] == "}", "bounded function body: " + name)
    return start, end + 1


def select_scope(proof, code, selector):
    kind = selector["kind"]
    if kind == "unique_function":
        start, end = function_location(proof, code, selector["name"])
        parents = [
            item for item in root_containers(proof, code)
            if item["opening"] < start and end <= item["end"]
        ]
        depth = depth_at(code, start)
        if not parents:
            require(depth == (0, 0, 0), "function hidden in non-owner/nested scope")
            owner = None
        else:
            require(len(parents) == 1 and depth == (1, 0, 0),
                    "function must be direct member of one root impl/trait")
            owner = parents[0]["header"]
        return {"start": start, "end": end, "owner": owner, "kind": kind}
    if kind == "root_impl_method":
        parents = [
            item for item in root_containers(proof, code)
            if item["header"] == selector["header"]
        ]
        require(len(parents) == 1, "unique root impl: " + selector["header"])
        parent = parents[0]
        start, end = function_location(
            proof, code, selector["name"], parent["opening"] + 1, parent["end"] - 1
        )
        require(depth_at(code, start) == (1, 0, 0), "direct actual impl method")
        if selector.get("protect_entire_impl", False):
            start, end = parent["start"], parent["end"]
        return {"start": start, "end": end, "owner": parent["header"], "kind": kind}
    if kind == "root_type":
        pattern = (
            r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?"
            + re.escape(selector["item_kind"]) + r"\s+"
            + re.escape(selector["name"]) + r"\b"
        )
        matches = []
        for match in re.finditer(pattern, code):
            start = match.start()
            while start < match.end() and code[start].isspace():
                start += 1
            if depth_at(code, start) == (0, 0, 0):
                matches.append(start)
        require(len(matches) == 1, "unique actual root type: " + selector["name"])
        start = matches[0]
        end = item_end(proof, code, start) + 1
        return {"start": start, "end": end, "owner": None, "kind": kind}
    raise PreconditionRejected("unknown scope selector")


def without_nested_functions(proof, code, scope):
    """The same nested-function exclusion used by original function-order checks."""
    start, end = scope["start"], scope["end"]
    body = code[start:end]
    outer = re.match(r"fn\s+\w+\s*", body)
    require(outer is not None, "literal function scope must begin at fn")
    cursor = outer.end()
    while nested := re.search(r"\bfn\s+(?:r#)?\w+", body[cursor:]):
        nested_start = cursor + nested.start()
        nested_end = item_end(proof, body, nested_start)
        body = (
            body[:nested_start]
            + "".join("\n" if char == "\n" else " "
                      for char in body[nested_start:nested_end + 1])
            + body[nested_end + 1:]
        )
        cursor = nested_end + 1
    return body


def literal_span(proof, code, raw, spec):
    if spec["scope"]["kind"] == "module_constant":
        start, end = 0, len(code)
        scoped_code = code
    else:
        scope = select_scope(proof, code, spec["scope"])
        start, end = scope["start"], scope["end"]
        scoped_code = without_nested_functions(proof, code, scope)
    matches = list(re.finditer(spec["prefix_regex"], scoped_code))
    require(len(matches) == 1, "unique actual protocol expression")
    match = matches[0]
    prefix_start = start + match.start()
    offset = start + match.end()
    if spec["scope"]["kind"] == "module_constant":
        require(depth_at(code, prefix_start) == (0, 0, 0),
                "protocol constant must be at actual module scope")
    literal = re.match(r'\s*(b?"(?:[^"\\]|\\.)*")', raw[offset:end])
    require(literal is not None, "actual literal immediately follows code prefix")
    token_start = offset + literal.start(1)
    token_end = offset + literal.end(1)
    token = literal.group(1)
    require(token == spec["expected_rust_literal"], "actual protocol literal differs")
    require(code[token_start:token_end] == proof._strip_rust_non_code(token),
            "literal must occupy this real masked code expression")
    return {"prefix_start": prefix_start, "start": token_start, "end": token_end,
            "literal": token, "scope": spec["scope"],
            "prefix_regex": spec["prefix_regex"]}


def mount_span(proof, code, raw, spec):
    matches = []
    for prefix in re.finditer(r"#\[\s*path\s*=", code):
        if depth_at(code, prefix.start()) != (0, 0, 0):
            continue
        literal = re.match(r'\s*("(?:[^"\\]|\\.)*")', raw[prefix.end():])
        if literal is None or literal.group(1) != spec["path_literal"]:
            continue
        start_literal = prefix.end() + literal.start(1)
        end_literal = prefix.end() + literal.end(1)
        if code[start_literal:end_literal] != proof._strip_rust_non_code(literal.group(1)):
            continue
        suffix = re.match(
            r"\s*\]\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+"
            + re.escape(spec["module_name"]) + r"\s*;", code[end_literal:]
        )
        if suffix is not None:
            matches.append((prefix.start(), end_literal + suffix.end()))
    require(len(matches) == 1, "actual production module mount: " + spec["child"])
    return {"start": matches[0][0], "end": matches[0][1],
            "child": spec["child"], "module_name": spec["module_name"]}


def original_compatible_proposal(code, selected):
    body = code[selected["start"]:selected["end"]]
    marker = re.match(r"fn [A-Za-z_]\w*\(", body)
    if selected["kind"] == "unique_function" and marker is not None:
        # Whole actual function, not a function name alone. Final review still
        # checks every original top_level/literal_calls/forbidden obligation.
        return {"required_function_order": {
            "function": marker.group(0), "sequence": ["fn ", body[3:]]
        }}
    split = re.match(r"\S+\s+", body)
    require(split is not None, "nonempty rooted item")
    return {"required_order": [[body[:split.end()], body[split.end():]]],
            "supplementary_actual_scope_check_required": True}


def pointer_value(value, pointer):
    require(pointer.startswith("/"), "explicit maintenance JSON pointer")
    for segment in pointer[1:].split("/"):
        key = segment.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--inventory-driver", type=Path, required=True)
    parser.add_argument("--structural-callers", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    require(args.root.is_absolute() and root.is_dir(), "absolute existing source root")
    records = outside(args.records, root)
    records.mkdir(parents=False, exist_ok=False)
    result = {
        "schema": SCHEMA, "status": "unknown_preparation", "source_mutated": None,
        "source_closure": "not_run", "full_caller": "not_run", "rust_tests": "not_run",
        "proposals_are_qualification": False, "actual_formatted_markers_frozen": False,
    }
    driver = None
    before = None
    lease = None
    prior_path = list(sys.path)
    source_read_started = False
    try:
        contract_path = outside(args.contract, root)
        contract_raw = contract_path.read_bytes()
        require(identities(contract_raw)["sha256"] == args.contract_sha256,
                "contract transport hash")
        put(records / "INPUT.json", contract_raw)
        cfg = json.loads(contract_raw)
        result["run_identity"] = cfg.get("run_identity")
        require(cfg.get("status") == "root_reviewed_actual_native_formatted_source",
                "WAITING contract: actual formatted source has not been approved")
        require(re.fullmatch(r"[0-9a-f]{40}", cfg.get("root_review_blob", "")) is not None,
                "exact external root review identity")
        require(cfg["extractor_sha256"] == identities(Path(__file__).read_bytes())["sha256"],
                "frozen extractor")
        plan_path = outside(args.plan, root)
        plan_raw = plan_path.read_bytes()
        require(identities(plan_raw)["sha256"] == PLAN_SHA256
                and identities(plan_raw)["git_blob_sha"] == PLAN_BLOB, "frozen scope plan")
        put(records / "PLAN.json", plan_raw)
        plan = json.loads(plan_raw)
        driver_path = outside(args.inventory_driver, root)
        driver_raw = driver_path.read_bytes()
        require(identities(driver_raw)["sha256"] == DRIVER_SHA256
                and identities(driver_raw)["git_blob_sha"] == DRIVER_BLOB,
                "original complete-inventory driver")
        driver = module_at("hepta_fence_original_inventory_driver", driver_path)
        manifest_path = outside(args.structural_callers, root)
        manifest_raw = read_pinned(manifest_path, plan["structural_callers"])
        put(records / "STRUCTURAL_CALLERS.toml", manifest_raw)
        paths = sorted({row["path"] for row in plan["rows"]})
        require(set(cfg["formatted_source_pins"]) == set(paths),
                "all 46 actual formatted path pins, no subset")
        require(len(plan["rows"]) == 49 and len(paths) == 46, "exact reviewed scope")
        lock_path = outside(Path(cfg["source_lock_path"]), root)
        require(lock_path.is_file() and not lock_path.is_symlink(), "existing native source lock")
        lease = lock_path.open("rb")
        fcntl.flock(lease.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        result["root_review_blob"] = cfg["root_review_blob"]
        maintenance = []
        require(len(cfg["maintenance_records"]) >= 2, "actual maintenance records")
        require({item["phase"] for item in cfg["maintenance_records"]} >= {"fix", "fmt"},
                "actual fix and fmt identities")
        for index, item in enumerate(cfg["maintenance_records"]):
            path = outside(Path(item["path"]), root)
            raw = read_pinned(path, item)
            observed = json.loads(raw)
            exit_value = pointer_value(observed, item["exit_code_pointer"])
            require(type(exit_value) is int and exit_value == 0, "actual maintenance zero exit")
            require(pointer_value(observed, item["timeout_pointer"]) is False,
                    "actual maintenance did not time out")
            checks = item["required_json_values"]
            require(checks and any(value == 0 and not isinstance(value, bool)
                                   for value in checks.values()), "actual zero exit assertion")
            for pointer, expected in checks.items():
                actual_value = pointer_value(observed, pointer)
                require(type(actual_value) is type(expected) and actual_value == expected,
                        "maintenance original JSON differs at " + pointer)
            put(records / ("maintenance-" + str(index) + ".json"), raw)
            maintenance.append({"phase": item["phase"], **identities(raw)})
        result["maintenance_originals"] = maintenance
        source_read_started = True
        before = driver.inventory(root)
        put(records / "SOURCE_BEFORE.json", before)
        before_meta = identities(before)
        require(before_meta == cfg["complete_source_inventory"], "full physical source inventory")
        snapshot = json.loads(before)
        require(snapshot["source"] == cfg["source_identity"], "source identity/status")
        require(all(item.get("stable") is True
                    and item["kind"] in ("file", "symlink", "gitlink_directory")
                    for item in snapshot["files"]), "no missing or unstable inventory entry")
        for pin in (plan["original_verifier"], plan["typed_helper"]):
            read_pinned(relative_path(root, pin["path"]), pin)
        sys.path.insert(0, str(root / "scripts"))
        proof = module_at("hepta_fence_original_proof", root / plan["original_verifier"]["path"])
        require(Path(proof.typed_callers.__file__).resolve()
                == (root / plan["typed_helper"]["path"]).resolve(), "actual pinned typed module")
        data = proof.tomllib.loads(manifest_raw.decode("utf-8"))
        require(proof._string_tuple(data, "source_roots") == ("codex-rs",),
                "unchanged complete source roots")
        require(proof._string_tuple(data, "ignored_path_fragments")
                == ("/tests/", "/examples/", "_tests.rs"), "unchanged product-only ignores")
        require(len(proof._boundary_rows(data)) == 569
                and len(data["protected_file"]) == 412, "reviewed structural CALLERS counts")
        # These are scoped source reads for marker proposals, not a replacement
        # for the original full Rust collector used by qualification and QA.
        sources = {}
        masked = {}
        source_pins = {}
        for relative in paths:
            raw = read_pinned(relative_path(root, relative), cfg["formatted_source_pins"][relative])
            source = raw.decode("utf-8")
            code = proof._strip_cfg_test_items(proof._strip_rust_non_code(source))
            require(len(code) == len(source), "original mask must preserve positions")
            sources[relative], masked[relative] = source, code
            source_pins[relative] = identities(raw)
        proposals = []
        for row in plan["rows"]:
            path = row["path"]
            code, raw = masked[path], sources[path]
            item = {"id": row["id"], "path": path, "source": source_pins[path],
                    "semantic_obligations": row["semantic_obligations"], "scopes": []}
            if row["id"].startswith("existing-"):
                original_row = data["protected_file"][row["index"]]
                require(original_row["path"] == path, "original row index/path")
                item["original_row_unchanged"] = original_row
                item["preserve_forbidden_exactly"] = original_row.get("forbidden", [])
            else:
                item["new_proposed_forbidden"] = row["proposed_forbidden"]
            for selector in row["selectors"]:
                selected = select_scope(proof, code, selector)
                start, end = selected["start"], selected["end"]
                item["scopes"].append({
                    "selector": selector, "actual_span": selected,
                    "actual_raw": raw[start:end],
                    "actual_masked": code[start:end],
                    "marker_proposal": original_compatible_proposal(code, selected),
                    "limits": "Proposal only; preserve old constraints and independently review every transfer.",
                })
            proposals.append(item)
        literal_proposals = []
        for spec in plan["critical_literals"]:
            path = spec["path"]
            literal_proposals.append({
                "path": path, **literal_span(proof, masked[path], sources[path], spec)
            })
        mounts = []
        for spec in plan["module_mounts"]:
            parent = spec["parent"]
            require(spec["child"] in sources, "actual approved module child")
            mounts.append({"parent": parent,
                           **mount_span(proof, masked[parent], sources[parent], spec)})
        proposal = {
            "schema": SCHEMA + ".proposal", "status": "unapplied_proposal_requires_review",
            "source_inventory": before_meta, "source_identity": cfg["source_identity"],
            "source_pins": source_pins, "rows": proposals, "literals": literal_proposals,
            "mounts": mounts, "original_validator_run": False,
            "boundary_membership_run": False, "source_closure_run": False,
        }
        save(records / "PROPOSALS.json", proposal)
        result["proposal"] = identities((records / "PROPOSALS.json").read_bytes())
        result["status"] = "prepared_postformat_proposal_requires_review"
        result["counts"] = {"existing_rows": 39, "new_rows": 10, "source_paths": 46,
                            "critical_literals": 17, "module_mounts": 10}
    except PreconditionRejected as error:
        result["status"] = "rejected_preconditions"
        result["error"] = repr(error)
        save(records / "ERROR.json", {"kind": "precondition", "error": repr(error),
                                      "traceback": traceback.format_exc()})
    except Exception as error:
        result["status"] = "unknown_preparation"
        result["error"] = repr(error)
        save(records / "ERROR.json", {"kind": "unexpected", "error": repr(error),
                                      "traceback": traceback.format_exc()})
    finally:
        if source_read_started and driver is not None:
            try:
                after = driver.inventory(root)
                put(records / "SOURCE_AFTER.json", after)
                result["source_after"] = identities(after)
                result["source_mutated"] = None if before is None else after != before
                if before is None:
                    result["status"] = "unknown_preparation"
                elif after != before:
                    result["status"] = "rejected_source_changed"
            except Exception as error:
                result["after_inventory_error"] = repr(error)
                result["source_mutated"] = None
                result["status"] = "unknown_preparation"
        sys.path[:] = prior_path
        if lease is not None:
            lease.close()
        save(records / "RESULT.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "prepared_postformat_proposal_requires_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
