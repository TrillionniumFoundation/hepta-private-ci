"""Read-only admission checks for one explicitly requested pre-decoder resume."""

import json
from pathlib import Path
import stat
import sys

from native_backend import canonical, file_sha, inspect, sha

FAILURE = (
    "agentd protocol error: recover production cognitive store: cognitive recovery "
    "state is indeterminate: SQLite recovery is indeterminate: the complete "
    "immutable file identity was not established"
)
COMMANDS = {"source-archive", "prepare-source", "prepare-owner", "train-96",
            "configure", "daemon-probe"}
MUTABLE_PINS = {"runtime_digest", "worker_sha256"}


def read(path):
    return json.loads(Path(path).read_text())


def inventory(root):
    """Include empty directories and modes; reject links and special files."""
    entries = {}
    for path in [root, *sorted(root.rglob("*"))]:
        mode = path.lstat().st_mode
        row = {"mode": stat.S_IMODE(mode)}
        if stat.S_ISREG(mode):
            row.update(kind="file", bytes=path.stat().st_size, sha256=file_sha(path))
        elif stat.S_ISDIR(mode):
            row.update(kind="directory")
        else:
            raise ValueError("frozen inputs require regular files and directories")
        entries[str(path.relative_to(root))] = row
    return entries


def admit(failed, output, repo):
    """No output creation or model import; all old receipts remain unmodified."""
    trial = failed / "trial"
    original = read(trial / "native_config.json")
    model = Path(original["model"]).resolve(strict=True)
    checkpoint = Path(original["checkpoint"]).resolve(strict=True)
    if checkpoint != trial / "checkpoint":
        raise ValueError("checkpoint must belong to the retained failed run")
    for protected in (failed, model, checkpoint, repo):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("new output must not overlap frozen inputs or source")
    if output.exists() or output.is_symlink():
        raise ValueError("resume output must be create-new")
    frozen = {"failed_run": inventory(failed), "model": inventory(model)}
    if (read(failed / "native-owner/failure.json")["error"] != FAILURE
            or read(failed / "failure.json")["automatic_retry"] is not False
            or read(failed / "failure.json")["error"] !=
            f"RuntimeError: daemon-probe failed; original output is retained in {failed / 'commands/daemon-probe'}"):
        raise ValueError("only the exact retained pre-decoder recovery failure is admissible")
    commands = failed / "commands"
    if {p.name for p in commands.iterdir()} != COMMANDS:
        raise ValueError("unexpected prior command or read/control attempt")
    receipts = {name: read(commands / name / "receipt.json") for name in sorted(COMMANDS)}
    for name, receipt in receipts.items():
        if (receipt["attempts"] != 1 or receipt["timed_out"]
                or receipt["failure"] is not None
                or receipt["exit_code"] != (1 if name == "daemon-probe" else 0)):
            raise ValueError("prior stages must have one completed attempt with exact failure")
    allowed_owner_files = {"prepare.json", "failure.json", "anchor.json", "fleet", "workspace"}
    if ({p.name for p in (failed / "native-owner").iterdir()} - allowed_owner_files
            or (failed / "report.json").exists()
            or any((failed / "native-owner/workspace").iterdir())
            or any((trial / "native-process-receipts").iterdir())):
        raise ValueError("prior native dispatch or completed result cannot be resumed")
    if Path(original["receipt_directory"]).resolve() != trial / "native-process-receipts":
        raise ValueError("original model receipts must be inside the frozen run")
    source = read(failed / "source-before.json")
    invocation = read(failed / "invocation.json")
    if source["status"] or invocation["expected_head"] != source["head"]:
        raise ValueError("original source identity is not a clean explicit commit")
    if (Path(original["python"]).absolute() != Path(sys.executable).absolute()
            or invocation["python"] != original["python"]):
        raise ValueError("reuse requires the identical Python environment path")
    protocol = read(trial / "protocol.json")
    expected = {"steps": 96, "rank": 8, "seed": 24031, "learning_rate": 0.01,
                "objective": "completion_ce", "scope": "native-hnmf-ci-development",
                "templates": ["What is the {relation} for {entity}?"],
                "decoder_queries": 3, "native_feature_forwards": 1,
                "read_arms": ["native-fixed-adapter", "research-base", "research-shuffled"],
                "confirmation": False, "production_qualification": False,
                "parameter_success_gate": None}
    if any(protocol.get(key) != value for key, value in expected.items()):
        raise ValueError("only the unchanged fixed 96-update development recipe is admissible")
    training = read(trial / "training.json")
    receipt = training["receipt"]
    lineage = read(checkpoint / "lineage.json")
    document = read(trial / "source_document.json")
    query = read(trial / "read_query.json")
    root = file_sha(trial / "source_document.json")
    question = f"What is the {document['key']['relation']} for {document['key']['entity']}?"
    if (receipt["steps"] != 96 or receipt["actual_model_forwards"] != 96
            or receipt["schedule_indices"] != [0] * 96
            or receipt["writer_seed"] != 24031 or receipt["learning_rate"] != 0.01
            or receipt["objective"] != "completion_ce" or receipt["scope"] != protocol["scope"]
            or receipt["evaluation_targets_used"] or not receipt["base_unchanged"]
            or receipt["initialization"] != "frozen_base" or receipt["inherited_roots"]
            or receipt["roots"] != [root] or receipt["source_digests"] != [root]
            or lineage["training"] != receipt or lineage["roots"] != [root]
            or training["manifest_sha256"] != file_sha(checkpoint / "lineage.json")
            or query != {"question": question, "source_root": root}
            or read(trial / "source_mapping.json")["typed_source_sha256"] != root):
        raise ValueError("training, source, query and checkpoint lineage must bind exactly")
    if read(failed / "checkpoint-before.json") != {
            p.name: file_sha(p) for p in checkpoint.iterdir() if p.is_file()}:
        raise ValueError("retained post-training checkpoint changed")
    if (original["output_width"] != 4 or original["rank"] != 8
            or original["seed"] != 24031 or original["scope"] != protocol["scope"]
            or read(checkpoint / "adapter_config.json")["r"] != 8):
        raise ValueError("original native profile changed")
    pins, inspected = inspect(repo, model, checkpoint)
    if (set(pins) != set(original["pins"])
            or any(pins[key] != original["pins"][key] for key in set(pins) - MUTABLE_PINS)):
        raise ValueError("base, adapter, lineage, decoder or device identity changed")
    old_inspection = read(trial / "native_inspection.json")
    if (inspected["model"] != old_inspection["model"]
            or inspected["lineage"] != old_inspection["lineage"]
            or original["pins"]["runtime_digest"] != sha(canonical(old_inspection["runtime"]))):
        raise ValueError("original inspected checkpoint or runtime receipt differs")
    inputs = read(failed / "source-inputs.json")
    acquisition = read(failed / "acquisition.json")
    fixtures = repo / "scripts/memory_cell_native/fixtures"
    if (inputs != read(fixtures / "source-inputs.json")
            or acquisition["spec"] != read(fixtures / "base-acquisition.json")
            or acquisition["automatic_retries"] != 0
            or file_sha(fixtures / inputs["archive"]) != inputs["archive_sha256"]):
        raise ValueError("original source inputs or pinned base acquisition changed")
    for member in inputs["members"]:
        path = trial / "imported" / member["path"]
        if (not path.resolve().is_relative_to(trial / "imported")
                or path.stat().st_size != member["bytes"] or file_sha(path) != member["sha256"]):
            raise ValueError("actual imported source evidence differs from frozen inventory")
    for row in acquisition["files"]:
        if (not row["complete"] or inspected["model"].get(row["path"]) !=
                {"bytes": row["bytes"], "sha256": row["sha256"]}):
            raise ValueError("original completed acquisition differs from actual base files")
    for key in ("python", "executable_sha256", "versions"):
        if inspected["runtime"][key] != old_inspection["runtime"][key]:
            raise ValueError("original Python runtime packages changed")
    for name, row in old_inspection["runtime"]["sources"].items():
        if name != "scripts/memory_cell_native/native_worker.py":
            if inspected["runtime"]["sources"].get(name) != row:
                raise ValueError(f"frozen training/control/runtime source changed: {name}")
    return {"original": original, "protocol": protocol, "training": training,
            "model": model, "checkpoint": checkpoint, "pins": pins, "inspection": inspected,
            "frozen": frozen, "source": source, "commands": receipts,
            "original_sha256s": {name: frozen["failed_run"][name]["sha256"] for name in
                                 ("failure.json", "trial/training.json", "trial/native_config.json")},
            "failure": read(failed / "failure.json"), "acquisition": acquisition}
