#!/usr/bin/env python3
"""Execute one explicitly authorized B epoch. The distributed template cannot run."""

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import traceback
import zlib

from b16_guard import SourceGuard, identity, need, record, same_record, validate_binding
from b16_capacity import cache_and_capacity
from b16_locks import bazel_registration, lock_gate
from b16_native import Native, graph

HERE = Path(__file__).resolve().parent
EPOCHS = ["foundation", "driver", "pool", "checkpoint", "owning"]


def export_evidence(guard):
    files = [p for p in sorted(guard.out.rglob("*")) if p.is_file() and not p.name.endswith(".index")]
    members = []
    for index, p in enumerate(files):
        row = record(p)
        if row["bytes"] > 44000:
            raw = p.read_bytes()
            compressed = zlib.compress(raw, 9)
            directory = guard.out / "retrieval-parts" / str(index).zfill(4)
            directory.mkdir(parents=True, exist_ok=False)
            chunks = []
            for offset in range(0, len(compressed), 44000):
                part = compressed[offset:offset + 44000]
                q = directory / (str(len(chunks)).zfill(4) + ".json")
                chunk = {"offset": offset, "bytes": len(part), "sha256": identity(part)["sha256"],
                         "base64": base64.b64encode(part).decode()}
                q.write_text(json.dumps(chunk) + "\n")
                chunks.append({"offset": offset, **record(q)})
            row["compressed_retrieval"] = {"format": "zlib", "raw_crc32": zlib.crc32(raw),
                "compressed_bytes": len(compressed), "compressed_sha256": identity(compressed)["sha256"], "chunks": chunks}
        members.append(row)
    guard.save("complete-evidence-index", {"files": members, "complete_original_files_retained": True,
                "partial_stdout_is_not_terminal_evidence": True, "decode": "Concatenate decoded chunk payloads by offset, verify compressed hash, zlib.decompress, then verify original bytes/SHA256/CRC32."})


def execute_scopes(native, operation):
    for name in operation.get("before", []):
        native.g.apply(name)
    for scope in operation["scopes"]:
        native.run_scope(scope)


def negative_with_finally(native, operation):
    need(operation["restore"], "negative missing approved restoration")
    # Apply fully checked counterfactual before entering the test try/finally.
    # A partial source write is never overwritten by a blind cleanup/reset.
    for name in operation["before"]:
        native.g.apply(name)
    negative_tree = native.g.source
    primary, restore_error = None, None
    try:
        for scope in operation["scopes"]:
            native.run_scope(scope)
    except BaseException as error:
        primary = error
    finally:
        try:
            need(native.g.source == negative_tree, "negative source identity moved")
            native.g.guard(operation["id"] + "-finally-owned-negative")
            native.g.apply(operation["restore"])
        except BaseException as error:
            restore_error = error
        native.g.save(operation["id"] + "-finally-receipt", {
            "negative_tree": negative_tree, "restored_tree": native.g.source if restore_error is None else None,
            "restoration": operation["restore"], "causal_gate_passed": primary is None,
            "primary_error": repr(primary) if primary is not None else None,
            "restore_error": repr(restore_error) if restore_error is not None else None,
            "next_phase_permitted": primary is None and restore_error is None})
    if restore_error is not None:
        raise RuntimeError("negative restoration refused/failed; inspect both saved errors") from restore_error
    if primary is not None:
        raise primary


