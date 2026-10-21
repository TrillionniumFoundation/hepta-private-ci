"""Build separately labeled controlled-event projections of original Git bytes.

The emitted event JSON is a derived representation, never an original Git
object or a natural-language project fact. Logical revisions are the two
declared snapshots of one captured first-parent pair. A mode is a fixed,
read-only object-type predicate, not repository-supplied executable code.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from capture_git_objects import object_sha, sha256, write
from event_projection import PROFILE, EventProjection
from native import Document

PRECOMMIT_SHA = "3cecc183f44a89060c4575dd379c05c9b11675cb7a1d26e8e34bf014ce402d39"
KINDS = ("new_fact", "correction", "composition", "procedure")
SCHEMA = "hepta.external-git-event-projection.v1"


def regular(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("bounded regular source artifact required")
    return path.read_bytes()


def load_receipt(path):
    raw = regular(path)
    receipt = json.loads(raw)
    if (receipt["schema"] != "hepta.external-git-event-source.v1"
            or receipt["status"] != "original_bytes_and_probe_verified"):
        raise ValueError("original byte capture is incomplete")
    entry = receipt["entry"]
    objects = {}
    for info in receipt["original_objects"] + receipt["root_license_objects"]:
        filename = info["filename"]
        if Path(filename).name != filename:
            raise ValueError("source path escape")
        data = regular(path.parent / filename)
        kind = info.get("kind", "blob")
        if (len(data) != info["bytes"] or sha256(data) != info["sha256"]
                or object_sha(kind, data) != info["git_sha1"]):
            raise ValueError("original source byte identity drift")
        objects[info.get("label", "license:" + info.get("path", ""))] = (info, data)
    if not receipt["root_license_objects"]:
        raise ValueError("source license bytes missing")
    for prefix in ("previous", "current"):
        info, data = objects[prefix + "-commit"]
        if info["git_sha1"] != entry[prefix + "_sha"]:
            raise ValueError("commit identity mismatch")
        if not data.startswith(("tree " + entry[prefix + "_tree"] + "\n").encode()):
            raise ValueError("tree header binding mismatch")
        if objects[prefix + "-tree"][0]["git_sha1"] != entry[prefix + "_tree"]:
            raise ValueError("root tree mismatch")
        committer = re.search(rb"(?m)^committer .+ ([0-9]+) ([+-][0-9]{4})$",
                              data.split(b"\n\n", 1)[0])
        if committer is None:
            raise ValueError("original committer timestamp missing")
        actual_date = datetime.fromtimestamp(int(committer[1]), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if actual_date != entry[prefix + "_date"]:
            raise ValueError("API committer date differs from original Git header")
    current = objects["current-commit"][1]
    first_parent = re.search(rb"(?m)^parent ([0-9a-f]{40})\n", current.split(b"\n\n", 1)[0] + b"\n")
    if first_parent is None or first_parent[1].decode() != entry["previous_sha"]:
        raise ValueError("original first-parent relation mismatch")
    commands_raw = regular(path.parent / "commands.json")
    commands = json.loads(commands_raw)
    probes = {}
    for variant, identifier, expected in (
        ("tree", entry["current_tree"], b"tree\n"),
        ("commit", entry["current_sha"], b"commit\n"),
    ):
        matches = [(i, c) for i, c in enumerate(commands)
                   if c["argv"][-3:] == ["cat-file", "-t", identifier]]
        if len(matches) != 1:
            raise ValueError("unique original read-only probe required")
        index, command = matches[0]
        if command["returncode"] != 0 or base64.b64decode(command["stdout_base64"], validate=True) != expected:
            raise ValueError("actual object-type probe mismatch")
        probes[variant] = dict(command_index=index, commands_sha256=sha256(commands_raw),
                               object=identifier, actual_stdout=expected.decode(),
                               required_stdout="tree\n", predicate_success=variant == "tree")
    return receipt, objects, probes, first_parent.span(1), sha256(raw)


def verify_admission(admission_path, pairs_path, calibration_path, receipt_paths):
    """Bind the selector's exact ordered admission, not merely any sorted eight."""
    admission_raw, pairs_raw, calibration_raw = [regular(p) for p in
        (admission_path, pairs_path, calibration_path)]
    admission, pairs, calibration = [json.loads(raw) for raw in
        (admission_raw, pairs_raw, calibration_raw)]
    entries = pairs["entries"]
    if (admission["schema"] != "hepta.external-git-event.prospective-admission.v1"
            or admission["precommit_sha256"] != PRECOMMIT_SHA
            or admission["complete"] is not True or admission["admitted_sources"] != 8
            or admission["planned_sources"] != 8 or len(entries) != 8 or len(receipt_paths) != 8
            or admission["selected_pairs_sha256"] != sha256(pairs_raw)
            or admission["calibration_collection_sha256"] != sha256(calibration_raw)
            or admission["windows_extended"] is not False or admission["source_replacements"] is not False
            or admission["model_outcomes_consulted"] is not False
            or calibration["schema"] != SCHEMA or calibration["phase"] != "calibration"
            or calibration["precommit_sha256"] != PRECOMMIT_SHA):
        raise ValueError("complete original admission/pairs/calibration binding required")
    admitted = [r["repository"] for r in admission["source_selection"] if r["status"] == "admitted"]
    if admitted != [e["repo"] for e in entries] or len(set(admitted)) != 8:
        raise ValueError("unrecorded or reordered source admission")
    calibration_objects = set(calibration["exact_source_object_ids"])
    for entry, path in zip(entries, receipt_paths):
        receipt, _, _, _, receipt_sha = load_receipt(path)
        if (Path(entry["source_receipt_path"]).resolve() != path.resolve()
                or entry["source_receipt_sha256"] != receipt_sha
                or any(entry.get(key) != value for key, value in receipt["entry"].items())):
            raise ValueError("ordered admitted source receipt differs from projection source")
        objects = {obj["git_sha1"] for obj in receipt["original_objects"] + receipt["root_license_objects"]}
        if entry["repo"] in calibration["source_repositories"] or objects & calibration_objects:
            raise ValueError("calibration repository or exact object leaked into evaluation")
    return dict(admission_sha256=sha256(admission_raw), pairs_sha256=sha256(pairs_raw),
                calibration_sha256=sha256(calibration_raw))


