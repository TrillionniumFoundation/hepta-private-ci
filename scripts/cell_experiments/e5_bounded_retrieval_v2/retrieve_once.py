"""Freeze a partial, exact-byte view. This is not a semantic-closure proof."""

import ast
import copy
import textwrap

from before_index import index_before
from v2_common import POLICY_SHA, canonical, code_identity, policy, require, sha
from v2_legacy import source_units


def unit_view(unit):
    keys = (
        "unit_id",
        "path",
        "qualname",
        "kind",
        "start_line",
        "end_line",
        "text",
        "text_sha256",
    )
    return {k: unit[k] for k in keys}


def render(payload, digest):
    pieces = [
        "Repair the original runtime. Return one JSON array [2, VIEW, edits]. Each edit is "
        "[runtime_ordinal, op, start_line, end_line, replacement]. op=0 replaces original "
        "zero-based lines [start,end); op=1 inserts a complete helper after a visible unit "
        "through unchanged whitespace. All original native tests/fixtures stay unchanged. "
        "Only the complete runtime units shown below are editable. Empty edits means no change.",
        "VIEW " + digest,
        "Source " + payload["source_id"],
        "Original case count "
        + str(payload["case_count"])
        + "; complete verifier bundle retained.",
        "This is a partial retrieved view; omitted dependencies are not claimed semantically closed.",
        "Original before case " + payload["diagnostic"]["case"],
        payload["diagnostic"]["failure"],
    ]
    for item in payload["task_items"]:
        pieces += ["Fixed task " + item["path"] + " " + item["label"], item["text"]]
    for ordinal, unit in enumerate(payload["runtime_units"]):
        pieces += [
            f"Runtime {ordinal} {unit['path']} {unit['qualname']} "
            f"original lines [{unit['start_line']},{unit['end_line']})",
            unit["text"],
        ]
    return "\n".join(pieces)


