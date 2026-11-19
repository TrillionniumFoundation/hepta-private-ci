"""Package verified recovery evidence; this is not the original complete release.

Standard library only. Creation requires the final recovery audit and current
report, exact primary recovery, numerical replay and new timing measurements.
Original timing, original final audit and original complete archive remain lost.
"""

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath


E = "research_evidence/hepta_stable_flow_20261029"
R = E + "/recovery_20261030"
N = E + "/trained_numerics_replay_20261030"
T = E + "/inference_cost_replay_20261030"
P = E + "/formal_run001"
AUDIT = R + "/final_recovery_audit.json"
REPORT = E + "/report003_recovery/report_receipt.json"
PRIMARY = R + "/primary_reconstruction_receipt.json"
PRIMARY_RESULT = P + "/results.json"
PRIMARY_SHA = "062c049ab04abe6ca1a12f1cf2f67b88056c74dcde60cc212fa38bc6c22de992"
MANIFEST = "HEPTA_RECOVERY_MANIFEST.json"
SCHEMA = "hepta-recovery-evidence-v1"
SCOPE = (
    "experiments/call_put_stable_flow",
    "experiments/call_put_stable_flow_appendix",
    "experiments/call_put_stable_flow_analysis",
    E,
    "research_evidence/hepta_callput_recovery_20261029",
)
GATE_INPUTS = {
    AUDIT, REPORT, PRIMARY, PRIMARY_RESULT, N + "/execution/summary.json",
    T + "/execution/summary.json", T + "/execution/raw_events.jsonl",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


def safe(name):
    require(isinstance(name, str) and name and not name.startswith("/"), "Unsafe path")
    require(not any(c in name for c in "\\:\x00"), "Unsafe path character")
    require(all(p not in ("", ".", "..") for p in name.split("/")), "Unsafe path component")
    require(PurePosixPath(name).as_posix() == name, "Noncanonical path")
    return name


def included(name):
    safe(name)
    return (
        any(name.startswith(p + "/") for p in SCOPE)
        and name != E + "/releases" and not name.startswith(E + "/releases/")
        and "__pycache__" not in name.split("/") and not name.endswith(".pyc")
    )


def checked(root, name):
    path = root / safe(name)
    require(not any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)), "Symlink rejected")
    require(path.resolve().is_relative_to(root), "Path escapes root")
    return path


def inventory(root):
    rows = []
    for prefix in SCOPE:
        folder = checked(root, prefix)
        require(folder.is_dir(), "Missing scope directory: " + prefix)
        for path in folder.rglob("*"):
            name = path.relative_to(root).as_posix()
            if not included(name):
                continue
            checked(root, name)
            if path.is_dir():
                continue
            require(path.is_file(), "Nonregular artifact")
            data = path.read_bytes()
            rows.append({"path": name, "bytes": len(data), "sha256": sha(data)})
    require(len({r["path"] for r in rows}) == len(rows), "Duplicate scope artifact")
    return sorted(rows, key=lambda row: row["path"])


