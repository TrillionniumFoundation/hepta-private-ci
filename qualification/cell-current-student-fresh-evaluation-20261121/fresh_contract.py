"""Offline admission and durable budgets for the new single-call E2 scope."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
import xml.etree.ElementTree as ET

MODES = ("document_evidence", "native_feedback")
ARMS = ("frozen", "retrieval", "final_only")
REPOSITORIES = (
    "tartley/colorama", "python-poetry/tomlkit", "andialbrecht/sqlparse",
    "theskumar/python-dotenv", "uiri/toml", "jaraco/inflect",
    "agronholm/exceptiongroup", "jd/tenacity",
)
TRAINING_CANDIDATE = "dc96ad0c29223dc0fbf0e6165854d8e7cf25331c3f77d57ad30c4f30fc6cf678"
POLICY = "manifest_predictor_single_native_chat_4096_384.v1"
AS_OF = "2026-11-21T03:00:00Z"
COMMIT_ORDER = "Git default rev-list traversal; retained exact SHA list is authoritative; no resorting"
CAPS = {"nonmerge_commits_per_repository": 50, "material_attempts_per_repository": 4,
        "material_attempts": 28, "qualification_native_children": 56,
        "generation_slots": 24, "evaluation_native_children": 24,
        "input_tokens": 4096, "output_tokens": 384, "rendered_input_bytes": 131072,
        "blob_bytes": 1024**2, "archive_bytes": 128 * 1024**2, "tree_entries": 20000,
        "git_command_seconds": 600, "clone_depth": 256, "owner_material_bytes": 2 * 1024**3,
        "changed_python_paths_per_commit": 32, "git_commands_per_repository": 2000, "scan_wall_seconds": 1800,
        "generation_wall_seconds": 300, "evaluation_arm_wall_seconds": 2400, "cleanup_grace_seconds": 20}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_bound(binding):
    path = Path(binding["path"])
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024**2,
            "bounded regular receipt required")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == binding["sha256"], "receipt bytes changed")
    return json.loads(raw)


def native_output_guard(record, pair):
    """Bind full native receipts and raw output to the retained actual artifacts."""
    root = Path(record["task_spec_path"]).parent
    mapping = {"STDOUT.txt": "stdout_sha256", "STDERR.txt": "stderr_sha256", "CASE.json": "case_sha256",
               "sandbox-output/junit.xml": "junit_sha256", "sandbox-output/SANDBOX_ATTESTATION.json": "sandbox_attestation_sha256"}
    for side in ("before", "after"):
        folder, receipt = root / (side + "-run"), pair[side]
        require(read_bound({"path": str(folder / "RESULT.json"), "sha256": record["native_result_sha256s"][side]}) == receipt,
                "pair differs from actual native result bytes")
        for relative, key in mapping.items():
            path = folder / relative
            require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024**2
                    and re.fullmatch(r"[0-9a-f]{64}", receipt[key]) and sha(path) == receipt[key],
                    "actual native output/attestation missing or changed: " + relative)
        case = json.loads((folder / "CASE.json").read_bytes())
        attestation = json.loads((folder / "sandbox-output/SANDBOX_ATTESTATION.json").read_bytes())
        cases = list(ET.parse(folder / "sandbox-output/junit.xml").getroot().iter("testcase"))
        measured = {"tests": len(cases), **{key: sum(node.find(tag) is not None for node in cases)
                    for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))},
                    "cases": [{"classname": node.attrib.get("classname", ""), "name": node.attrib["name"],
                               **{tag: None if node.find(tag) is None else node.find(tag).attrib.get("message")
                                  for tag in ("failure", "error")}} for node in cases]}
        require(all(receipt[key] == value for key, value in measured.items()), "native counts/cases differ from actual JUnit")
        expected = record["original_source_sha256" if side == "before" else "original_after_sha256"]
        require(case["project_id"] == record["project_id"] and case["source_path"] == record["source_path"]
                and case["source_sha256"] == expected == receipt["patched_source_sha256"] == attestation["source_sha256"]
                and all(attestation[key] is True for key in ("tests_readonly", "dependencies_readonly", "package_readonly"))
                and attestation["host_canary_visible"] is False and int(attestation["effective_capabilities"], 16) == 0
                and attestation["net_namespace"] != case["host_net_namespace"]
                and attestation["pid_namespace"] != case["host_pid_namespace"]
                and attestation["network_interfaces"] == [[1, "lo"]]
                and attestation["test_files"] == {row["path"]: row["sha256"] for row in case["test_files"]}
                and attestation["root_test_files"] == {row["path"]: row["sha256"] for row in case.get("root_test_files", [])},
                "actual original native attestation differs")
        if case.get("dependency_files"):
            require(attestation["extra_dependencies_readonly"] is True and attestation["extra_dependency_files"]
                    == {row["path"]: row["sha256"] for row in case["dependency_files"]}, "original extra dependency attestation differs")


def write_new(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_selection(selection, weights, excluded, publication):
    require(selection["schema"] == "hepta.current-student-fresh-selection.v1",
            "old future protocols cannot extend this budget")
    require(weights["schema"] == "hepta.current-student-fresh-weights.v1"
            and weights["training_candidate_digest"] == TRAINING_CANDIDATE
            and set(weights["models"]) == set(MODES), "two new child freezes required")
    require(selection["weights_digest"] == digest(weights)
            and selection["excluded_inventory_digest"] == digest(excluded), "selection inputs changed")
    require(selection["repositories"] == list(REPOSITORIES) and selection["caps"] == CAPS and selection["as_of"] == AS_OF
            and selection["commit_order"] == COMMIT_ORDER and selection["request_policy"] == POLICY, "new fixed order or caps changed")
    require(selection["automatic_retry"] is False
            and selection["old_raw_policy_comparable"] is False, "old policy scope cannot be reused")
    require(publication["selection_digest"] == digest(selection)
            and re.fullmatch(r"[0-9a-f]{40}", publication["commit"])
            and 0 < int(weights["created_at_ns"]) < int(publication["published_at_ns"]) <= time.time_ns(),
            "selection must be published after both child weights froze")
    require("jaraco" in excluded["owners"]
            and all(owner == owner.casefold() and owner for owner in excluded["owners"]),
            "canonical owner exclusion inventory required")
    root = Path(selection["owner_root"])
    require(root.is_absolute() and root.name.startswith("e2-fresh-") and ".." not in root.parts,
            "independent fresh owner root required")
    return {repo: ("BEFORE_SCAN_REFUSAL" if repo.split("/")[0].casefold() in excluded["owners"]
                   else "ELIGIBLE_FOR_ORDERED_SCAN") for repo in REPOSITORIES}


def record_guard(record, selection, excluded, publication):
    require(record["schema"] == "hepta.current-student-fresh-task.v1", "new task schema required")
    project = record["project_id"]
    require(project in REPOSITORIES, "unlisted source")
    owner = project.split("/")[0].casefold()
    require(owner not in excluded["owners"] and record["source_group"] == "github-owner:" + owner,
            "old owner/source group rejected")
    metadata = read_bound(record["repository_metadata"])
    require(metadata["full_name"] == project and metadata["owner"]["login"].casefold() == owner
            and type(metadata["id"]) is int and metadata["id"] > 0 and metadata["fork"] is False,
            "canonical nonfork repository metadata required")
    require(record["training_allowed"] is False and record["evaluation_allowed"] is True
            and record["previously_exposed"] is False and record["split"] == "confirmation"
            and record["origin_kind"] == "curated_development", "record authorization/exposure changed")
    require(record["weights_digest"] == selection["weights_digest"]
            and int(publication["published_at_ns"]) < int(record["source_access_started_at_ns"]) <= time.time_ns(),
            "source acquisition predates publication or weight freeze")
    require(int(record["source_access_started_at_ns"]) <= int(record["source_preparation_completed_at_ns"]) <= time.time_ns(),
            "complete material preparation timestamp required")
    path = PurePosixPath(record["source_path"])
    require(not path.is_absolute() and ".." not in path.parts
            and record["allowed_function"].isidentifier(), "unsafe source identity")
    require(all(re.fullmatch(r"[0-9a-f]{40}", record[key])
                for key in ("original_parent", "original_commit")), "original revisions required")
    hashes = {record["original_source_sha256"], record["original_after_sha256"],
              *record["before_after_function_AST_sha256"], *record["test_AST_sha256s"]}
    require(len(record["before_after_function_AST_sha256"]) == 2 and record["test_AST_sha256s"]
            and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
            and not hashes.intersection(excluded["content_sha256s"]), "old content or incomplete fingerprints")
    prompt = record["task"]["input"]
    require(isinstance(prompt, str) and 0 < len(prompt.encode()) <= 65536
            and record["task"]["messages"] == [{"role": "user", "content": prompt}],
            "single original user request required")
    pair = read_bound(record["native_pair"])
    before, after = pair["before"], pair["after"]
    for receipt in (before, after):
        require(type(receipt["actual_wait_returncode"]) is int
                and all(type(receipt[key]) is int and receipt[key] >= 0 for key in ("tests", "failures", "errors", "skipped"))
                and receipt["tests"] > 0 and len(receipt["cases"]) == receipt["tests"]
                and [[row["classname"], row["name"]] for row in receipt["cases"]] == record["expected_cases"],
                "native cases/counts must be complete nonnegative integers in identical original order")
    require(pair["status"] == "ORIGINAL_NATIVE_PAIR_PASSED" and pair["repository"] == project
            and pair["commit"] == record["original_commit"] and pair["parent"] == record["original_parent"]
            and pair["source_path"] == record["source_path"] and pair["function"] == record["allowed_function"]
            and [pair["commit_index"], pair["source_index"]] == record["source_position"]
            and pair["task_spec_sha256"] == record["task_spec_sha256"]
            and before["actual_wait_returncode"] == 1 and before["failures"] > 0
            and before["errors"] == before["skipped"] == 0 and before["timed_out"] is False
            and before["sandbox_attestation_sha256"] and after["success"] is True
            and after["actual_wait_returncode"] == 0 and after["timed_out"] is False
            and after["failures"] == after["errors"] == after["skipped"] == 0
            and after["sandbox_attestation_sha256"] and pair["same_original_case_set"] is True
            and pair["expected_cases"] == record["expected_cases"] and record["expected_cases"],
            "strict unchanged original BEFORE/AFTER cases required")
    native_output_guard(record, pair)
    license_review = read_bound(record["license_review"])
    require(license_review["material_retention_conditions_satisfied"] is True
            and license_review["task_spec_sha256"] == record["task_spec_sha256"]
            and license_review["original_notices"], "retained original license review required")
    for notice in license_review["original_notices"]:
        require(Path(notice["path"]).stat().st_size == notice["bytes"]
                and sha(notice["path"]) == notice["sha256"], "original notice changed")
    return owner, hashes


def panel_guard(panel, selection, excluded, publication):
    require(panel["schema"] == "hepta.current-student-fresh-panel.v1"
            and panel["selection_digest"] == digest(selection) and len(panel["tasks"]) == 4,
            "four newly frozen sources required; no partial replacement panel")
    owners, fingerprints, positions = set(), set(), []
    for record in panel["tasks"]:
        owner, hashes = record_guard(record, selection, excluded, publication)
        require(owner not in owners and not hashes.intersection(fingerprints), "panel source overlap")
        owners.add(owner)
        fingerprints.update(hashes)
        positions.append(REPOSITORIES.index(record["project_id"]))
    require(positions == sorted(set(positions)) and len({x["record_id"] for x in panel["tasks"]}) == 4,
            "source order or record identity differs")
    audit = read_bound(panel["selection_audit"])
    by_id = {record["record_id"]: record for record in panel["tasks"]}
    selected = []
    for index, entry in enumerate(audit["repositories"]):
        require(index < 8 and entry["project_id"] == REPOSITORIES[index], "skipped earlier source group")
        refused = REPOSITORIES[index].split("/")[0].casefold() in excluded["owners"]
        if refused:
            require(entry["status"] == "BEFORE_SCAN_REFUSAL" and not entry["attempts"], "excluded source was scanned")
            continue
        scanned = read_bound(entry["scan"])
        require(scanned["canonical_repository"] == entry["project_id"], "scan belongs to another repository")
        if entry["status"] == "SCAN_FAILED_NO_RETRY":
            require(scanned["status"] == "FAILED_NO_RETRY" and not entry["attempts"], "scan failure lost")
            continue
        schedule = ordered_potentials(scanned)
        attempts = entry["attempts"]
        prior_selections = len(selected)
        require(len(attempts) <= len(schedule), "extra materialization attempt")
        for ordinal, attempt in enumerate(attempts):
            require(attempt["position"] == list(schedule[ordinal]), "candidate qualification order changed")
            receipt = read_bound(attempt["result"])
            if receipt["status"] == "QUALIFIED":
                require(ordinal == len(attempts) - 1 and entry["status"] == "SELECTED", "qualified task skipped")
                chosen = by_id[receipt["record_id"]]
                require(chosen["project_id"] == entry["project_id"] and chosen["source_position"] == attempt["position"]
                        and receipt["task_digest"] == digest(chosen), "qualification receipt belongs to another task")
                selected.append(receipt["record_id"])
            else:
                require(receipt["status"] in ("REFUSED", "FAILED_NO_RETRY"), "unknown qualification terminal")
        if entry["status"] == "SELECTED":
            require(len(selected) == prior_selections + 1, "selected source lacks its qualified receipt")
        else:
            require(entry["status"] == "NO_QUALIFIED_TASK" and len(attempts) == len(schedule), "candidate was skipped")
        require(len(selected) < 4 or index == len(audit["repositories"]) - 1, "scan continued after four selections")
    require(selected == [row["record_id"] for row in panel["tasks"]], "first four qualified source groups required")


def prefix_measure(request, tokenizer, chat):
    prompt = request["task"]["input"]
    messages = chat.inference_messages(prompt, request["task"]["messages"])
    require(len(messages) <= 2 and all(row["role"] == "user" for row in messages), "single-call history required")
    rendered = chat.render_prompt(tokenizer, prompt, messages)
    ids = tokenizer.encode(rendered, add_special_tokens=False, truncation=False)
    require(0 < len(ids) <= 4096 and len(rendered.encode()) <= 131072, "complete input exceeds 4096; no truncation")
    return {"request_digest": digest(request), "input_tokens": len(ids),
            "input_ids_digest": digest(ids), "rendered_input_sha256": hashlib.sha256(rendered.encode()).hexdigest()}


def complete_capacity(request, reference, tokenizer, chat):
    measured = prefix_measure(request, tokenizer, chat)
    task = request["task"]
    example = {"record_id": request["record_id"], "input": task["input"],
               "initial_messages": copy.deepcopy(task["messages"]),
               "segments": [{"role": "assistant", "content": reference, "kind": "final_answer",
                             "actor": "upstream_maintainer", "train": True, "trainable": True}]}
    turns = chat.encode_native_turns(tokenizer, example, 4480)
    require(len(turns) == 1, "one complete reference turn required")
    turn = turns[0]
    prefix, targets = turn["prefix_tokens"], turn["input_ids"][turn["prefix_tokens"]:]
    require(prefix == measured["input_tokens"] and digest(turn["input_ids"][:prefix]) == measured["input_ids_digest"]
            and 0 < len(targets) <= 384 and turn["labels"] == [-100] * prefix + targets,
            "complete native continuation including template terminator must fit 384")
    return {**measured, "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
            "reference_continuation_tokens": len(targets), "reference_token_ids_digest": digest(targets),
            "truncations": 0, "model_calls": 0, "native_children": 0}


class Slots:
    """Linux owner-local claims persist through failures; no automatic retry."""

    def __init__(self, selection, excluded):
        self.selection, self.excluded = selection, excluded
        owner = Path(selection["owner_root"])
        require(owner.is_absolute() and owner.name.startswith("e2-fresh-") and ".." not in owner.parts,
                "independent owner root required before any write")
        self.root = Path(selection["owner_root"]) / "slots"
        self.root.mkdir(parents=True, exist_ok=True)
        identity = {"selection_digest": digest(selection), "excluded_digest": digest(excluded)}
        with (self.root / "OWNER.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "IDENTITY.json"
            if path.exists():
                require(json.loads(path.read_bytes()) == identity, "owner cannot be rebound to another protocol")
            else:
                write_new(path, identity)

    def claim(self, kind, slot, binding):
        limits = {"scan": 7, "material": 28, "qualification_native": 56,
                  "generation": 24, "evaluation_native": 24}
        require(kind in limits and isinstance(slot, (list, tuple)) and slot, "unknown budget or slot")
        if kind in ("generation", "evaluation_native"):
            require(len(slot) == 3 and slot[0] in MODES and slot[1] in ARMS
                    and type(slot[2]) is int and 0 <= slot[2] < 4, "undeclared evaluation slot")
        else:
            require(type(slot[0]) is int and 0 <= slot[0] < 8
                    and REPOSITORIES[slot[0]].split("/")[0].casefold() not in self.excluded["owners"],
                    "source refused before scan")
            size = {"scan": 1, "material": 2, "qualification_native": 3}[kind]
            require(len(slot) == size and (size == 1 or type(slot[1]) is int and 0 <= slot[1] < 4)
                    and (size < 3 or slot[2] in ("before", "after")), "undeclared acquisition slot")
        name = kind + "--" + "--".join(map(str, slot)) + ".json"
        with (self.root / "OWNER.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            require(len(list(self.root.glob(kind + "--*.json"))) < limits[kind], "global budget exhausted")
            if kind == "scan":
                require(all((self.root / f"scan--{index}.json").is_file() for index in range(slot[0])
                            if REPOSITORIES[index].split("/")[0].casefold() not in self.excluded["owners"]),
                        "repository scan order changed")
            if kind == "material":
                require((self.root / f"scan--{slot[0]}.json").is_file(), "material attempt lacks scan claim")
            if kind == "material" and slot[1] > 0:
                require((self.root / f"material--{slot[0]}--{slot[1] - 1}.json").is_file(), "material slot order changed")
            if kind == "qualification_native":
                require((self.root / f"material--{slot[0]}--{slot[1]}.json").is_file(), "native pair lacks material claim")
                if slot[2] == "after":
                    require((self.root / f"qualification_native--{slot[0]}--{slot[1]}--before.json").is_file(),
                            "original BEFORE must precede AFTER")
            if kind == "evaluation_native":
                require((self.root / ("generation--" + "--".join(map(str, slot)) + ".json")).is_file(),
                        "evaluation native lacks generation claim")
            if kind == "generation" and slot[2] > 0:
                require((self.root / f"generation--{slot[0]}--{slot[1]}--{slot[2] - 1}.json").is_file(),
                        "evaluation task order changed")
            write_new(self.root / name, {"kind": kind, "slot": list(slot), "binding": binding,
                      "selection_digest": digest(self.selection), "claimed_at_ns": str(time.time_ns()),
                      "failure_or_timeout_consumes_slot": True, "automatic_retry": False})
        return self.root / name


def ordered_potentials(scanned):
    require(scanned["schema"] == "hepta.current-student-fresh-history.v1"
            and scanned["status"] == "ORDERED_STATIC_SCAN_COMPLETE" and len(scanned["commits"]) <= 50,
            "bounded completed scan required")
    return [(i, j) for i, commit in enumerate(scanned["commits"])
            for j, source in enumerate(commit.get("source_candidates", []))
            if source["status"] == "REQUIRES_QUALIFICATION"][:4]