def select_once(visible):
    indexed = index_before(visible)
    budget = indexed["budget"]
    limits = policy()["packing"]
    primary = indexed["failed"][0]
    payload = {
        "schema": "hepta.e5.before-retrieved-view-payload.v2",
        "source_id": visible["identity"]["source_id"],
        "before_commit": visible["identity"]["before_commit"],
        "visible_identity_sha256": visible["identity_sha256"],
        "cases_sha256": visible["identity"]["cases_sha256"],
        "case_count": len(visible["cases"]),
        "runtime_binding_sha256": indexed["binding"]["binding_sha256"],
        "policy_sha256": POLICY_SHA,
        "code_sha256": code_identity(),
        "tokenizer_freeze_sha256": policy()["exact_tokenizer_required"],
        "diagnostic": {
            "case": primary["classname"] + "::" + primary["name"],
            "failure": primary["failure"],
        },
        "task_items": [],
        "runtime_units": [],
        "opaque_task_boundary": None,
    }
    omissions = []

    def fits(candidate):
        return len(render(candidate, "0" * 64).encode()) <= limits["max_prompt_bytes"]

    def add_task(path, label, raw, mandatory):
        text = raw.decode("utf-8")
        item = {"path": path, "label": label, "text": text, "sha256": sha(raw)}
        if item in payload["task_items"]:
            return
        candidate = copy.deepcopy(payload)
        candidate["task_items"].append(item)
        if fits(candidate):
            payload["task_items"].append(item)
        else:
            require(not mandatory, "mandatory complete task exceeds byte view")
            omissions.append(
                {"task_path": path, "label": label, "reason": "whole item byte cap"}
            )

    test_units, primary_matches = [], []
    name = primary["name"].split("[", 1)[0]
    for path in visible["identity"]["test_paths"]:
        require(path in visible["task"], "original selected test file absent")
        module = path.rsplit(".", 1)[0].replace("/", ".")
        if module not in primary["classname"]:
            continue
        try:
            current = source_units.inventory(path, visible["task"][path])
        except (SyntaxError, UnicodeError, ValueError):
            continue
        test_units += current
        primary_matches += [
            u
            for u in current
            if u["kind"] in ("function", "method")
            and (u["qualname"] == name or u["qualname"].endswith("." + name))
        ]
        budget.check()
    if len(primary_matches) == 1:
        test = primary_matches[0]
        add_task(test["path"], test["qualname"], test["text"].encode(), True)
    else:
        payload["opaque_task_boundary"] = (
            "generated, missing, or ambiguous complete test function"
        )
    scripts = [p for p in indexed["matched_task_paths"] if p.endswith(".py")]
    if scripts:
        add_task(
            scripts[0],
            "complete name-matched task script",
            visible["task"][scripts[0]],
            True,
        )
    require(fits(payload), "mandatory diagnostic/header exceeds byte view")
    by_id = {u["unit_id"]: u for u in indexed["units"]}
    selected = set()
    groups = 0

    def add_group(key, mandatory):
        nonlocal groups
        if key in selected:
            return
        if groups >= limits["max_runtime_groups"]:
            require(not mandatory, "mandatory runtime group count cap")
            omissions.append({"unit_id": key, "reason": "whole group count cap"})
            return
        unit = by_id[key]
        group = [unit]
        path = unit["path"]
        twin = path[:-3] + ".pyx" if path.endswith(".py") else path[:-4] + ".py"
        if twin in visible["runtime"]:
            mates = [
                u
                for u in indexed["units"]
                if u["path"] == twin
                and u["qualname"] == unit["qualname"]
                and u["kind"].removeprefix("cython_")
                == unit["kind"].removeprefix("cython_")
            ]
            require(len(mates) == 1, "coupled complete Python/Cython unit unresolved")
            group += mates
        group = [u for u in group if u["unit_id"] not in selected]
        candidate = copy.deepcopy(payload)
        candidate["runtime_units"] += [unit_view(u) for u in group]
        if (
            groups < limits["max_runtime_groups"]
            and len(candidate["runtime_units"]) <= limits["max_runtime_units"]
            and fits(candidate)
        ):
            payload["runtime_units"] = candidate["runtime_units"]
            selected.update(u["unit_id"] for u in group)
            groups += 1
        else:
            require(
                not mandatory,
                "highest-ranked complete runtime group exceeds view limits",
            )
            omissions.append({"unit_id": key, "reason": "whole group byte/count cap"})

    add_group(indexed["ranking"][0]["unit_id"], True)
    if len(primary_matches) == 1:
        tree = ast.parse(textwrap.dedent(primary_matches[0]["text"]))
        called = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        helpers = sorted(
            [
                u
                for u in test_units
                if u["path"] == primary_matches[0]["path"] and u["qualname"] in called
            ],
            key=lambda u: (u["qualname"], u["start_line"]),
        )
        for unit in helpers[:2]:
            add_task(unit["path"], unit["qualname"], unit["text"].encode(), False)
    data = [p for p in indexed["matched_task_paths"] if not p.endswith(".py")]
    if data:
        add_task(
            data[0],
            "complete name-matched task fixture",
            visible["task"][data[0]],
            False,
        )
    for row in indexed["ranking"][1:]:
        if row["score"] > 0:
            add_group(row["unit_id"], False)
        budget.check()
    digest = sha(canonical(payload))
    prompt = render(payload, digest)
    require(
        fits(payload) and len(prompt.encode()) <= 65536,
        "final native message byte overflow",
    )
    view = {
        "schema": "hepta.e5.before-retrieved-view.v2",
        "payload": payload,
        "view_digest": digest,
        "prompt": prompt,
        "prompt_sha256": sha(prompt.encode()),
    }
    receipt = {
        "view_digest": digest,
        "source_cost": budget.receipt(),
        "ranking": indexed["ranking"],
        "omissions": omissions,
        "query": indexed["query"],
        "mismatch": indexed["mismatch"],
        "fixture_terms": indexed["fixture_terms"],
        "unsupported_task_scripts": indexed["unsupported_task_scripts"],
        "token_admission": None,
        "training_execution_admitted": False,
        "all_original_cases_retained": len(visible["cases"]),
        "semantic_context_complete": False,
    }
    return view, receipt
