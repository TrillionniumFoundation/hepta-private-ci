#!/usr/bin/env python3
"""Prepare a local V11 owner checkpoint from frozen reports and actual receipts.

This program has no network, Git, subprocess, host, test-runner, or publication
operation. It edits explicit JSON value spans so protected V10 values retain
their original UTF-8 bytes. An output is an unpublished owner proposal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


BASE_IDENTITY = {
    "bytes": 134567,
    "sha256": "bac85ca6969f7fe47b75245cb688bbcf995871204e5ad921c327df736aa85b36",
    "git_blob": "2d5f0256776089b386f8e5ebd9d9eefcbfaac5f2",
}
BASE_OWNER_HEAD = "f86dfb058edd6e489671e99baf7643a58e7eed35"
SOURCE_BASE = "96038ccf0660154fac143ba6cbe4be81e00813e8"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REQUIRED_FACTS = {
    "source_v9", "source_v10", "source_v11", "mem_d0f",
    "architecture_d0f", "private_d0f", "native_two_d0f",
    "fence013_isolated", "fence013_d0f", "windows_shard2_d0f",
    "mac_d0f", "blocking_original_d0f",
}
EDITABLE_TOP = {
    "checkpoint_revision", "checkpoint_utc", "date_utc",
    "publication_state", "publication", "open", "actionable_remaining_inputs",
}
ADDED_TOP = {"source_ci_followup_v9_v11", "v11_update_provenance"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def pairs_unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate JSON key: " + key)
        out[key] = value
    return out


def reject_nonfinite(value):
    raise ValueError("nonfinite JSON number: " + value)


DECODER = json.JSONDecoder(object_pairs_hook=pairs_unique, parse_constant=reject_nonfinite)


def decode(raw):
    text = raw.decode("utf-8")
    obj, end = DECODER.raw_decode(text.lstrip())
    require(not text.lstrip()[end:].strip(), "trailing JSON content")
    return obj


def pointer(obj, path):
    require(path == "" or path.startswith("/"), "invalid JSON pointer")
    for part in path.split("/")[1:] if path else []:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(obj, list):
            require(part.isdigit() and str(int(part)) == part, "invalid array index")
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def json_spans(text):
    """Return complete value spans; object/list layout is not reserialized."""
    spans = {}

    def whitespace(i):
        while i < len(text) and text[i] in " \r\n\t":
            i += 1
        return i

    def value(i, path):
        i = whitespace(i)
        start = i
        if text[i] == "{":
            i = whitespace(i + 1)
            seen = set()
            while text[i] != "}":
                key, i = DECODER.raw_decode(text, i)
                require(isinstance(key, str) and key not in seen, "bad object key")
                seen.add(key)
                i = whitespace(i)
                require(text[i] == ":", "missing colon")
                i = whitespace(value(i + 1, path + (key,)))
                if text[i] == "}":
                    break
                require(text[i] == ",", "missing object comma")
                i = whitespace(i + 1)
                require(text[i] != "}", "trailing object comma")
            i += 1
        elif text[i] == "[":
            i = whitespace(i + 1)
            n = 0
            while text[i] != "]":
                i = whitespace(value(i, path + (n,)))
                n += 1
                if text[i] == "]":
                    break
                require(text[i] == ",", "missing array comma")
                i = whitespace(i + 1)
                require(text[i] != "]", "trailing array comma")
            i += 1
        else:
            _, i = DECODER.raw_decode(text, i)
        spans[path] = (start, i)
        return i

    end = value(0, ())
    require(not text[end:].strip(), "trailing content after spans")
    return spans


def raw_at(raw, spans, path):
    a, b = spans[path]
    return raw.decode("utf-8")[a:b].encode("utf-8")


def frozen_json(root, spec):
    require(set(spec) == {"local_path", "bytes", "sha256", "git_blob"}, "bad file descriptor")
    path = Path(spec["local_path"])
    if not path.is_absolute():
        path = root / path
    raw = path.read_bytes()
    require(identity(raw) == {k: spec[k] for k in BASE_IDENTITY}, "file identity mismatch: " + str(path))
    return decode(raw), identity(raw)


def sha(value, label):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{40}", value), "invalid " + label)
    return value


def repository_path(path):
    require(isinstance(path, str), "missing repository path")
    p = PurePosixPath(path)
    require(not p.is_absolute() and ".." not in p.parts and "\\" not in path and str(p) == path,
            "invalid repository path")
    require(path.startswith("qualification/"), "evidence must name its existing qualification path")
    return path


def verify_publication(root, name, spec, pr):
    """Selectors accommodate the actual root receipts' different JSON shapes."""
    require(spec["pr"] == pr and spec["draft"] is True, "wrong publication PR/draft")
    head, tree = sha(spec["head"], name + " head"), sha(spec["tree"], name + " tree")
    if name == "source":
        require(spec["base"] == SOURCE_BASE, "wrong source review base")
    if name == "owner_previous":
        require(head == BASE_OWNER_HEAD, "owner baseline head changed")
    doc, pin = frozen_json(root, spec["receipt"])
    expected = {
        "head": head, "tree": tree, "pr": pr, "draft": True,
        "raw_ref_head": head, "body_equal": True, "update_success": True,
    }
    require(set(spec["receipt_selectors"]) == set(expected), "incomplete actual publication selectors")
    for label, want in expected.items():
        require(pointer(doc, spec["receipt_selectors"][label]) == want,
                name + " actual publication mismatch: " + label)
    return {
        "head": head, "tree": tree, "pr": pr, "draft": True,
        **({"base": SOURCE_BASE} if name == "source" else {}),
        "actual_publication_receipt": {
            **pin, "path_in_this_owner_proposal": repository_path(spec["receipt_repository_path"]),
            "selector_checks": dict(spec["receipt_selectors"]),
        },
        "binding_scope": "Verified against the supplied frozen root publication receipt; no new remote action.",
    }


