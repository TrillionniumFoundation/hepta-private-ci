"""Pack exactly the frozen Windows44 safe roster without executing its payload."""

from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile


ROOT = Path("/workspace/scratch/3f6a885bb83c")
HERE = Path("/dev/shm/ndu_windows44_checkpoint_20261107")
ROSTER = HERE / "INPUT_ROSTER_v2.json"
ROSTER_SHA = "14df96951737d091acda46a1ec4c167e31f9d4244ad3dfd875bcceb71f194146"
OUTPUT = HERE / "packet_v2"
CHECKS = HERE / "checks_v2"
TEMPLATE = ROOT / "round3_native/access_terminal_checkpoint_inputs/reviewed_restore.py"
TEMPLATE_SHA = "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d"
OLD_SEAL = "f4d8ee695d5928ae3543e7c13e8198ee3ee01228b4e5d0bd78345af6126a6089"
REMOTE = "experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/evidence/windows_mutation44_terminal_checkpoint_20261107"


def need(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": digest(raw),
        "git_blob_sha": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def read_reader():
    spec = importlib.util.spec_from_file_location(
        "fixed_windows44_evidence_reader", OUTPUT / "restore.py"
    )
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def verify_only():
    index, members = read_reader().read_package(OUTPUT)
    for row in index["files"]:
        source = Path(row["source_path"])
        metadata = source.lstat()
        need(stat.S_ISREG(metadata.st_mode) and not source.is_symlink(), "SOURCE_KIND")
        need(source.read_bytes() == members[row["path"]], "EXACT_ORIGINAL_BYTES")
        need(
            format(stat.S_IMODE(metadata.st_mode), "04o")
            == row["source_permission_bits"]
            and format(metadata.st_mode, "06o") == row["source_stat_mode"],
            "SOURCE_MODE",
        )
    print(
        json.dumps(
            {
                "files": len(members),
                "bytes": sum(map(len, members.values())),
                "optimized_python": not __debug__,
                "exact_members_bytes_and_source_modes": True,
                "disk_extraction": False,
                "archived_source_executed": False,
                "native_execution": False,
            }
        )
    )


def main():
    need(not OUTPUT.exists() and not CHECKS.exists(), "NEW_PACKET_DESTINATIONS")
    roster_raw = ROSTER.read_bytes()
    need(digest(roster_raw) == ROSTER_SHA, "FROZEN_ROSTER")
    selection = json.loads(roster_raw)
    need(
        selection["packet_original_count"] == 183
        and selection["packet_original_bytes"] == 1895194,
        "EXACT_ROSTER_SCOPE",
    )
    rows = [
        {
            "path": row["archive_name"],
            "source_path": row["source_path"],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
            "source_permission_bits": row["mode"],
            "source_stat_mode": "100644",
        }
        for row in selection["packet_files"]
    ]
    need(
        len(rows) == 183 and sum(row["bytes"] for row in rows) == 1895194,
        "EXACT_ROSTER_TOTAL",
    )
    plain = [
        row
        for row in selection["separate_plain_publication"]
        if "/analysis/" in row["remote_path"]
    ]
    need(
        {Path(row["source_path"]).name for row in plain}
        == {"bind_call_chain45.py", "CALL_CHAIN_AND_NEXT_UNIT.md"},
        "TWO_PLAIN_ANALYSIS_INPUTS",
    )
    plain_before = {
        Path(row["source_path"]): Path(row["source_path"]).read_bytes() for row in plain
    }
    for row in plain:
        need(
            identity(plain_before[Path(row["source_path"])])["sha256"] == row["sha256"]
            and row["mode"] == "0644",
            "PLAIN_SOURCE_IDENTITY",
        )
    all_plain_bytes = []
    for row in selection["separate_plain_publication"]:
        value = Path(row["source_path"]).read_bytes()
        need(
            len(value) == row["bytes"] and digest(value) == row["sha256"],
            "ALL_PLAIN_IDENTITY",
        )
        all_plain_bytes.append(value)
    need(len(all_plain_bytes) == 6, "SIX_PLAIN_FILES")
    originals, inventory = {}, []
    for row in sorted(rows, key=lambda item: item["path"]):
        path = Path(row["source_path"])
        metadata = path.lstat()
        need(
            stat.S_ISREG(metadata.st_mode)
            and not path.is_symlink()
            and metadata.st_nlink == 1,
            "REGULAR_SOURCE",
        )
        need(
            path.suffix
            not in (".log", ".zip", ".rmeta", ".rlib", ".exe", ".dll", ".so", ".pyc")
            and row["source_permission_bits"] == "0644",
            "SAFE_ROSTER_DATA",
        )
        raw = path.read_bytes()
        need(all(raw != value for value in all_plain_bytes), "PLAIN_FINAL_BYTE_ALIAS")
        need(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "FROZEN_BYTES")
        need(
            format(stat.S_IMODE(metadata.st_mode), "04o")
            == row["source_permission_bits"]
            and format(metadata.st_mode, "06o") == row["source_stat_mode"],
            "FROZEN_MODES",
        )
        need(row["path"] not in originals, "DUPLICATE_ARCHIVE_NAME")
        originals[row["path"]] = raw
        inventory.append(
            {
                key: row[key]
                for key in (
                    "path",
                    "source_path",
                    "bytes",
                    "sha256",
                    "source_permission_bits",
                    "source_stat_mode",
                )
            }
        )
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, raw in originals.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(raw), 0o644
            member.uid = member.gid = member.mtime = 0
            member.uname = member.gname = ""
            archive.addfile(member, io.BytesIO(raw))
    tar = memory.getvalue()
    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as archive:
        actual = list(archive)
        need(
            len(actual) == len(inventory)
            and all(
                member.isreg() and not member.linkname and member.mode == 0o644
                for member in actual
            ),
            "INERT_TAR_HEADERS",
        )
    compressed = lzma.compress(tar, preset=6)
    OUTPUT.mkdir()
    CHECKS.mkdir()
    parts = []
    for offset in range(0, len(compressed), 440000):
        segment = compressed[offset : offset + 440000]
        wrapped = gzip.compress(segment, compresslevel=1, mtime=0)
        need(len(wrapped) <= 450000, "PART_BOUND")
        name = f"native-evidence.tar.xz.part{len(parts):03d}.gz"
        (OUTPUT / name).write_bytes(wrapped)
        parts.append(
            {
                "name": name,
                "bytes": len(wrapped),
                "sha256": digest(wrapped),
                "segment_bytes": len(segment),
                "segment_sha256": digest(segment),
            }
        )
    need(len(parts) == 1, "SINGLE_BOUNDED_GZIP_PART")
    index = {
        "format": "native-blocker-evidence-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_bytes": len(tar),
        "archive_sha256": digest(tar),
        "compressed_bytes": len(compressed),
        "compressed_sha256": digest(compressed),
        "parts": parts,
        "files": inventory,
        "scope": "Windows44 source history, direct prepared/ACL case passes and unchanged production failures; Windows45 conditional source-only report; P0 remains open",
        "excluded": selection["excluded_private_identity_only"],
        "plain_source_references": selection["separate_plain_publication"],
        "identity_only_audit_implementations": selection[
            "omitted_implementation_identity_only"
        ],
        "input_roster_sha256": ROSTER_SHA,
        "roster_revision": selection["revision_from"],
        "plain_byte_exclusion": selection["plain_byte_exclusion"],
        "published_plain_algorithm_PRs": [5279, 5280],
        "source_restore": "Inert regular 0644; original permission/stat modes and original source_path are evidence records",
        "lossless_boundary": "Exactly the selected source, finite records and APIs. No private console or execution ZIP content is included or reconstructed.",
    }
    write(OUTPUT / "INDEX.json", index)
    seal = digest((OUTPUT / "INDEX.json").read_bytes())
    template = TEMPLATE.read_bytes()
    need(
        digest(template) == TEMPLATE_SHA and template.count(OLD_SEAL.encode()) == 1,
        "CANONICAL_READER_PIN",
    )
    reader_bytes = template.replace(OLD_SEAL.encode(), seal.encode())
    need(
        reader_bytes.replace(seal.encode(), OLD_SEAL.encode()) == template,
        "ONLY_SEAL_DELTA",
    )
    (OUTPUT / "restore.py").write_bytes(reader_bytes)
    before = {p.name: identity(p.read_bytes()) for p in OUTPUT.iterdir()}
    actual_index, members = read_reader().read_package(OUTPUT)
    need(actual_index == index and members == originals, "EXACT_MEMORY_ROUNDTRIP")
    command = [
        sys.executable,
        "-B",
        "-O",
        str(Path(__file__).resolve()),
        "--verify-only",
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True)
    (CHECKS / "roundtrip.stdout").write_bytes(result.stdout)
    (CHECKS / "roundtrip.stderr").write_bytes(result.stderr)
    need(result.returncode == 0, "OPTIMIZED_READER_EXIT")
    verified = json.loads(result.stdout)
    need(
        verified["optimized_python"] is True and verified["files"] == len(inventory),
        "OPTIMIZED_READER_SCOPE",
    )
    need(
        before == {p.name: identity(p.read_bytes()) for p in OUTPUT.iterdir()},
        "BUNDLE_INPUT_CHANGED",
    )
    write(
        OUTPUT / "ROUNDTRIP.json",
        {
            "ordinary_memory_roundtrip_exact": True,
            "optimized": {
                "argv": command,
                "exit_code": result.returncode,
                "stdout": verified,
                "stderr": result.stderr.decode(),
            },
            "files": len(inventory),
            "bytes": sum(map(len, originals.values())),
            "index_sha256": seal,
            "bundle_inputs_unchanged": True,
            "source_path_and_modes_compared": True,
            "on_disk_extraction": False,
            "restored_on_disk_modes_tested": False,
            "archived_source_or_native_executed": False,
        },
    )
    (OUTPUT / "README.md").write_text(
        f"# Windows44 mutation-mask native evidence\n\nThis additive packet preserves exactly {len(inventory)} selected safe originals and {sum(map(len, originals.values())):,} bytes. The source is PR #5270, head 883b85f2c0198e9373022e8082d866c080178c0a. Its original run 42352197933, attempt 1, ended in failure. The owning Windows sandbox target failed after 114.1 seconds.\n\nThe prepared full-restriction probe and three specific ACL units passed. Both original production regressions failed. The outside deletion calls in the broad regression returned success; the legacy tuple remained unchanged. Zero FULL records were emitted: F0-F4 numeric, access and cleanup fields remain unobserved. Repeated case lines are not independent trials. Product P0 and old-ACL migration remain open.\n\nThe four finalized observation and independent root audit algorithms are plain source in PRs #5279 and #5280 under observer/ and root/. The additional analysis/bind_call_chain45.py and analysis/CALL_CHAIN_AND_NEXT_UNIT.md are also plain source. They are excluded from the compressed member roster. Historical failed parser predecessors and their failure receipts remain in the packet.\n\nRun `python -B restore.py /absolute/path/to-a-new-directory` with Python 3.12 or later. The destination must not exist. The canonical reader differs only in its fixed INDEX seal, {seal}. It checks bounded gzip/xz data, complete unique regular membership and all byte hashes before writing inert 0644 files. It does not execute archived source.\n\nINDEX keeps each real source_path, exact archive alias, original permission/stat modes and byte identity. No original was moved. Complete ordinary and optimized Python memory roundtrips compared all 183 members and modes. No duplicate extraction tree was created. The original reader remains unchanged except for the seal literal.\n\nThe lossless claim covers only these exact selected safe members. Private original console bytes and the initial LF-normalized capture, execution ZIPs, signed transfer URLs, binaries and broad environment output are excluded. No excluded bytes are reconstructed or encoded. Audit algorithms requiring the excluded console cannot be replayed fully from this packet. Three historical source-review implementations are identity-referenced only; their receipts do not imply those implementations are included.\n\nThe Windows45 report is a conditional argument about the present raw token interface, not a general impossibility claim about Windows. It creates no production authority and launches no new native experiment. Earlier source and evidence packets remain unchanged. The initial 184-member packet was not published: its path-only exclusion admitted one 8,888-byte alias identical to the final plain assertion parser. This version removes only that redundant alias. The original packet, alias and two genuinely failed parser predecessors remain preserved.\n"
    )
    ruff = str(ROOT / "round3_ci/ruff_tooling/ruff")
    config = str(ROOT / "round3_ci/ruff_tooling/pyproject.toml")
    checks = []
    for argv in (
        [ruff, "format", "--check", "--config", config, str(OUTPUT / "restore.py")],
        [ruff, "check", "--config", config, str(OUTPUT / "restore.py")],
    ):
        done = subprocess.run(argv, capture_output=True, text=True)
        checks.append(
            {
                "argv": argv,
                "exit_code": done.returncode,
                "stdout": done.stdout,
                "stderr": done.stderr,
            }
        )
        need(done.returncode == 0, "READER_STYLE")
    write(
        OUTPUT / "READER_CHECK.json",
        {
            "template": str(TEMPLATE),
            "template_sha256": TEMPLATE_SHA,
            "reader": identity(reader_bytes),
            "only_index_seal_changed": True,
            "checks": checks,
        },
    )
    stage = CHECKS / "codespell_stage"
    stage.mkdir()
    configs = []
    for name in (".codespellrc", ".codespellignore", ".codespell-exclude-lines"):
        path = ROOT / "hepta-research" / name
        shutil.copyfile(path, stage / name)
        configs.append({"path": str(path), **identity(path.read_bytes())})
    for path in OUTPUT.iterdir():
        shutil.copyfile(path, stage / path.name)
    for row in plain:
        source = Path(row["source_path"])
        target = stage / "analysis" / source.name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
    argv = [
        sys.executable,
        "-B",
        "-m",
        "codespell_lib",
        "--ignore-words",
        ".codespellignore",
        "--skip",
        "./.git",
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "tooling/codespell-2.4.3") + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    done = subprocess.run(
        argv, cwd=stage, env=environment, capture_output=True, text=True
    )
    write(
        OUTPUT / "CODESPELL.json",
        {
            "argv": argv,
            "cwd": str(stage),
            "exit_code": done.returncode,
            "stdout": done.stdout,
            "stderr": done.stderr,
            "configs": configs,
            "new_ignores_or_skips": False,
        },
    )
    need(done.returncode == 0, "FULL_PACKET_CODESPELL")
    shutil.copyfile(OUTPUT / "CODESPELL.json", stage / "CODESPELL.json")
    final = subprocess.run(
        argv, cwd=stage, env=environment, capture_output=True, text=True
    )
    write(
        CHECKS / "FINAL_CODESPELL.json",
        {
            "argv": argv,
            "cwd": str(stage),
            "exit_code": final.returncode,
            "stdout": final.stdout,
            "stderr": final.stderr,
        },
    )
    need(final.returncode == 0, "FINAL_FULL_PACKET_CODESPELL")
    for row in inventory:
        need(
            Path(row["source_path"]).read_bytes() == originals[row["path"]],
            "SOURCE_CHANGED_DURING_PACKAGING",
        )
    files = []
    for path in sorted(OUTPUT.iterdir()):
        raw = path.read_bytes()
        need(
            len(raw) <= 450000 and (stage / path.name).read_bytes() == raw,
            "FINAL_PUBLICATION_BYTES",
        )
        files.append(
            {
                "path": REMOTE + "/" + path.name,
                "local_path": str(path),
                **identity(raw),
                "mode": "100644",
                "encoding": "base64" if path.suffix == ".gz" else "utf-8",
            }
        )
    for row in plain:
        path = Path(row["source_path"])
        raw = path.read_bytes()
        need(
            raw == plain_before[path]
            and (stage / "analysis" / path.name).read_bytes() == raw,
            "PLAIN_SOURCE_UNCHANGED",
        )
        files.append(
            {
                "path": REMOTE + "/analysis/" + path.name,
                "local_path": str(path),
                **identity(raw),
                "mode": "100644",
                "encoding": "utf-8",
            }
        )
    manifest = {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "repo_directory": REMOTE,
        "index_sha256": seal,
        "files": files,
        "remote_mutations_performed": False,
        "source_packet": "windows44",
        "qualification": "EXACT_SELECTED_SAFE_BYTES_MEMORY_ROUNDTRIP; PREPARED_AND_THREE_ACL_CASES_PASS; TWO_PRODUCTION_CASES_FAIL; P0_OPEN",
        "parent_binding": "ROOT_TO_BIND_CURRENT_EVIDENCE_MAIN",
        "original_files": len(inventory),
        "original_bytes": sum(map(len, originals.values())),
        "nonmechanical_publication_lines": len(reader_bytes.splitlines())
        + len((OUTPUT / "README.md").read_text().splitlines())
        + sum(len(raw.splitlines()) for raw in plain_before.values()),
        "final_spelling_check": str(CHECKS / "FINAL_CODESPELL.json"),
    }
    need(manifest["nonmechanical_publication_lines"] <= 800, "PUBLICATION_LINE_BOUND")
    manifest["source_builder_identity"] = identity(Path(__file__).read_bytes())
    manifest["builder_review"] = str(HERE / "BUILDER_V2_CHANGE_REVIEW.json")
    manifest["published_plain_algorithms"] = [5279, 5280]
    path = HERE / "WINDOWS44_TERMINAL_CHECKPOINT_PUBLICATION_MANIFEST_v2.json"
    write(path, manifest)
    print(
        json.dumps(
            {
                "manifest": str(path),
                **identity(path.read_bytes()),
                "original_files": len(inventory),
                "original_bytes": manifest["original_bytes"],
                "parts": len(parts),
                "max_part_bytes": max(row["bytes"] for row in parts),
                "publication_files": len(files),
                "nonmechanical_publication_lines": manifest[
                    "nonmechanical_publication_lines"
                ],
            }
        )
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--verify-only"]:
        verify_only()
    else:
        main()