def validate_previous(binding, manifest_sha):
    epoch = binding["authorized_epoch"]
    if epoch == "foundation":
        return None
    pin = binding["previous_epoch_receipt"]
    need(same_record(pin["path"], pin), "previous epoch receipt bytes changed")
    previous = json.loads(Path(pin["path"]).read_bytes())
    need(previous["status"] == "QUALIFIED" and previous["epoch"] == EPOCHS[EPOCHS.index(epoch) - 1], "wrong/failed previous epoch")
    need(previous["final_A_tree"] == binding["final_A_tree"] and previous["payload_sha256"] == manifest_sha,
         "previous epoch belongs to another base/payload")
    need(previous["final_tree"] == binding["initial_tree"], "epoch source continuity broken")
    need({p: {k: r[k] for k in ("bytes", "sha256")} for p, r in previous["locks"].items()} ==
         {p: {k: r[k] for k in ("bytes", "sha256")} for p, r in binding["locks"].items()}, "epoch lock continuity broken")
    need(previous["ordinary_head"] == binding["ordinary_head"] and
         all(previous["ordinary_index"][k] == binding["ordinary_index"][k] for k in ("bytes", "sha256")),
         "ordinary repository identity moved between epochs")
    for field in ("target_directory", "bazel_cache_directory", "bazel_cache_owner", "A_helper_basename_roster", "last_tested_A_tree", "last_tested_A_to_final_A_review"):
        need(previous[field] == binding[field], "epoch cache/helper contract changed: " + field)
    need(previous["last_tested_A_artifacts"]["sha256"] == binding["last_tested_A_artifacts"]["sha256"], "last-tested A artifact identity changed")
    need(previous["metadata_graph"] == graph(json.loads(Path(binding["baseline_metadata"]["path"]).read_bytes())),
         "next epoch metadata differs from prior qualified graph")
    return previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--epoch", choices=EPOCHS, required=True)
    args = parser.parse_args()
    binding = json.loads(args.binding.read_bytes())
    manifest_bytes = (HERE / "payload-manifest.json").read_bytes()
    manifest, manifest_sha = json.loads(manifest_bytes), identity(manifest_bytes)["sha256"]
    validate_binding(binding, manifest_sha)
    need(binding["authorized_epoch"] == args.epoch, "epoch argument not authorized")
    # File-only checks happen before any subprocess, directory creation or source mutation.
    integrity = json.loads((HERE / "runner-integrity.json").read_bytes())
    need(identity((HERE / "runner-integrity.json").read_bytes())["sha256"] == binding["approved_runner_integrity_sha256"], "runner approval identity mismatch")
    for row in integrity["files"]:
        need(same_record(HERE / row["path"], row), "runner/input file drift: " + row["path"])
    sources = {}
    for part in manifest["payloads"]:
        p = HERE / part["path"]
        need(same_record(p, part), "source payload chunk changed")
        objects = json.loads(p.read_bytes())
        need(not set(objects) & set(sources), "duplicate source object across chunks")
        for blob, value in objects.items():
            need(identity(value["text"].encode()) == {k: value[k] for k in ("blob", "bytes", "sha256")} and blob == value["blob"], "source object bytes changed")
        sources.update(objects)
    epoch_file = next(x for x in manifest["epoch_files"] if x["path"] == "epoch-" + args.epoch + ".json")
    need(same_record(HERE / epoch_file["path"], epoch_file), "phase manifest drift")
    operations = json.loads((HERE / epoch_file["path"]).read_bytes())["operations"]
    need(same_record(binding["baseline_metadata"]["path"], binding["baseline_metadata"]), "baseline metadata receipt drift")
    baseline = json.loads(Path(binding["baseline_metadata"]["path"]).read_bytes())
    validate_previous(binding, manifest_sha)
    capacity = cache_and_capacity(binding, baseline)
    tree, out, target = (Path(binding[k]).resolve() for k in ("source_directory", "evidence_directory", "target_directory"))
    need(tree.is_dir() and not out.is_relative_to(tree) and not target.is_relative_to(tree), "source/evidence/target separation invalid")
    need(not out.exists() and out.parent.is_dir(), "use a new existing-parent evidence directory")
    need(platform.system() == "Linux" and platform.machine() == "x86_64", "this concrete B gate is Linux x86_64 only")
    for tool in binding["tools"]:
        need(same_record(tool["path"], tool), "approved tool identity drift")
    env = dict(os.environ)
    env.update(binding["environment"])
    for tool in binding["tools"]:
        selected = shutil.which(tool["name"], path=env.get("PATH"))
        need(selected is not None and Path(selected).resolve() == Path(tool["path"]).resolve(),
             "PATH does not select the pinned tool: " + tool["name"])
    need(env.get("CARGO_TARGET_DIR") == str(target) and env.get("RUSTUP_TOOLCHAIN") == "1.95.0" and
         env.get("NEXTEST_PROFILE") == "local" and env.get("CARGO_INCREMENTAL") == "0", "runtime environment differs from reviewed lane")
    need(not any(env.get(k) for k in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "NEXTEST_FILTERSET", "NEXTEST_RETRIES")), "unreviewed compilation/test override")
    out.mkdir(exist_ok=False)
    with (out.parent / ".b16-sole-mutator.lock").open("a+b") as lane_lock:
        fcntl.flock(lane_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        guard = SourceGuard(binding, manifest, sources, out, env)
        native = Native(guard, baseline)
        error = None
        status = "INCOMPLETE"
        try:
            guard.guard("epoch-entry")
            guard.save("target-reuse-and-capacity", capacity)
            for recipe in binding["recipe_sources"]:
                need(same_record(guard.check_path(recipe["path"]), recipe), "original recipe source drift: " + recipe["path"])
            if args.epoch == "foundation":
                for path, blob in manifest["initial_preimages"].items():
                    p = guard.check_path(path)
                    need((not p.exists()) if blob is None else p.is_file() and identity(p.read_bytes())["blob"] == blob,
                         "final A changed an original B preimage; rebase/review instead of overwriting: " + path)
                need(not (tree / "codex-rs/third_party/sqlx-sqlite-0.9.0").exists(), "native token was adopted before foundation negatives")
            guard.save("native-host-receipt", {"uname": list(platform.uname()), "source": guard.source,
                        "final_A_tree": binding["final_A_tree"], "tool_files": binding["tools"],
                        "cargo_profile": "dev-small", "nextest_profile": "local", "retries": 0})
            version = native.command("rustc-version", ["rustc", "-vV"], separate=True)
            need(version["exit_code"] == 0 and "release: 1.95.0" in Path(version["stdout"]["path"]).read_text(), "actual Rust toolchain differs")
            version = native.command("bazel-version", ["bazel", "--version"], separate=True)
            need(version["exit_code"] == 0 and Path(version["stdout"]["path"]).read_text().strip() == "bazel " + (tree / ".bazelversion").read_text().strip(), "actual Bazel differs from the repository pin")
            native.read_metadata("epoch-entry")
            for operation in operations:
                kind = operation["kind"]
                if kind == "apply":
                    guard.apply(operation["delta"])
                elif kind == "scopes":
                    execute_scopes(native, operation)
                elif kind == "negative":
                    negative_with_finally(native, operation)
                elif kind == "locks":
                    lock_gate(native, operation)
                elif kind == "bazel-registration":
                    bazel_registration(native, operation)
                elif kind == "owning":
                    for package in operation["packages"]:
                        native.run_scope({"label": "B20-owning-" + package, "package": package, "exact_names": None,
                                          "supports": [], "authored_argv": ["just", "test", "-p", package, "--lib", "--locked", "--retries", "0"]})
                elif kind == "hygiene":
                    for label, argv in [("B20-fix", ["just", "fix", "--locked", "--profile", "dev-small", "-p", "sqlx-sqlite", "-p", "codex-state", "-p", "codex-hepta-memory"]),
                                        ("B20-fmt", ["just", "fmt"])]:
                        result = native.command(label, argv, hygiene=True)
                        need(result["exit_code"] == 0, "original hygiene failed")
                    from b16_locks import private_bazel
                    with private_bazel(native, "B20-final-lock-check"):
                        result = native.command("B20-final-lock-check", ["just", "bazel-lock-check"], cwd=tree, separate=True)
                        need(result["exit_code"] == 0, "final original lock check failed")
                else:
                    raise RuntimeError("unknown operation")
            status = "AWAITING_HYGIENE_DIFF_REVIEW" if args.epoch == "owning" else "QUALIFIED"
        except BaseException as caught:
            error = {"type": type(caught).__name__, "message": str(caught), "traceback": traceback.format_exc()}
        finally:
            final_guard = None
            try:
                guard.guard("epoch-final")
                final_guard = True
            except BaseException as caught:
                final_guard = {"type": type(caught).__name__, "message": str(caught)}
                status = "SOURCE_GUARD_FAILED"
            receipt = {"schema": "hepta-b16-native-epoch-receipt-v1", "epoch": args.epoch, "status": status,
                       "display_namespace": "B16/phase", "internal_stage_ids_are_not_original_blocker_ids": True,
                       "final_A_tree": binding["final_A_tree"], "initial_tree": binding["initial_tree"],
                       "final_tree": guard.source, "ordinary_head": binding["ordinary_head"],
                       "ordinary_index": binding["ordinary_index"], "locks": guard.locks,
                       "payload_sha256": manifest_sha, "runner_integrity_sha256": binding["approved_runner_integrity_sha256"],
                       "target_directory": binding["target_directory"], "bazel_cache_directory": binding["bazel_cache_directory"],
                       "bazel_cache_owner": binding["bazel_cache_owner"], "last_tested_A_artifacts": binding["last_tested_A_artifacts"],
                       "last_tested_A_tree": binding["last_tested_A_tree"],
                       "last_tested_A_to_final_A_review": binding["last_tested_A_to_final_A_review"],
                       "A_helper_basename_roster": binding["A_helper_basename_roster"],
                       "metadata_graph": native.expected_graph, "error": error, "final_guard": final_guard,
                       "commands": native.commands, "reviews": [{k: v for k, v in x.items() if k != "cases"} for x in native.reviews],
                       "post_hygiene_tests_run": False, "platform_matrix_or_B16_closed": False,
                       "open_limits": manifest["open_limits"]}
            guard.save("epoch-terminal", receipt)
            export_evidence(guard)
        if error or status == "SOURCE_GUARD_FAILED":
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