def facts_from_reports(root, facts, evidence):
    require(facts["schema"] == "mem8.owner-v11.frozen-report-selections.v1", "wrong facts schema")
    rows = facts["records"]
    ids = [r["id"] for r in rows]
    require(len(ids) == len(set(ids)) and REQUIRED_FACTS <= set(ids), "missing/duplicate original facts")
    require(set(evidence["objects"]) == set(ids), "published evidence map must match frozen report IDs")
    output = {}
    completed = []
    for row in rows:
        report, pin = frozen_json(root, row["proof"])
        for path, want in row["expected"].items():
            require(pointer(report, path) == want, row["id"] + " report assertion differs: " + path)
        ref = evidence["objects"][row["id"]]
        require({k: ref[k] for k in BASE_IDENTITY} == pin, row["id"] + " evidence postimage differs")
        require(ref["root_full_readback_verified"] is True, "proof not marked read back by root")
        bound_ref = {
            "commit": evidence["head"], "path": repository_path(ref["path"]), **pin,
            "root_full_readback_verified": True,
        }
        if "archive_member" in ref:
            require(not PurePosixPath(ref["archive_member"]).is_absolute()
                    and ".." not in PurePosixPath(ref["archive_member"]).parts, "unsafe archive member")
            bound_ref["archive_member"] = ref["archive_member"]
            bound_ref["identity_scope"] = "Full extracted member bytes; path names its published archive."
        observed = {key: pointer(report, path) for key, path in row["project"].items()}
        output[row["id"]] = {
            "evidence": bound_ref, "observed": observed, "boundary": row["boundary"],
        }
        if row.get("completed_work"):
            work = row["completed_work"]
            require(work["status"] in {"CLOSED_SOURCE_ONLY", "QUALIFIED_ORIGINAL_SOFTWARE_SCOPE",
                                       "CLOSED_AUDIT_MODE_POLICY_SCOPE"}, "invalid completed-work label")
            completed.append({**work, "report_id": row["id"], "evidence": bound_ref,
                              "adoption_gate_closed": False, "result_transferred_to_new_source": False})
    for version in (9, 10, 11):
        o = output[f"source_v{version}"]["observed"]
        require(o["native_tests_executed"] == o["real_model_requests"] == 0, "source-only scope drift")
        require(o["python_pass"] == 18 and o["original_deadline_seconds"] == 600, "source gate changed")
    return output, completed


