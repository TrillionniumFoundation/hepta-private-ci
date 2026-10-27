"""Prepare typed memory models, then seal committed execution code before held use.

Neither subcommand reads held wording. The seal copies the expected held hashes
from the committed protocol. Selected router vocabularies are loaded as model
artifacts; training/selection language records are never used to fit memory cells.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import time

from v6.artifacts import durable_bytes
from v6.contracts import canonical
from v6.encoder import MiniLMEncoder
from v6.router import Router
from v6.runtime import train_snapshot
from v6.study_data import create_sources


PROJECT = Path(__file__).resolve().parent
REPOSITORY = PROJECT.parents[1]
TRAINING_FILES = (
    "prepare_run.py",
    "v6/cells.py",
    "v6/values.py",
    "v6/store.py",
    "v6/artifacts.py",
    "v6/runtime.py",
    "v6/contracts.py",
    "v6/study_data.py",
    "v6/encoder.py",
    "v6/router.py",
)


def identity(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("not an admitted regular file: " + str(path))
    checksum, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
            size += len(block)
    return {"sha256": checksum.hexdigest(), "bytes": size}


def inventory(root):
    root = Path(root)
    paths = sorted(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("symlink in artifact inventory")
    return {
        str(path.relative_to(root)): identity(path) for path in paths if path.is_file()
    }


def verify_files(root, files):
    root = Path(root).resolve()
    for name, expected in files.items():
        path = root / name
        if path.resolve().is_relative_to(root) is False or identity(path) != expected:
            raise ValueError("frozen file differs: " + name)


def dump(path, value):
    durable_bytes(path, canonical(value) + b"\n")


def load(path):
    return json.loads(Path(path).read_bytes())


def git_head():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
    ).strip()


def code_bindings():
    paths = (
        list(PROJECT.glob("*.py"))
        + list((PROJECT / "v6").glob("*.py"))
        + list((PROJECT / "tests").glob("*.py"))
    )
    paths += [
        path
        for name in ("qualify.py", "make_fixture.py")
        if (path := PROJECT / "native" / name).is_file()
    ]
    paths += [
        PROJECT / "PROTOCOL.json",
        PROJECT.parent / "memory-cell-v2" / "MODEL_SOURCE.json",
    ]
    return {str(path.relative_to(REPOSITORY)): identity(path) for path in sorted(paths)}


def verify_committed(files, commit):
    if git_head() != commit:
        raise ValueError("execution HEAD differs from frozen source commit")
    verify_files(REPOSITORY, files)
    for name, expected in files.items():
        content = subprocess.check_output(
            ["git", "show", commit + ":" + name], cwd=REPOSITORY
        )
        if {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        } != expected:
            raise ValueError("execution source is not committed: " + name)
    if code_bindings() != files:
        raise ValueError("execution source inventory changed")


def prepare(routers, encoder_paths, plan_path, output):
    started, cpu = time.perf_counter(), time.process_time()
    output, routers = Path(output).resolve(), Path(routers).resolve()
    plan = load(plan_path)
    if plan != load(PROJECT / "PROTOCOL.json") or plan["memory_fit"]["dimension"] != 64:
        raise ValueError(
            "prepare requires the repository's frozen protocol and supported dimensions"
        )
    if (
        plan["expected_records"]
        != len(plan["seeds"])
        * len(plan["domains"])
        * len(plan["full_arms"])
        * plan["templates"]
    ):
        raise ValueError("execution plan count is inconsistent")
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "execution_plan.json", plan)
    training_sources = {name: identity(PROJECT / name) for name in TRAINING_FILES}
    encoders, encoder_receipts = {}, []
    for path in encoder_paths:
        before, process = time.perf_counter(), time.process_time()
        encoder = MiniLMEncoder(path)
        if encoder.digest in encoders:
            raise ValueError("duplicate encoder identity")
        encoders[encoder.digest] = encoder
        encoder_receipts.append(
            {
                "path": str(Path(path).resolve()),
                "digest": encoder.digest,
                "base_bytes": encoder.base_bytes,
                "files": inventory(path),
                "admission_wall_seconds": time.perf_counter() - before,
                "admission_cpu_seconds": time.process_time() - process,
            }
        )
    selected = {}
    for seed in plan["seeds"]:
        source = routers / f"seed-{seed}"
        winner = load(source / "SELECTED.json")
        manifest = load(source / "selected" / "manifest.json")
        folder = output / "routers" / f"seed-{seed}"
        shutil.copytree(source / "selected", folder)
        expected = winner["artifact"]["manifest_sha256"]
        encoder = (
            None
            if manifest["encoder_digest"] is None
            else encoders[manifest["encoder_digest"]]
        )
        admitted = Router.load(folder, encoder, expected)
        if admitted.seed != seed:
            raise ValueError("selected router seed mismatch")
        selected[str(seed)] = {
            "path": str(folder.relative_to(output)),
            "manifest_sha256": expected,
            "encoder_digest": manifest["encoder_digest"],
            "selected_name": winner["name"],
            "files": inventory(folder),
        }
    cases = []
    for seed in plan["seeds"]:
        for domain in plan["domains"]:
            before, process = time.perf_counter(), time.process_time()
            folder = output / "cases" / f"seed-{seed}" / domain
            folder.mkdir(parents=True)
            truth = create_sources(
                folder / "source.sqlite",
                seed=seed,
                domain=domain,
                count=plan["memory_entities_per_domain"],
            )
            dump(folder / "truth.json", truth)
            receipt = train_snapshot(
                folder / "source.sqlite",
                folder / "artifacts",
                scope=truth["scope"],
                seed=seed,
                hidden=plan["memory_fit"]["hidden"],
                steps=plan["memory_fit"]["steps"],
                router_digest=selected[str(seed)]["manifest_sha256"],
            )
            receipt.update(
                seed=seed,
                domain=domain,
                preparation_wall_seconds=time.perf_counter() - before,
                preparation_cpu_seconds=time.process_time() - process,
            )
            dump(folder / "TRAINING.json", receipt)
            cases.append(
                {
                    "seed": seed,
                    "domain": domain,
                    "path": str(folder.relative_to(output)),
                    "snapshot_digest": receipt["snapshot_digest"],
                    "scope": truth["scope"],
                    "source_cut": receipt["source_cut"],
                    "files": inventory(folder),
                    "preparation_wall_seconds": receipt["preparation_wall_seconds"],
                    "preparation_cpu_seconds": receipt["preparation_cpu_seconds"],
                }
            )
            print(
                json.dumps(
                    {"prepared": [seed, domain], "snapshot": receipt["snapshot_digest"]}
                ),
                flush=True,
            )
    verify_files(PROJECT, training_sources)
    dump(output / "ROUTER_TRAINING.json", load(routers / "TRAINING.json"))
    receipt = {
        "schema": "hepta.memory.v6.prepared-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "preparation_observed_git_head": git_head(),
        "training_sources": training_sources,
        "plan": identity(output / "execution_plan.json"),
        "routers": selected,
        "encoders": encoder_receipts,
        "cases": cases,
        "formal_router_directory": str(routers),
        "formal_router_files": inventory(routers),
        "router_training_receipt": identity(output / "ROUTER_TRAINING.json"),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "held_read": False,
        "memory_selection_on_held": False,
    }
    dump(output / "PREPARED.json", receipt)
    return identity(output / "PREPARED.json")


def verify_prepared(run, prepared):
    verify_files(PROJECT, prepared["training_sources"])
    verify_files(
        run,
        {
            "execution_plan.json": prepared["plan"],
            "ROUTER_TRAINING.json": prepared["router_training_receipt"],
        },
    )
    for selected in prepared["routers"].values():
        verify_files(run / selected["path"], selected["files"])
    for case in prepared["cases"]:
        verify_files(run / case["path"], case["files"])
    for encoder in prepared["encoders"]:
        verify_files(encoder["path"], encoder["files"])
    verify_files(prepared["formal_router_directory"], prepared["formal_router_files"])


def seal(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("freeze already exists; no silent replacement")
    prepared = load(run / "PREPARED.json")
    verify_prepared(run, prepared)
    commit, sources = git_head(), code_bindings()
    verify_committed(sources, commit)
    plan = load(run / "execution_plan.json")
    versions = {
        name: importlib.metadata.version(name)
        for name in ("numpy", "scipy", "scikit-learn", "onnxruntime", "tokenizers")
    }
    freeze = {
        "schema": "hepta.memory.v6.execution-freeze.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": commit,
        "source_files": sources,
        "prepared": identity(run / "PREPARED.json"),
        "plan": identity(run / "execution_plan.json"),
        "held_queries_sha256": plan["held_queries_sha256"],
        "held_seal_sha256": plan["held_seal_sha256"],
        "versions": versions,
        "held_read": False,
    }
    dump(output, freeze)
    return identity(output)


def verify_run(run, freeze_path, expected_digest):
    run = Path(run).resolve()
    if identity(freeze_path)["sha256"] != expected_digest:
        raise ValueError("freeze identity differs from admitted SHA-256")
    freeze = load(freeze_path)
    if (
        freeze["schema"] != "hepta.memory.v6.execution-freeze.v1"
        or freeze["held_read"] is not False
    ):
        raise ValueError("invalid execution freeze")
    verify_committed(freeze["source_files"], freeze["source_commit"])
    verify_files(
        run,
        {"PREPARED.json": freeze["prepared"], "execution_plan.json": freeze["plan"]},
    )
    for name, expected in freeze["versions"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError("frozen runtime version differs: " + name)
    prepared = load(run / "PREPARED.json")
    verify_prepared(run, prepared)
    return freeze, prepared, load(run / "execution_plan.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparing = commands.add_parser("prepare")
    preparing.add_argument("--routers", type=Path, required=True)
    preparing.add_argument("--encoder-cache", type=Path, action="append", required=True)
    preparing.add_argument("--plan", type=Path, required=True)
    preparing.add_argument("--output", type=Path, required=True)
    sealing = commands.add_parser("seal")
    sealing.add_argument("--run", type=Path, required=True)
    sealing.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = (
        prepare(args.routers, args.encoder_cache, args.plan, args.output)
        if args.command == "prepare"
        else seal(args.run, args.output)
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
