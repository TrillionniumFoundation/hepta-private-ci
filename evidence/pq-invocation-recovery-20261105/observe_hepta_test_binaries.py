#!/usr/bin/env python3
"""Observe local Cargo test artifacts without building or executing any artifact.

This is a point-in-time inventory, not a native-test gate or build attestation.
Supply all active/finished relevant receipts so running packages remain pending.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PACKAGES = {
    "codex-hepta-agentd": "codex_hepta_agentd",
    "codex-hepta-evidence": "codex_hepta_evidence",
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def utc():
    return datetime.now(timezone.utc).isoformat()


def identity(value):
    return {
        key: getattr(value, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mode",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    }


def metadata(path):
    value = path.lstat()
    return {
        "path": str(path),
        **identity(value),
        "mtime_utc": datetime.fromtimestamp(value.st_mtime, timezone.utc).isoformat(),
        "is_symlink": stat.S_ISLNK(value.st_mode),
    }


def read_small(path):
    before = metadata(path)
    if not stat.S_ISREG(before["st_mode"]) or before["st_size"] > 32 * 1024 * 1024:
        raise ValueError(f"not a bounded regular observation: {path}")
    raw = path.read_bytes()
    if metadata(path) != before or len(raw) != before["st_size"]:
        raise ValueError(f"observation changed while read: {path}")
    return raw, {**before, "sha256": hashlib.sha256(raw).hexdigest()}


def git(repo, *arguments):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    return (
        subprocess.check_output(
            ["git", "-c", "core.fsmonitor=false", "-C", str(repo), *arguments], env=env
        )
        .decode()
        .strip()
    )


def source_context(repo):
    return {
        "commit": git(repo, "rev-parse", "HEAD"),
        "tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "dirty": bool(git(repo, "status", "--porcelain=v1")),
    }


def receipt_observation(path, repo):
    result = {"path": str(path), "usable_for_association": False}
    try:
        raw, file = read_small(path)
        record = json.loads(raw)
        command = record.get("command", [])
        package = command[command.index("-p") + 1] if "-p" in command else None
        result.update(
            file=file,
            package=package,
            recorded_status=record.get("status"),
            source_sha=record.get("source_sha"),
            tested_sha=record.get("tested_sha"),
            started_at=record.get("started_at"),
            finished_at=record.get("finished_at"),
        )
        if record.get("status") == "running":
            result["state"] = "pending; no partial log read"
            return result
        if record.get("status") != "passed":
            result["state"] = "not a successful completed receipt"
            return result
        before = record["before"]
        source = record["source_sha"]
        valid = (
            record.get("schema_version") == 1
            and package in PACKAGES
            and "--lib" in command
            and record.get("lane") == "source-head"
            and record.get("working_directory") == str(repo)
            and re.fullmatch(r"[0-9a-f]{40}", source) is not None
            and source == record.get("tested_sha") == before.get("commit")
            and before == record["after"]
            and before.get("dirty") is False
            and before.get("tree") == git(repo, "rev-parse", source + "^{tree}")
            and record.get("finished_at")
            and not record.get("error")
            and record.get("timed_out") is False
            and record.get("output_limit_exceeded") is False
            and all(
                type(record.get(key)) is int and record[key] == 0
                for key in ("returncode", "command_exit_code", "exit_code")
            )
        )
        if not valid:
            raise ValueError("receipt identity/completion fields do not match")
        log_name = record["log_file"]
        if not isinstance(log_name, str) or Path(log_name).name != log_name:
            raise ValueError("log_file is not a sibling basename")
        log, log_file = read_small(path.parent / log_name)
        if (
            log_file["sha256"] != record["log_sha256"]
            or len(log) != record["log_bytes"]
        ):
            raise ValueError("retained log hash/length mismatch")
        lines = ANSI.sub("", log.decode()).splitlines()
        result.update(
            usable_for_association=True,
            state="completed receipt and log observed",
            log=log_file,
            observed_passed_tests_recorded=record.get("observed_passed_tests"),
            running_lines=[
                line for line in lines if line.lstrip().startswith("Running ")
            ],
            nextest_starting_lines=[
                line for line in lines if line.lstrip().startswith("Starting ")
            ],
            test_roster_revalidated=False,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        result.update(state="unavailable or inconsistent", error=str(error))
    return result


def dep_info(path, repo):
    raw, file = read_small(path)
    text = raw.decode()
    roots = sorted(set(re.findall(r"(/workspace/scratch/[^\s:]+?/codex-rs/)", text)))
    prefix = str(repo / "codex-rs") + "/"
    examples = sorted(set(re.findall(re.escape(prefix) + r"[^\s\\:]+", text)))[:6]
    return {
        "file": file,
        "absolute_codex_source_roots": roots,
        "current_worktree_absolute_examples": examples,
        "relative_paths_are_not_absolute_provenance": True,
    }


def evidence_library_links(fp, target, repo):
    links = []
    dependencies = [
        row for row in fp.get("deps", []) if row[1] == "codex_hepta_evidence"
    ]
    for directory in sorted(
        (target / "debug/.fingerprint").glob("codex-hepta-evidence-*")
    ):
        marker_path = directory / "lib-codex_hepta_evidence"
        if not marker_path.is_file():
            continue
        marker, marker_file = read_small(marker_path)
        if re.fullmatch(rb"[0-9a-f]{16}", marker) is None:
            continue
        numeric = int.from_bytes(bytes.fromhex(marker.decode()), "little")
        matching = [row for row in dependencies if row[3] == numeric]
        if not matching:
            continue
        raw, file = read_small(marker_path.with_suffix(".json"))
        json.loads(raw)
        suffix = directory.name.removeprefix("codex-hepta-evidence-")
        links.append(
            {
                "dependency_rows": matching,
                "library_fingerprint": file,
                "marker": marker_file,
                "marker_hex": marker.decode(),
                "comparison": "dependency integer equals marker bytes interpreted little-endian",
                "dep_info": dep_info(
                    target / "debug/deps" / f"codex_hepta_evidence-{suffix}.d", repo
                ),
                "strength": "indirect Cargo dependency/path association; not compile-commit attestation",
            }
        )
    return links


def hash_stable_elf(path, watched):
    before = metadata(path)
    if (
        before["is_symlink"]
        or not stat.S_ISREG(before["st_mode"])
        or not before["st_mode"] & 0o111
    ):
        raise ValueError("artifact is not a regular executable file")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as handle:
        opened = identity(os.fstat(handle.fileno()))
        if any(opened[key] != before[key] for key in opened):
            raise ValueError("artifact replaced before read")
        if handle.read(4) != b"\x7fELF":
            raise ValueError("artifact does not have ELF magic")
        handle.seek(0)
        while block := handle.read(1024 * 1024):
            digest.update(block)
            count += len(block)
        if identity(os.fstat(handle.fileno())) != opened:
            raise ValueError("artifact changed during streaming hash")
    if metadata(path) != before or count != before["st_size"]:
        raise ValueError("artifact replaced or changed during read")
    if any(
        metadata(Path(item["path"])) != {k: v for k, v in item.items() if k != "sha256"}
        for item in watched
    ):
        raise ValueError("Cargo metadata changed during artifact read")
    return {
        **before,
        "sha256": digest.hexdigest(),
        "stable_during_read": True,
        "observed_at": utc(),
        "profile_classification": "local debug test artifact",
    }


def observe_package(package, stem, target, repo, receipts):
    associated = [r for r in receipts if r.get("package") == package]
    running = any(r.get("recorded_status") == "running" for r in associated)
    completed = [r for r in associated if r["usable_for_association"]]
    candidates = []
    for directory in sorted((target / "debug/.fingerprint").glob(package + "-*")):
        fingerprint = directory / f"test-lib-{stem}.json"
        if (
            not fingerprint.exists()
            and not (directory / f"output-test-lib-{stem}").exists()
        ):
            continue
        suffix = directory.name.removeprefix(package + "-")
        binary = target / "debug/deps" / f"{stem}-{suffix}"
        item = {
            "binary_path": str(binary),
            "state": "pending",
            "sha256": None,
            "compile_commit_attested": None,
            "exact_execution_binding_established": False,
        }
        candidates.append(item)
        if running:
            item["reason"] = (
                "a supplied receipt for this package is running; artifact not hashed"
            )
            continue
        if not completed:
            item["reason"] = (
                "no usable completed package receipt supplied; artifact not hashed"
            )
            continue
        if not fingerprint.is_file() or not binary.is_file():
            item["reason"] = (
                "test executable or completed test-lib fingerprint absent; not hashed"
            )
            continue
        try:
            raw, fp_file = read_small(fingerprint)
            fp = json.loads(raw)
            marker, marker_file = read_small(directory / f"test-lib-{stem}")
            if re.fullmatch(rb"[0-9a-f]{16}", marker) is None:
                raise ValueError("incomplete Cargo fingerprint marker")
            dependencies = dep_info(binary.with_suffix(".d"), repo)
            if binary.stat().st_mtime_ns > fp_file["st_mtime_ns"]:
                raise ValueError(
                    "binary is newer than completed fingerprint; possible rebuild"
                )
            library_links = evidence_library_links(fp, target, repo)
            watched = [fp_file, marker_file, dependencies["file"]]
            for link in library_links:
                watched.extend(
                    (
                        link["library_fingerprint"],
                        link["marker"],
                        link["dep_info"]["file"],
                    )
                )
            artifact = hash_stable_elf(binary, watched)
            item.update(
                state="stable completed test artifact observed",
                artifact=artifact,
                sha256=artifact["sha256"],
                fingerprint=fp_file,
                cargo_fingerprint_hex=marker.decode(),
                dep_info=dependencies,
                cargo_fingerprint_fields={
                    key: fp.get(key)
                    for key in (
                        "rustc",
                        "features",
                        "profile",
                        "path",
                        "target",
                        "rustflags",
                        "compile_kind",
                    )
                },
                evidence_library_dependency=[
                    row
                    for row in fp.get("deps", [])
                    if row[1] == "codex_hepta_evidence"
                ],
                evidence_library_links=library_links,
                receipt_associations=[],
            )
            for receipt in completed:
                exact_path = re.compile(
                    r"(?<![A-Za-z0-9_./-])"
                    + re.escape(str(binary))
                    + r"(?![A-Za-z0-9_./-])"
                )
                exact = [
                    line for line in receipt["running_lines"] if exact_path.search(line)
                ]
                basename = [
                    line
                    for line in receipt["running_lines"]
                    if binary.name in line and line not in exact
                ]
                start = datetime.fromisoformat(receipt["started_at"]).timestamp()
                finish = datetime.fromisoformat(receipt["finished_at"]).timestamp()
                modified = artifact["st_mtime_ns"] / 1e9
                if modified > finish:
                    strength = "file is newer than this receipt; current bytes cannot be assigned to that run"
                elif exact:
                    strength = (
                        "retained Running line names this path; hash observed later"
                    )
                else:
                    strength = (
                        "same package/target candidate only; no exact Running path"
                    )
                item["receipt_associations"].append(
                    {
                        "receipt": receipt["path"],
                        "source_sha_recorded": receipt["source_sha"],
                        "receipt_matches_requested_current_source": receipt[
                            "matches_requested_current_source"
                        ],
                        "exact_path_running_lines": exact,
                        "basename_running_lines": basename,
                        "association_strength": strength,
                        "mtime_within_receipt_interval": start <= modified <= finish,
                        "predates_receipt_possible_cache_reuse": modified < start,
                    }
                )
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            item.update(
                state="pending or inconsistent; no terminal artifact hash",
                sha256=None,
                reason=str(error),
            )
            item.pop("artifact", None)
    return {
        "package": package,
        "candidates": candidates,
        "successful_current_source_receipt_supplied": any(
            receipt["matches_requested_current_source"] for receipt in completed
        ),
        "state": "candidates observed"
        if candidates
        else "no test-lib artifact observed",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-root", type=Path, default=HERE.parent / "hepta")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("/workspace/scratch/aea25ba345a8/hepta-effects-agent/target"),
    )
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = (
            HERE / f"hepta-test-binary-observations-{args.source_sha[:12]}.json"
        )
    if not args.output.resolve().is_relative_to(HERE):
        parser.error("write observations only beneath this evidence-prep directory")
    started = utc()
    before = source_context(args.source_root)
    if before["commit"] != args.source_sha or before["dirty"]:
        parser.error("current clean source does not match --source-sha")
    receipts = [receipt_observation(path, args.source_root) for path in args.receipt]
    for receipt in receipts:
        receipt["matches_requested_current_source"] = (
            receipt.get("source_sha") == args.source_sha
        )
    packages = [
        observe_package(package, stem, args.target_dir, args.source_root, receipts)
        for package, stem in PACKAGES.items()
    ]
    after = source_context(args.source_root)
    disk = os.statvfs(args.target_dir)
    report = {
        "schema": "hepta-local-test-binary-observations-v1",
        "started_at": started,
        "finished_at": utc(),
        "requested_current_source_sha": args.source_sha,
        "source_root": str(args.source_root),
        "target_dir": str(args.target_dir),
        "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_before": before,
        "source_after": after,
        "source_stable": before == after,
        "receipts": receipts,
        "packages": packages,
        "excluded_target_kinds": ["bin", "test-integration-test"],
        "excluded_target_files_inspected": False,
        "native_test_pass_proof": False,
        "deployment_release_binary": False,
        "independent_build_or_deployment": False,
        "filesystem_observation": {
            "f_bfree_bytes": disk.f_bfree * disk.f_frsize,
            "f_bavail_bytes": disk.f_bavail * disk.f_frsize,
        },
        "static_cache_relocation_record": str(
            HERE.parent / "native-static-cache-relocation.json"
        ),
        "obsolete_runtime_cache_backup_record": str(
            HERE.parent / "obsolete-runtime-cache-backup.json"
        ),
        "limits": [
            "Fingerprints and mtimes are local association evidence, not signed build provenance.",
            "Relative .d source paths are not absolute worktree attribution.",
            "A later stable binary hash is not its hash at the earlier test execution.",
            "Missing Running paths stay missing; nextest lists are not inferred.",
            "The reused target may contain multiple source trees and cached dependencies.",
            "Zero f_bavail is not zero physical free space; f_bfree is recorded separately.",
            "Exit zero means an observation file was written, not that native tests passed.",
        ],
    }
    with tempfile.NamedTemporaryFile(
        "w", dir=HERE, prefix=".hepta-binary-observation-", delete=False
    ) as output:
        temporary = Path(output.name)
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    try:
        # Atomic publication without overwriting an earlier source/hash record.
        os.link(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "source_stable": before == after,
                "native_test_pass_proof": False,
            }
        )
    )


if __name__ == "__main__":
    main()