def render_values(base_raw, replacements, additions):
    text = base_raw.decode("utf-8")
    spans = json_spans(text)
    edits = []
    for path, obj in replacements.items():
        start, end = spans[path]
        indent = 2 * len(path)
        encoded = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)
        encoded = encoded.replace("\n", "\n" + " " * indent)
        edits.append((start, end, encoded))
    root_end = spans[()][1] - 1
    encoded_additions = json.dumps(additions, ensure_ascii=False, indent=2, allow_nan=False)[1:-1].strip("\n")
    edits.append((root_end, root_end, ",\n" + encoded_additions + "\n"))
    ordered = sorted(edits)
    require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), "overlapping JSON changes")
    for start, end, encoded in reversed(ordered):
        text = text[:start] + encoded + text[end:]
    return text.encode("utf-8")


def invariant_audit(base_raw, result_raw):
    before, after = decode(base_raw), decode(result_raw)
    bs, ns = json_spans(base_raw.decode()), json_spans(result_raw.decode())
    require(set(after) == set(before) | ADDED_TOP, "unexpected top-level keys")
    protected = []
    for key in before:
        if key not in EDITABLE_TOP:
            require(before[key] == after[key], "protected value changed: " + key)
            require(raw_at(base_raw, bs, (key,)) == raw_at(result_raw, ns, (key,)), "protected bytes changed: " + key)
            protected.append({"path": [key], **identity(raw_at(base_raw, bs, (key,)))})
    require(len(before["closed_this_followup"]) == len(after["closed_this_followup"]) == 18, "old closed list changed")
    require(len(after["open"]) == 10, "adoption gate count changed")
    require([r["id"] for r in before["open"]] == [r["id"] for r in after["open"]], "gate order changed")
    for index, row in enumerate(before["open"]):
        path = ("open", index)
        if row["id"] != "HOSTED-CI":
            require(row == after["open"][index] and raw_at(base_raw, bs, path) == raw_at(result_raw, ns, path), "non-CI gate changed")
            protected.append({"path": list(path), **identity(raw_at(base_raw, bs, path))})
        else:
            require(set(after["open"][index]) == set(row), "HOSTED gate keys changed")
            require(row["closure"] == after["open"][index]["closure"], "HOSTED closure changed")
            for key in ("id", "closure"):
                require(raw_at(base_raw, bs, path + (key,)) == raw_at(result_raw, ns, path + (key,)), "HOSTED requirement bytes changed")
    old_intake, new_intake = before["actionable_remaining_inputs"], after["actionable_remaining_inputs"]
    require(set(old_intake) == set(new_intake), "intake keys changed")
    for key in old_intake:
        if key != "gates":
            p = ("actionable_remaining_inputs", key)
            require(raw_at(base_raw, bs, p) == raw_at(result_raw, ns, p), "non-gate intake bytes changed")
    require(len(new_intake["gates"]) == 10, "intake gate count changed")
    for index, row in enumerate(old_intake["gates"]):
        p = ("actionable_remaining_inputs", "gates", index)
        now = new_intake["gates"][index]
        require(set(row) == set(now), "intake item keys changed")
        for key in row:
            if row["gate_id"] != "HOSTED-CI" or key not in {"missing_inputs", "next_step"}:
                require(row[key] == now[key] and raw_at(base_raw, bs, p + (key,)) == raw_at(result_raw, ns, p + (key,)), "protected intake changed")
        if row["gate_id"] != "HOSTED-CI":
            require(raw_at(base_raw, bs, p) == raw_at(result_raw, ns, p), "non-CI intake original bytes changed")
            protected.append({"path": list(p), **identity(raw_at(base_raw, bs, p))})
    require(after["adoption_action"] == "NoUpdate" and after["scientific_acceptance"] == "HOLD"
            and after["production_adoption"] is False, "adoption outcome changed")
    require(after["new_model_requests_this_revision"] == after["new_real_actor_episodes"]
            == after["new_scored_memory_actor_episodes"] == 0, "new model/actor work claimed")
    require(after["logical_provider_turns_admitted"] == 1 and after["physical_provider_requests"] is None,
            "original provider count changed")
    return {
        "status": "PASS_LOCAL_LEDGER_INVARIANTS_ONLY", "baseline": identity(base_raw),
        "candidate": identity(result_raw), "protected_original_value_spans": protected,
        "open_adoption_gates": 10, "original_closed_entries_byte_equal": 18,
        "nine_non_CI_gate_objects_byte_equal": True, "nine_non_CI_intakes_byte_equal": True,
        "HOSTED_CI_closure_and_intake_closure_evidence_byte_equal": True,
        "all_original_other_top_level_values_byte_equal": True,
        "provider_H_unknown_scientific_and_no_update_values_unchanged": True,
        "Git_or_ref_writes": 0, "native_or_model_executions": 0,
    }


