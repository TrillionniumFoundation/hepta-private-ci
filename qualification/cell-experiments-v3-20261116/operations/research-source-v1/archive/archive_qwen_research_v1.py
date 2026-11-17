"""Create-only raw export after root has confirmed both writers terminal.

No experiment, model, verifier or C access. Whole ZIP/index are transport objects.
Real owned-child waits and fresh process observations are authoritative for writer
termination; raw controller status is preserved separately. Byte/stat rechecks are
not an atomic filesystem snapshot. Utility source origin: 7bcd81d5bc8cae58c03a80c62e5c39f858a5996c1df1768ac4252a2d58fb80d1.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import traceback
import zipfile

PART, LIMIT = 322560, 512000
DEV, DIAG = "research-sft-01", "research-diagnostic-01"
HELPERS = {
    "qwen_development_io_v3.py": "4116cfc058cfbec9bdca4845e409d0c1c2071d9da9faa4b56f9d8aa6df5a2060",
    "qwen_development_inputs_v3.py": "6bd1b2d71857c5b541ca63ce815cbb05660b75284fc7065e5766e43d910fea20",
    "qwen_development_execution_v3.py": "b28824a766115de190946055225452743dc95482de53a3d872781a7922b77656",
    "run_qwen_development_v3.py": "1f8cbc7eb21cae9a1e82654b3234e839f7cbe6cfa055f40900d16a559d72bb20",
}
FORBIDDEN = {"catalog-C.sealed.json", "specs-confirmation.json", "C_STARTED.json", "INPUTS_C.json"}
OMIT = {"__pycache__", ".pytest_cache", ".cache", "venv", "materials", "materials-recovered"}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def checksum(path):
    require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), "regular nonsymlink bytes required")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def bounded(root, relative):
    name = PurePosixPath(relative)
    require(name.parts and not name.is_absolute() and ".." not in name.parts
            and str(name) == relative and "\\" not in relative, "bounded relative path required")
    current = root
    for part in name.parts:
        current /= part
        require(not current.is_symlink(), "symlink rejected: " + str(current))
    require(current.resolve().is_relative_to(root), "path escaped artifact root")
    return current


def read(path):
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 64 * 1024**2, "bounded regular JSON required")
    return json.loads(path.read_bytes())


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def walk(root, path):
    mode = path.lstat().st_mode
    require(not stat.S_ISLNK(mode), "symlink rejected: " + str(path))
    require(path.name not in FORBIDDEN, "confirmation member rejected before reading")
    if path.name in OMIT:
        return []
    if stat.S_ISREG(mode):
        return [path]
    require(stat.S_ISDIR(mode), "special file rejected: " + str(path))
    return [p for child in sorted(path.iterdir())
            for p in walk(root, bounded(root, child.relative_to(root).as_posix()))]


def inventory(root, sources):
    result = []
    for path in sorted({p for source in sources for p in walk(root, source)}):
        s = path.stat()
        result.append({"path": path.relative_to(root).as_posix(), "bytes": s.st_size,
                       "sha256": checksum(path), "mode": stat.S_IMODE(s.st_mode),
                       "mtime_ns": s.st_mtime_ns, "device": s.st_dev, "inode": s.st_ino})
    return result


def process_observation(expected):
    require(type(expected.get("pid")) is int and expected["pid"] > 0, "valid owned PID required")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    result = {"observed_at_ns": time.time_ns(), "expected": expected, "current_boot": boot}
    if expected.get("boot") and expected["boot"] != boot:
        return dict(result, stopped=True, reason="different_boot")
    try:
        raw = Path("/proc", str(expected["pid"]), "stat").read_text()
    except FileNotFoundError:
        return dict(result, stopped=True, reason="pid_absent")
    fields = raw.rsplit(")", 1)[1].split()
    tick, state = int(fields[19]), fields[0]
    prior = expected.get("start_time_ticks")
    stopped = state in ("Z", "X") or (type(prior) is int and prior != tick)
    return dict(result, stopped=stopped, reason="not_same_live_writer" if stopped else "writer_may_be_live",
                current_start_time_ticks=tick, current_state=state,
                proc_stat_sha256=hashlib.sha256(raw.encode()).hexdigest())


def owned_receipts(directory, role, argv):
    intent_path, start_path, exit_path = [directory / n for n in ("INTENT.json", "STARTED.json", "EXIT.json")]
    intent, started, exited = [read(p) for p in (intent_path, start_path, exit_path)]
    require(intent.get("schema") == "hepta.research-owned-intent.v1"
            and started.get("schema") == "hepta.research-owned-started.v1"
            and exited.get("schema") == "hepta.research-owned-exit.v1", "owned receipt schema differs")
    require(intent.get("role") == role == exited.get("role")
            and intent.get("operation_key") == exited.get("operation_key"), "owned operation identity differs")
    require(intent.get("argv") == started.get("argv") == exited.get("argv") == argv, "owned argv differs")
    require(started.get("intent_sha256") == checksum(intent_path)
            and exited.get("intent_sha256") == checksum(intent_path)
            and exited.get("started_sha256") == checksum(start_path), "owned receipt chain changed")
    require(exited.get("child_identity") == started.get("child_identity")
            and type(exited.get("wait_returncode")) is int
            and exited.get("exit_source") == "subprocess.Popen.wait", "real owned wait result required")
    for channel in ("stdout", "stderr"):
        path = directory / (channel + ".log")
        require(started.get(channel + "_path") == str(path)
                and exited[channel] == {"bytes": path.stat().st_size, "sha256": checksum(path)},
                "original child stream identity differs")
    observations = [process_observation(started["child_identity"]),
                    process_observation(started["wrapper_identity"])]
    require(all(row["stopped"] for row in observations), "owned child or wrapper may still be live")
    return intent, started, exited, observations


def writer_evidence(root, index_path, helpers, postrun):
    index = read(index_path)
    require(index.get("schema") == "hepta.research-export-terminals.v1"
            and index.get("artifact_root") == str(root) and index.get("writers_stopped_confirmed") is True
            and type(index.get("observed_at_ns")) is int and index["observed_at_ns"] > 0,
            "explicit root terminal observation index required")
    rows = index.get("writers", [])
    require(len(rows) == 2 and {row.get("role") for row in rows} == {"research", "postrun"},
            "both research and postrun writer observations required")
    retained, outcomes = [index_path], []
    wrapper = bounded(root, "operations/launch_qwen_research_owned_v1.py")
    require(checksum(wrapper) == "4f647ae7e7cc5f5f0d04b597db10f0a68b946ecff04821651a16633bfe02eab0",
            "reviewed owned launcher differs")
    retained.append(wrapper)
    for row in rows:
        role = row["role"]
        output = DEV if role == "research" else DIAG
        owned = "owned-research-sft-01" if role == "research" else "owned-research-diagnostic-01"
        source = bounded(root, "research-sft-v1-source/run_research_sft_v1.py") if role == "research" else postrun
        require(row["output_directory"] == output and row["owned_directory"] == owned
                and bounded(root, row["source_path"]) == source
                and checksum(source) == row["source_sha256"], "writer source or output differs")
        freeze_path = bounded(root, row["launch_freeze_path"])
        require(checksum(freeze_path) == row["launch_freeze_sha256"], "launch freeze changed")
        freeze = read(freeze_path)
        require(freeze.get("schema") == "hepta.research-owned-launch-freeze.v1"
                and freeze["role"] == role and freeze["output_directory"] == output
                and freeze["entry_sha256"] == row["source_sha256"]
                and freeze["wrapper_sha256"] == checksum(wrapper), "launch freeze identity differs")
        intent, started, exited, observed = owned_receipts(bounded(root, owned), role, freeze["argv"])
        require(intent["freeze_sha256"] == row["launch_freeze_sha256"]
                and intent["entry_sha256"] == row["source_sha256"]
                and intent["wrapper_sha256"] == checksum(wrapper), "owned writer differs from freeze")
        for name, item in freeze["immutable_inputs"].items():
            path = bounded(root, name)
            require(path.stat().st_size == item["bytes"] and checksum(path) == item["sha256"],
                    "frozen launch input changed: " + name)
            retained.append(path)
        control_path = bounded(root, row["observation_path"])
        require(checksum(control_path) == row["observation_sha256"], "controller observation changed")
        control = read(control_path)
        require(isinstance(control.get("status"), dict) and isinstance(control.get("session_id"), str),
                "original terminal response required")
        retained.extend([freeze_path, control_path, bounded(root, owned)])
        require(bounded(root, output).is_dir() or exited["wait_returncode"] != 0,
                "successful writer output directory is absent")
        outcomes.append({"role": role, "actual_wait_returncode": exited["wait_returncode"],
                         "owned_exit_sha256": checksum(bounded(root, owned) / "EXIT.json"),
                         "process_observations": observed, "controller_status_as_observed": control["status"],
                         "controller_output_complete_as_observed": control.get("output_complete"),
                         "controller_status_rewritten": False})
    workers = []
    processes = bounded(root, DEV + "/processes")
    if processes.exists():
        for launch in sorted(processes.glob("*/LAUNCH.json")):
            bounded(root, launch.relative_to(root).as_posix())
            begin = read(launch)
            require(isinstance(begin.get("argv"), list) and begin.get("automatic_retry") is False,
                    "owned worker launch evidence differs")
            paths = [p for p in (launch.parent / "EXIT.json", launch.parent / "INTERRUPTED.json") if p.exists()]
            require(len(paths) == 1, "started worker lacks exactly one terminal receipt")
            child = read(paths[0])
            require(type(child.get("pid")) is int and child["pid"] > 0
                    and type(child.get("exit_code")) is int, "worker wait result is unknown")
            if paths[0].name == "EXIT.json":
                body = {k: v for k, v in child.items() if k != "receipt_sha256"}
                require(hashlib.sha256(canonical(body)).hexdigest() == child.get("receipt_sha256"),
                        "worker exit seal changed")
                for channel in ("stdout", "stderr"):
                    require(child[channel + "_sha256"] == checksum(launch.parent / (channel + ".log")),
                            "worker stream changed")
            observation = process_observation({"pid": child["pid"]})
            require(observation["stopped"], "worker PID still present; reconcile before final archive")
            workers.append({"launch_path": launch.relative_to(root).as_posix(), "launch_sha256": checksum(launch),
                            "terminal_sha256": checksum(paths[0]), "exit_code": child["exit_code"],
                            "process_observation": observation})
    index["verified_writer_outcomes"] = outcomes
    index["verified_worker_outcomes"] = workers
    return retained, index


def partition(path, destination, prefix):
    parts, whole = [], hashlib.sha256()
    with path.open("rb") as source:
        for i, raw in enumerate(iter(lambda: source.read(PART), b"")):
            name = f"{prefix}-{i:05d}.bin"
            with (destination / name).open("xb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            parts.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            whole.update(raw)
    require(whole.hexdigest() == checksum(path), "partition source changed")
    restored, size = hashlib.sha256(), 0
    for item in parts:
        raw = (destination / item["path"]).read_bytes()
        require(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"], "part bytes differ")
        restored.update(raw)
        size += len(raw)
    require(size == path.stat().st_size and restored.hexdigest() == whole.hexdigest(), "parts do not reconstruct original")
    return {"transport_path": path.name, "bytes": size, "sha256": whole.hexdigest(), "parts": parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    for name in ("helpers", "postrun-source", "terminal-index", "output"):
        parser.add_argument("--" + name, required=True, help="relative path under artifact root")
    args = parser.parse_args()
    root = args.artifact_root
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), "existing nonsymlink absolute root required")
    helpers, postrun = bounded(root, args.helpers), bounded(root, args.postrun_source)
    index_path, output = bounded(root, args.terminal_index), bounded(root, args.output)
    own = Path(__file__).absolute()
    require(own.resolve() == own and own.is_relative_to(root), "archive helper must be retained under artifact root")
    sources = [bounded(root, name) for name in (DEV, DIAG) if bounded(root, name).exists()]
    sources.extend([postrun, own])
    sources.extend(bounded(root, name) for name in ("research-sft-v1-source",
        "research-diagnostic-v1-source", "candidate-qwen-03", "probe-qwen-parent-03"))
    original = bounded(root, "operations/archive_qwen_final_v3.py")
    require(checksum(original) == "7bcd81d5bc8cae58c03a80c62e5c39f858a5996c1df1768ac4252a2d58fb80d1",
            "original reused archive utility source differs")
    sources.append(original)
    sources.extend(bounded(root, (helpers / name).relative_to(root).as_posix()) for name in HELPERS)
    require(not output.exists(), "export directory exists; do not overwrite or retry into it")
    retained, terminal = writer_evidence(root, index_path, helpers, postrun)
    sources.extend(retained)
    require(all(not output.is_relative_to(p) and not p.is_relative_to(output) for p in sources), "export/source overlap rejected")
    require({name: checksum(helpers / name) for name in HELPERS} == HELPERS, "helpers04 bytes differ")
    freeze, result = root / DEV / "FREEZE.json", root / DIAG / "RESULT.json"
    require((checksum(freeze) if freeze.exists() else None) == terminal["research_freeze_sha256"],
            "research freeze differs from root terminal index")
    require((checksum(result) if result.exists() else None) == terminal["diagnostic_result_sha256"],
            "diagnostic result differs from root terminal index")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    started = time.time_ns()
    write_new(output / "STARTED.json", {"started_at_ns": started, "root": str(root), "terminal_index_sha256": checksum(index_path)})
    try:
        members = inventory(root, sources)
        require(members, "empty export rejected")
        index = output / "MEMBERS.jsonl"
        with index.open("xb") as stream:
            for row in members:
                stream.write(canonical(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        archive = output / "qwen-research-sft.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for row in members:
                z.write(bounded(root, row["path"]), row["path"])
        with zipfile.ZipFile(archive) as z:
            require(z.namelist() == [r["path"] for r in members] and z.testzip() is None, "ZIP inventory or CRC differs")
            for row in members:
                h, count = hashlib.sha256(), 0
                with z.open(row["path"]) as stream:
                    for block in iter(lambda: stream.read(1024**2), b""):
                        h.update(block)
                        count += len(block)
                require(count == row["bytes"] and h.hexdigest() == row["sha256"], "ZIP member differs from source")
        manifest = {"schema": "hepta.research-final-export.v1", "artifact_root": str(root), "started_at_ns": started,
                    "member_count": len(members), "source_bytes": sum(r["bytes"] for r in members), "part_bytes": PART,
                    "archive": partition(archive, output, "archive-part"), "members": partition(index, output, "members-part"),
                    "terminal_index_sha256": checksum(index_path), "writer_observations": terminal["writers"],
                    "verified_writer_outcomes": terminal["verified_writer_outcomes"],
                    "verified_worker_outcomes": terminal["verified_worker_outcomes"],
                    "research_only": True, "scientific_confirmation_qualified": False,
                    "native_cell_adoption": False, "proof_of_useful_work_eligible": False,
                    "circuit_qualified": False, "candidate_selected": None, "independent_sample_increment": 0,
                    "public_base_included": False, "new_C_read": False, "new_model_calls": 0, "new_verifier_calls": 0,
                    "filesystem_atomic_snapshot_claimed": False,
                    "snapshot_basis": "root terminal observations, owned-child terminal receipts, final source byte/stat comparison"}
        require(inventory(root, sources) == members, "source files, paths or metadata changed during export")
        manifest.update(completed_at_ns=time.time_ns(), final_source_recheck_equal=True,
                        zip_crc_and_all_member_hashes_verified=True, all_part_reconstructions_verified=True)
        write_new(output / "TRANSFER_MANIFEST.json", manifest)
        restore = "Concatenate each manifest object's ordered parts into new archive/index files. Verify every part's size/SHA256, then each whole object's size/SHA256. Verify ZIP CRC and every member's path/size/SHA256 against MEMBERS.jsonl before extraction to a new directory. Reject symlinks, traversal, existing targets and special members. Preserve receipt bytes and original absolute paths; do not rewrite them. Base weights, environment and caches are separate dependencies. Git objects ONLY: TRANSFER_MANIFEST.json, RESTORE.txt, archive-part-*.bin and members-part-*.bin. Whole ZIP and MEMBERS.jsonl are transfer-only. STARTED/FAILED are operation evidence, outside that Git object list.\n"
        with (output / "RESTORE.txt").open("x") as stream:
            stream.write(restore)
        git_objects = [output / "TRANSFER_MANIFEST.json", output / "RESTORE.txt"] + [output / p["path"] for key in ("archive", "members") for p in manifest[key]["parts"]]
        require(all(p.stat().st_size < LIMIT for p in git_objects), "proposed Git object exceeds bound")
        print(json.dumps({"status": "EXPORTED_VERIFIED", "output": str(output), "members": len(members),
                          "archive_sha256": manifest["archive"]["sha256"], "git_objects": len(git_objects)}), flush=True)
    except BaseException as error:
        write_new(output / "FAILED.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "partial_export_preserved": True, "source_modified": False, "automatic_retry": False})
        raise


if __name__ == "__main__":
    main()
