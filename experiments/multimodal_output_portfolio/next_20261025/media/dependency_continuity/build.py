"""Bind a static import closure to evidence that predates qualification execution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "qualification-protocol", "process-start", "archive", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never replace a recorded dependency continuity audit")
    repo = Path.cwd().resolve()
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=repo, env=env)

    revision = git("rev-parse", args.revision).decode().strip()
    commit_seconds = int(git("show", "-s", "--format=%ct", revision))
    protocol = json.loads(args.qualification_protocol.read_text())
    started = json.loads(args.process_start.read_text())
    child_start_ns = started["started_unix_ns"]
    if not commit_seconds * 1_000_000_000 < protocol["registered_unix_ns"] < child_start_ns:
        raise ValueError("Historical evidence must predate both protocol registration and execution")
    argv = started["argv"]
    expected_output = Path(argv[argv.index("--output") + 1]).resolve()
    if Path(argv[argv.index("--protocol") + 1]).resolve() != args.qualification_protocol.resolve():
        raise ValueError("Actual started child names a different qualification protocol")
    review = json.loads(args.review.read_text())
    if (review["qualification_protocol_sha256"] != sha(args.qualification_protocol)
            or review["dynamic_import_calls"] or review["local_python_files"] != len(review["files"])):
        raise ValueError("Static review belongs to a different candidate or has unresolved dynamic imports")

    anchors = {}
    for name in ("closure_20261025/media/FINAL_PROTOCOL.json", "next_20261025/control/PROTOCOL.json",
                 "closure_20261025/media/EVIDENCE_RECEIPT.json"):
        relative = "experiments/multimodal_output_portfolio/" + name
        blob = git("show", revision + ":" + relative)
        anchors[relative] = {"sha256": hashlib.sha256(blob).hexdigest(), "document": json.loads(blob)}
        if sha(repo / relative) != anchors[relative]["sha256"]:
            raise ValueError("Historical evidence document changed since the earlier revision")
    receipt_name = "experiments/multimodal_output_portfolio/closure_20261025/media/EVIDENCE_RECEIPT.json"
    receipt = anchors[receipt_name]["document"]
    if sha(args.archive) != receipt["archive_sha256"] or args.archive.stat().st_size != receipt["archive_bytes"]:
        raise ValueError("Original archive differs from its pre-execution Git receipt")
    archive_entries = {}
    manifest = None
    wanted = {"repo_source/" + str(Path(row["path"]).relative_to(repo)) for row in review["files"]}
    with tarfile.open(args.archive, "r|gz") as stream:
        for member in stream:
            if not member.isfile():
                continue
            name = member.name.removeprefix("./")
            if name == "MANIFEST.json" or name in wanted:
                payload = stream.extractfile(member).read()
                digest = hashlib.sha256(payload).hexdigest()
                if name == "MANIFEST.json":
                    if digest != receipt["manifest_sha256"]:
                        raise ValueError("Archive manifest differs from its historical receipt")
                    manifest = json.loads(payload)
                else:
                    archive_entries[name] = {"sha256": digest, "bytes": len(payload)}
    if manifest is None:
        raise ValueError("Original archive manifest not found")
    manifest_files = {row["path"]: row for row in manifest["files"]}
    records = []
    for row in review["files"]:
        path = Path(row["path"]).resolve()
        relative = str(path.relative_to(repo))
        actual = sha(path)
        if actual != row["sha256"]:
            raise ValueError("Source changed since independent static review: " + relative)
        evidence = None
        if protocol["frozen_candidate_sha256"].get(str(path)) == actual:
            evidence = {"kind": "original_qualification_pin", "protocol_sha256": sha(args.qualification_protocol)}
        else:
            result = subprocess.run(["git", "show", revision + ":" + relative], cwd=repo, env=env, capture_output=True)
            if result.returncode == 0:
                if hashlib.sha256(result.stdout).hexdigest() != actual:
                    raise ValueError("Tracked helper changed from the pre-execution commit: " + relative)
                evidence = {"kind": "pre_execution_git_blob", "revision": revision,
                            "git_blob": git("rev-parse", revision + ":" + relative).decode().strip()}
            else:
                for anchor_name, anchor in anchors.items():
                    if anchor["document"].get("frozen_candidate_sha256", {}).get(str(path)) == actual:
                        evidence = {"kind": "pre_execution_protocol_pin", "anchor": str(repo / anchor_name),
                                    "anchor_sha256": anchor["sha256"], "revision": revision}
                        break
                if evidence is None:
                    member_name = "repo_source/" + relative
                    entry = archive_entries.get(member_name)
                    saved = manifest_files.get(member_name)
                    if not entry or not saved or entry["sha256"] != actual or saved["sha256"] != actual or entry["bytes"] != saved["bytes"]:
                        raise ValueError("No matching pre-execution evidence for helper: " + relative)
                    evidence = {"kind": "pre_execution_archive_member", "archive_sha256": receipt["archive_sha256"],
                                "member": member_name, "manifest_sha256": receipt["manifest_sha256"],
                                "receipt": str(repo / receipt_name), "receipt_sha256": anchors[receipt_name]["sha256"],
                                "revision": revision}
        records.append({"path": str(path), "relative_path": relative, "sha256": actual,
                        "qualification_pinned": bool(row["qualification_pinned"]),
                        "observed_mtime_ns": path.stat().st_mtime_ns, "historical_evidence": evidence})
    evidence_pins = {str(repo / key): value["sha256"] for key, value in anchors.items()}
    evidence_pins.update({str(args.review.resolve()): sha(args.review),
                          str(args.qualification_protocol.resolve()): sha(args.qualification_protocol),
                          str(args.process_start.resolve()): sha(args.process_start)})
    registration = expected_output / "registration.json"
    actual_registration = json.loads(registration.read_text())
    if actual_registration["protocol_sha256"] != sha(args.qualification_protocol):
        raise ValueError("Actual qualification registration differs from the expected protocol")
    evidence_pins[str(registration)] = sha(registration)
    guard_pins = {str(path.resolve()): sha(path) for path in sorted(Path(__file__).parent.glob("*.py"))}
    counts = {}
    for row in records:
        kind = row["historical_evidence"]["kind"]
        counts[kind] = counts.get(kind, 0) + 1
    save(args.output, {"schema": "hepta.next.media-dependency-continuity.v1", "created_unix_ns": time.time_ns(),
              "scope": "Retrospective identity continuity audit, with a prospective formal execution guard; the original qualification protocol was not amended",
              "qualification_protocol": str(args.qualification_protocol.resolve()),
              "qualification_protocol_sha256": sha(args.qualification_protocol),
              "qualification_process_start": str(args.process_start.resolve()), "qualification_child_start_unix_ns": child_start_ns,
              "qualification_output": str(expected_output),
              "qualification_process_receipt": str(args.process_start.parent / "receipt.json"),
              "qualification_registered_unix_ns": protocol["registered_unix_ns"],
              "qualification_outcome_values_read_for_this_audit": False,
              "historical_revision": revision, "historical_commit_unix_seconds": commit_seconds,
              "static_entrypoints": review["entrypoints"], "source_closure": records, "evidence_counts": counts,
              "frozen_evidence_sha256": evidence_pins, "frozen_guard_sha256": guard_pins,
              "archive": {"path": str(args.archive.resolve()), "sha256": receipt["archive_sha256"],
                          "bytes": receipt["archive_bytes"], "manifest_sha256": receipt["manifest_sha256"],
                          "full_compressed_hash_rechecked": True, "selected_members_read_without_extraction": True},
              "boundaries": ["Original 411-pin qualification did omit these local helpers; this audit does not retroactively claim otherwise.",
                             "Matching historical byte identities and current files establish recorded source continuity, not a forensic trace of every byte executed in process memory.",
                             "Local Git timestamps and filesystem metadata are not independently trusted timestamp authorities.",
                             "This closure covers statically imported repository Python sources; third-party interpreter, packages and native libraries are not an entire reproducible operating-system image.",
                             "No threshold, model, parser, cohort, generator or scoring choice changes in this addendum."]})
    print(json.dumps({"manifest_sha256": sha(args.output), "source_files": len(records), "evidence_counts": counts}))


if __name__ == "__main__":
    main()