def build(receipts, phase, precommit_path, output, *, admission_path=None, calibration_path=None):
    precommit_raw = regular(precommit_path)
    if sha256(precommit_raw) != PRECOMMIT_SHA:
        raise ValueError("prospective registration bytes changed")
    registration = json.loads(precommit_raw)
    if phase not in ("calibration", "evaluation") or len(receipts) != 8:
        raise ValueError("exact eight-source phase required")
    selection = None
    if phase == "evaluation":
        if admission_path is None or calibration_path is None:
            raise ValueError("evaluation requires the exact selector admission and calibration boundary")
        selection = verify_admission(admission_path, admission_path.parent / "EVALUATION_PAIRS.json",
                                     calibration_path, receipts)
    elif admission_path is not None or calibration_path is not None:
        raise ValueError("calibration cannot accept an evaluation admission")
    output.mkdir()
    documents, questions, labels, mappings, object_ids, repos = [], [], [], [], set(), []
    aliases = {}

    def alias(prefix, raw):
        value = prefix + "_" + hashlib.sha256(raw.encode()).hexdigest()[:8]
        if value in aliases and aliases[value] != raw:
            raise ValueError("declared identifier collision")
        aliases[value] = raw
        return value

    for slot, path in enumerate(receipts):
        receipt, objects, probes, parent_span, receipt_sha = load_receipt(path)
        entry = receipt["entry"]
        repo = entry["repo"]
        registered_sources = registration["calibration_sources"] if phase == "calibration" else registration["evaluation_source_pool_order"]
        if repo not in registered_sources:
            raise ValueError("unregistered source")
        registered_slot = registered_sources.index(repo)
        if (repo in repos or entry["slot"] != registered_slot
                or entry["kind"] != KINDS[registered_slot % 4]):
            raise ValueError("fixed source/kind order drift")
        repos.append(repo)
        if phase == "calibration" and repo != registration["calibration_sources"][slot]:
            raise ValueError("calibration source order changed")
        if phase == "evaluation" and repo not in registration["evaluation_source_pool_order"]:
            raise ValueError("unregistered evaluation source")
        lower, upper = registration[phase + "_window"]
        if not (lower <= entry["previous_date"] <= upper and lower <= entry["current_date"] <= upper):
            raise ValueError("source outside its fixed window")
        qid = alias("q", phase + ":" + repo + ":" + entry["current_sha"])
        service = alias("service", repo + ":" + entry["current_sha"])
        old_component = alias("component", entry["previous_sha"])
        new_component = alias("component", entry["current_sha"])
        old_site = alias("site", entry["previous_tree"])
        new_site = alias("site", entry["current_tree"])
        modes = {v: alias("mode", "git-cat-file-type-tree:" + repo + ":" + p["object"])
                 for v, p in probes.items()}
        scoped, derivations = [], []

        def binding(label, start=0, end=None):
            info, raw = objects[label]
            end = len(raw) if end is None else end
            return dict(source_filename=info["filename"], source_sha256=info["sha256"],
                        git_object=info["git_sha1"], byte_start=start, byte_end=end,
                        span_sha256=sha256(raw[start:end]))

        def fact(suffix, entity, attribute, value, revision, evidence, supersedes=()):
            identity = qid + "_" + suffix
            event = dict(schema=PROFILE, id=identity, entity=entity, attribute=attribute,
                         value=value, revision=revision, supersedes=list(supersedes))
            scoped.append(Document(identity, "git_" + entry["current_sha"], qid, qid,
                                   receipt["captured_at"], json.dumps(event, separators=(",", ":"))))
            derivations.append(dict(event_id=identity, source_bindings=evidence,
                                    derived_projection=True, external_original=False))
            return identity

        a = fact("l1", service, "location", old_site, 1, [binding("previous-commit", 5, 45)])
        b = fact("l2", service, "location", new_site, 2, [binding("current-commit", 5, 45)], [a])
        c = fact("c1", service, "component", old_component, 1, [binding("previous-commit")])
        d = fact("c2", service, "component", new_component, 2, [binding("current-commit")], [c])
        e = fact("p1", old_component, "location", old_site, 1, [binding("previous-commit", 5, 45)])
        fact("p2", new_component, "location", new_site, 2, [binding("current-commit", 5, 45)])
        fact("parent", new_component, "parent", old_component, 2,
             [binding("current-commit", *parent_span)])
        fact("kind1", old_component, "object_kind", "commit", 1, [binding("previous-commit")])
        fact("kind2", new_component, "object_kind", "commit", 2, [binding("current-commit")])
        success = fact("ok", new_component, "successful_mode", modes["tree"], 2,
                       [binding("current-tree"), probes["tree"]])
        fact("fail", new_component, "failed_mode", modes["commit"], 2,
             [binding("current-commit"), probes["commit"]])
        EventProjection(tuple(scoped))
        kind = entry["kind"]
        revision, path_fields, expected, support = {
            "new_fact": (1, ["location"], old_site, [a]),
            "correction": (2, ["location"], new_site, [b]),
            "composition": (1, ["component", "location"], old_site, [c, e]),
            "procedure": (2, ["component", "successful_mode"], modes["tree"], [d, success]),
        }[kind]
        questions.append(dict(id=qid, kind=kind, phase="test" if phase == "evaluation" else phase,
                              entity=service, path=path_fields, revision=revision))
        labels.append(dict(id=qid, kind=kind, expected=expected, support=support,
                           procedure=dict(bare_git_dir=str((path.parent / "objects.git").resolve()),
                                          source_receipt_path=str(path.resolve()), source_receipt_sha256=receipt_sha,
                                          modes={modes[v]: p["object"] for v, p in probes.items()},
                                          required_stdout="tree\n") if kind == "procedure" else None))
        documents.extend(asdict(doc) for doc in scoped)
        object_ids.update(i["git_sha1"] for i in receipt["original_objects"] + receipt["root_license_objects"])
        mappings.append(dict(question_id=qid, repository=repo, source_receipt_path=str(path.resolve()),
                             source_receipt_sha256=receipt_sha, derivations=derivations,
                             logical_snapshot_map={"1": entry["previous_sha"], "2": entry["current_sha"]},
                             unchanged_tree=entry["previous_tree"] == entry["current_tree"]))
    if phase == "evaluation":
        pool = registration["evaluation_source_pool_order"]
        if [pool.index(r) for r in repos] != sorted(pool.index(r) for r in repos):
            raise ValueError("evaluation pool order changed")
    write(output / "sources.json", documents)
    write(output / "questions.json", questions)
    write(output / "labels.json", labels)
    write(output / "program-support.json", {label["id"]: label["support"] for label in labels})
    write(output / "projection-proof.json", dict(
        schema=SCHEMA, phase=phase, cases=mappings, reversible_identifier_map=aliases,
        derivation="Git header/object identities and actual object-type probes; declared pair snapshots",
        event_json_is_external_original=False, semantic_adjudication_independent=False,
        raw_git_objects_retained=True, production_accepted=False,
    ))
    file_names = ["sources.json", "questions.json", "labels.json", "program-support.json", "projection-proof.json"]
    if selection is not None:
        for name, source in (("selection-admission.json", admission_path),
                             ("selected-pairs.json", admission_path.parent / "EVALUATION_PAIRS.json"),
                             ("calibration-source-boundary.json", calibration_path)):
            with (output / name).open("xb") as stream:
                stream.write(regular(source)); stream.flush(); os.fsync(stream.fileno())
            file_names.append(name)
    write(output / "collection.json", dict(
        schema=SCHEMA, phase=phase, created_at=datetime.now(timezone.utc).isoformat(),
        precommit_sha256=PRECOMMIT_SHA, builder_sha256=sha256(Path(__file__).read_bytes()),
        task_count=8, source_repositories=repos, exact_source_object_ids=sorted(object_ids),
        files={name: sha256((output / name).read_bytes()) for name in file_names},
        selection_proof=selection,
        separate_external_metadata_profile=True, inherited_original_pins_modified=False,
        independent_semantic_adjudication=False, production_accepted=False,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("calibration", "evaluation"))
    parser.add_argument("precommit", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("receipts", type=Path, nargs=8)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--calibration-collection", type=Path)
    args = parser.parse_args()
    build(args.receipts, args.phase, args.precommit, args.output,
          admission_path=args.admission, calibration_path=args.calibration_collection)


if __name__ == "__main__":
    main()