def gates(files, read):
    catalog = {row["path"]: row for row in files}

    def bind(name, digest, size=None):
        require(included(name) and name in catalog, "Missing bound artifact: " + name)
        row = catalog[name]
        require(row["sha256"] == digest and (size is None or row["bytes"] == size), "Binding changed: " + name)

    def load(name):
        require(name in catalog, "Missing gate input: " + name)
        return json.loads(read(name))

    audit = load(AUDIT)
    require(audit.get("status") == "complete" and audit.get("artifact_integrity_passed") is True, "Final recovery audit incomplete")
    require(audit.get("all_research_blockers_closed", False) is False and audit.get("original_archive_recovered", False) is False, "Final audit overstates recovery")
    bound = audit.get("bound_artifacts", [])
    names = [row["path"] for row in bound]
    require(bound and len(names) == len(set(names)) and AUDIT not in names, "Empty, duplicate or recursive audit bindings")
    require((GATE_INPUTS - {AUDIT}).issubset(names), "Critical gate input is not audited")
    for row in bound:
        bind(row["path"], row["sha256"])
    report = load(REPORT)
    require(report.get("outputs") and report.get("consumed_inputs"), "Recovery report bindings incomplete")
    for row in report["consumed_inputs"]:
        bind(row["path"], row["sha256"], row["bytes"])
    for row in report["outputs"]:
        bind(str(PurePosixPath(REPORT).parent / safe(row["path"])), row["sha256"], row["bytes"])
    primary = load(PRIMARY)
    require(primary.get("all_original_primary_digests_reproduced") is True and primary.get("original_inputs_unchanged") is True and primary.get("training_or_selection_executed") is False, "Primary reconstruction gate failed")
    rows = primary.get("comparisons", [])
    require(len(rows) == 61 and len({r["path"] for r in rows}) == 61, "Primary reconstruction coverage mismatch")
    scores = load(PRIMARY_RESULT)
    expected = {PRIMARY_RESULT} | {P + "/" + safe(r["prediction_file"]) for r in scores["results"]}
    require(len(scores["results"]) == 60 and len(expected) == 61 and {r["path"] for r in rows} == expected, "Primary identities mismatch")
    bind(PRIMARY_RESULT, PRIMARY_SHA)
    for row in scores["results"]:
        bind(P + "/" + safe(row["prediction_file"]), row["prediction_sha256"])
    for row in rows:
        require(row.get("exact_match") is True and row["reconstructed_sha256"] == row["sha256"], "Nonexact primary reconstruction")
        bind(row["path"], row["sha256"], row["bytes"])
    numerical = load(N + "/execution/summary.json")
    require(all(numerical.get(k) == v for k, v in {"registered_aliases": 24, "physical_checkpoints": 24, "dop_aliases": 8, "dop_physical_checkpoints": 8, "execution_errors": 0}.items()), "Numerical replay coverage incomplete")
    require(numerical.get("primary_scores_or_selection_modified") is False and numerical.get("test_data_or_scores_read") is False, "Numerical replay changed primary contract")
    records = numerical["records"]
    require(len(records) == 24 and len({r["folder"] for r in records}) == 24 and sum("independent_flow" in r for r in records) == 8, "Numerical replay records incomplete")
    for row in records:
        require("execution_error" not in row and row.get("checkpoint_unchanged") is True, "Numerical execution error retained but not complete")
        folder = N + "/" + safe(row["folder"])
        bind(folder + "/receipt.json", row["receipt_sha256"])
        require(row.get("raw_artifacts_sha256"), "Missing numerical raw artifacts")
        for name, digest in row["raw_artifacts_sha256"].items():
            bind(folder + "/" + safe(name), digest)
    runtime = load(T + "/execution/summary.json")
    require(all(runtime.get(k) == v for k, v in {"status": "complete", "alias_count": 20, "physical_checkpoint_count": 20, "case_count": 40, "timed_repetitions_per_case": 11, "warmups_per_case": 3}.items()), "Runtime replay coverage incomplete")
    cases = runtime["cases"]
    require(len(cases) == 40 and len({c["case_id"] for c in cases}) == 40, "Duplicate or missing runtime case")
    identity = lambda r: (r["task"], r["arm"], r["seed"], r["regime"])
    desired = {identity(r) for r in scores["results"] if r["seed"] == 81301}
    require(len(desired) == 20 and {identity(a) for c in cases for a in c["aliases"]} == desired and {(c["physical_index"], c["batch_size"]) for c in cases} == {(i, b) for i in range(20) for b in (1, 32)}, "Runtime model or batch identities differ")
    for filename, key in (("raw_times.npz", "raw_times_sha256"), ("raw_events.jsonl", "raw_events_sha256"), ("plan.json", "execution_plan_sha256")):
        bind(T + "/execution/" + filename, runtime[key])
    events = [json.loads(line) for line in read(T + "/execution/raw_events.jsonl").splitlines()]
    require(len(events) == 440 and {(e["case_index"], e["repetition"]) for e in events} == {(i, r) for i in range(40) for r in range(11)}, "Runtime event coverage incomplete")
    require(all(e["case_id"] == cases[e["case_index"]]["case_id"] and e["cpu_nanoseconds"] > 0 and e["wall_nanoseconds"] > 0 for e in events), "Runtime event identity or duration invalid")
    return {"final_recovery_audit_sha256": catalog[AUDIT]["sha256"], "recovery_report_receipt_sha256": catalog[REPORT]["sha256"], "primary_exact_artifacts": 61, "numerical_aliases": 24, "continuous_flow_aliases": 8, "runtime_aliases": 20, "runtime_cases": 40, "runtime_events": 440}


def validate_manifest(manifest):
    require(manifest.get("schema") == SCHEMA and manifest.get("scope") == list(SCOPE), "Wrong recovery manifest contract")
    require(manifest.get("all_research_blockers_closed") is False and manifest.get("original_archive_recovered") is False, "Misleading completion claim")
    rows = manifest["files"]
    names = [row["path"] for row in rows]
    require(rows and names == sorted(set(names)), "Empty, duplicate or unordered manifest")
    for row in rows:
        require(set(row) == {"path", "bytes", "sha256"} and included(row["path"]), "Out-of-scope manifest member")
        require(type(row["bytes"]) is int and row["bytes"] >= 0, "Invalid member length")
        require(len(row["sha256"]) == 64 and all(c in "0123456789abcdef" for c in row["sha256"]), "Invalid member digest")
    require(manifest["file_count"] == len(rows) and manifest["total_file_bytes"] == sum(r["bytes"] for r in rows), "Manifest counts mismatch")
    return rows