def prepare(base_raw, bindings, facts, root):
    require(identity(base_raw) == BASE_IDENTITY, "not the actual 134567-byte V10 baseline")
    before = decode(base_raw)
    require(before["checkpoint_revision"] == 10, "wrong baseline revision")
    require(bindings["schema"] == "mem8.owner-v11.actual-publication-bindings.v1", "wrong binding schema")
    timestamp = datetime.fromisoformat(bindings["checkpoint_utc"].replace("Z", "+00:00"))
    require(timestamp.utcoffset() == timezone.utc.utcoffset(timestamp), "checkpoint must be UTC")
    source = verify_publication(root, "source", bindings["source"], 5935)
    evidence = verify_publication(root, "evidence", bindings["evidence"], 5889)
    previous = verify_publication(root, "owner_previous", bindings["owner_previous"], 5897)
    reports, completed = facts_from_reports(root, facts, bindings["evidence"])
    gate_index = next(i for i, r in enumerate(before["open"]) if r["id"] == "HOSTED-CI")
    intake_index = next(i for i, r in enumerate(before["actionable_remaining_inputs"]["gates"]) if r["gate_id"] == "HOSTED-CI")
    finding = (
        "Original V9, V10 and V11 source-only qualifications passed their unchanged 600-second gates; "
        "each has 18 Python regressions and no native/model execution. The separately bound d0f MEM, "
        "Architecture, Private, two-case native and audit-mode blob-policy results are recorded below "
        "under their own original source and run identities. Original Windows/Mac failures, flakes, "
        "timeouts, cancellations, cached scopes, missing logs and any nonterminal observations remain "
        "explicit. The currently published source is " + source["head"] + "/tree " + source["tree"] +
        "; no older or different-head pass is transferred to it. Audit readiness is not enforcing "
        "protection. The v0.10 unavailable subreason, original provider terminal/physical request count "
        "and H process/write settlement remain unknown. All ten adoption gates remain open."
    )
    replacements = {
        ("checkpoint_revision",): 11,
        ("checkpoint_utc",): timestamp.isoformat(),
        ("date_utc",): timestamp.date().isoformat(),
        ("publication_state",): "PREPARED_UNPUBLISHED_OWNER_CHECKPOINT_REQUIRES_EXPECTED_HEAD_CAS",
        ("publication",): {
            "scope": "Owner PR5897 V11 proposal based on the actual V10 ledger and separately published source/evidence receipts.",
            "activation": "ROOT_EXPECTED_HEAD_CAS_SUCCESS_ONLY",
            "expected_previous_head": previous["head"], "owner_pr": 5897, "draft": True,
            "actual_new_head": "Recorded separately only after successful owner publication; no self-hash or advance publication claim.",
        },
        ("open", gate_index, "finding"): finding,
        ("open", gate_index, "status"): "SOURCE_AND_SELECTED_ORIGINAL_SCOPES_QUALIFIED_HOSTED_CI_AND_ADOPTION_OPEN",
        ("actionable_remaining_inputs", "gates", intake_index, "missing_inputs"): [
            "Accepted existing required CI and its applicable dependencies on the actually published final source "
            + source["head"] + "; exact-head package passes do not establish every required context.",
            "Retained original terminal/source/case/raw/JUnit evidence for incomplete or failed Windows/Mac scopes, "
            "including missing logs and actual cached/retry boundaries; unresolved original outcomes are not replaced.",
        ],
        ("actionable_remaining_inputs", "gates", intake_index, "next_step"):
            "Adjudicate each existing original run from its own exact head and complete evidence. Preserve actual "
            "failed or unexecuted scopes, unchanged security assertions, deadlines and retry limits. A new source "
            "requires its own qualification; source checks and archives do not close scientific or owner gates.",
    }
    additions = {
        "source_ci_followup_v9_v11": {
            "scope": "Additive original software/source qualification evidence; no adoption gate closes.",
            "current_published_source": source, "published_evidence": evidence,
            "supersedes_prior_current_source_labels_without_rewriting_historical_values": True,
            "completed_work": completed, "original_report_facts": reports,
            "all_ten_adoption_gates_remain_open": True,
            "current_source_required_CI_accepted": False,
            "prior_package_or_same_tree_results_transferred_to_new_head": False,
            "new_scored_actor_episodes": 0, "new_real_model_requests": 0,
            "original_provider_and_H_UNKNOWN_states_unchanged": True,
        },
        "v11_update_provenance": {
            "actual_base_owner_publication": previous, "base_blockers": BASE_IDENTITY,
            "nine_non_CI_gate_objects_and_intakes_retained_as_original_UTF8": True,
            "HOSTED_CI_closure_and_original_18_closed_entries_retained_as_original_UTF8": True,
            "all_other_prior_fields_outside_explicit_update_set_retained_as_original_UTF8": True,
            "dynamic_publication_bindings_required_no_predicted_head": True,
            "new_native_or_model_execution_by_generator": 0,
            "owner_publication_not_performed_by_generator": True,
        },
    }
    out = render_values(base_raw, replacements, additions)
    audit = invariant_audit(base_raw, out)
    audit["completed_work_items_added_outside_original_closed_list"] = len(completed)
    audit["facts_references_bound_to_root_published_evidence"] = len(reports)
    audit["actual_publication_receipts_checked"] = [source, evidence, previous]
    return out, audit