def verify(archive):
    retained, observed = {}, []
    with tarfile.open(archive, "r:gz") as stream:
        first = stream.next()
        require(first is not None and first.name == MANIFEST and first.isfile() and first.size <= 16 * 1024 * 1024, "Manifest must be the first regular member")
        require(first.mode == 0o644 and first.mtime == first.uid == first.gid == 0, "Unsafe manifest metadata")
        raw = stream.extractfile(first).read()
        manifest = json.loads(raw)
        require(encoded(manifest) == raw, "Manifest is not canonical JSON")
        rows = validate_manifest(manifest)
        expected = {row["path"]: row for row in rows}
        for member in iter(stream.next, None):
            require(member.name in expected and member.name not in observed, "Unexpected or duplicate archive member")
            require(member.isfile() and member.mode == 0o644 and member.mtime == member.uid == member.gid == 0, "Unsafe member type or metadata")
            row = expected[member.name]
            require(member.size == row["bytes"], "Archive member size mismatch")
            data = stream.extractfile(member).read()
            require(len(data) == row["bytes"] and sha(data) == row["sha256"], "Archive member digest mismatch")
            if member.name in GATE_INPUTS:
                retained[member.name] = data
            observed.append(member.name)
    require(observed == [r["path"] for r in rows], "Missing or unordered archive members")
    require(gates(rows, retained.__getitem__) == manifest["gates"], "Archive gates differ from manifest")
    return {"schema": "hepta-recovery-archive-verification-v1", "status": "archive_verified", "archive_bytes": archive.stat().st_size, "archive_sha256": sha(archive.read_bytes()), "manifest_sha256": sha(raw), "file_count": len(rows), "total_file_bytes": manifest["total_file_bytes"], "all_research_blockers_closed": False, "original_archive_recovered": False}


def verify_tree(root):
    raw = checked(root, MANIFEST).read_bytes()
    manifest = json.loads(raw)
    require(encoded(manifest) == raw, "Extracted manifest is not canonical JSON")
    rows = validate_manifest(manifest)
    actual = []
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        checked(root, name)
        require(path.is_dir() or path.is_file(), "Nonregular extracted entry")
        if path.is_file() and name != MANIFEST:
            actual.append(name)
    require(sorted(actual) == [r["path"] for r in rows], "Extracted file set differs")
    require(inventory(root) == rows, "Extracted bytes differ")
    require(gates(rows, lambda name: checked(root, name).read_bytes()) == manifest["gates"], "Extracted gates differ")
    return {"status": "tree_verified", "file_count": len(rows), "all_research_blockers_closed": False, "original_archive_recovered": False}


def create(root, output):
    if output.is_relative_to(root):
        checked(root, output.relative_to(root).as_posix())
    require(not output.is_relative_to(root) or not included(output.relative_to(root).as_posix()), "Output would enter its own inventory")
    targets = [output, Path(str(output) + ".manifest.json"), Path(str(output) + ".receipt.json")]
    require(all(not p.exists() and not p.is_symlink() for p in targets), "Refuse to overwrite release artifact")
    before = inventory(root)
    manifest = {"schema": SCHEMA, "scope": list(SCOPE), "all_research_blockers_closed": False, "original_archive_recovered": False, "meaning": "Available original evidence, exact digest-verified reconstructions and explicitly new appendix replays; not the lost original complete archive or proof of scientific advantage.", "files": before, "file_count": len(before), "total_file_bytes": sum(r["bytes"] for r in before), "gates": gates(before, lambda name: checked(root, name).read_bytes())}
    raw = encoded(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog = {r["path"]: r for r in before}
    with output.open("xb") as file, gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name in [MANIFEST, *catalog]:
            data = raw if name == MANIFEST else checked(root, name).read_bytes()
            if name != MANIFEST:
                row = catalog[name]
                require(len(data) == row["bytes"] and sha(data) == row["sha256"], "Input changed while archiving")
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime, info.uid, info.gid = len(data), 0o644, 0, 0, 0
            archive.addfile(info, io.BytesIO(data))
    require(inventory(root) == before, "Inventory changed during creation")
    receipt = verify(output)
    with targets[1].open("xb") as stream:
        stream.write(raw)
    with targets[2].open("xb") as stream:
        stream.write(encoded({**receipt, "status": "recovery_archive_created"}))
    return {**receipt, "status": "recovery_archive_created", "archive": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("create")
    build.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    build.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--archive", type=Path, required=True)
    tree = commands.add_parser("verify-tree")
    tree.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = create(args.root.resolve(), args.output.absolute()) if args.command == "create" else verify(args.archive) if args.command == "verify" else verify_tree(args.root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