def create_only(path, raw):
    with path.open("xb") as out:
        out.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--inspect-baseline", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--facts", type=Path)
    parser.add_argument("--facts-sha256")
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--bindings-sha256")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    raw = args.baseline.read_bytes()
    require(identity(raw) == BASE_IDENTITY, "baseline full bytes do not match V10")
    if args.inspect_baseline:
        before = decode(raw)
        spans = json_spans(raw.decode())
        require(len(before["open"]) == 10 and len(before["closed_this_followup"]) == 18, "baseline shape")
        print(json.dumps({"baseline": identity(raw), "value_spans": len(spans),
                          "original_open_gates": 10, "original_closed_entries": 18,
                          "candidate_written": False, "Git_or_ref_writes": 0}, indent=2))
        return
    require(all([args.root, args.facts, args.facts_sha256, args.bindings,
                 args.bindings_sha256, args.output_dir]), "render requires frozen facts and actual publication bindings")
    facts_raw, bindings_raw = args.facts.read_bytes(), args.bindings.read_bytes()
    require(identity(facts_raw)["sha256"] == args.facts_sha256, "facts changed after review")
    require(identity(bindings_raw)["sha256"] == args.bindings_sha256, "publication bindings changed after review")
    out, audit = prepare(raw, decode(bindings_raw), decode(facts_raw), args.root)
    audit["input_facts"] = identity(facts_raw)
    audit["input_publication_bindings"] = identity(bindings_raw)
    audit["generator"] = identity(Path(__file__).read_bytes())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    create_only(args.output_dir / "BLOCKERS_PROPOSED.json", out)
    create_only(args.output_dir / "LOCAL_INVARIANT_AUDIT.json", (json.dumps(audit, indent=2) + "\n").encode())
    print(json.dumps({"proposal": identity(out), "open_adoption_gates": 10,
                      "publication_performed": False, "output_dir": str(args.output_dir)}, indent=2))


if __name__ == "__main__":
    main()
