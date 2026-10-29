"""Pack completed follow-up evidence and verify a relocated extraction.

Standard library only: Python -I -S is sufficient. The original 207 MB evidence
archive is a declared dependency, never duplicated in this incremental bundle.
Completion gates inspect receipts and bound bytes; they do not rerun science.
"""

import argparse
import gzip
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path, PurePosixPath
import tarfile


SCHEMA = "hepta-followup-evidence-v1"
MANIFEST = "FOLLOWUP_EVIDENCE_MANIFEST.json"
PREFIXES = tuple(
    "experiments/" + name
    for name in (
        "call_put_next",
        "call_put_followup_diagnostics",
        "call_put_followup_runtime",
        "call_put_selected_solver",
        "call_put_audio_balance",
        "call_put_closure",
    )
)
OLD = "experiments/call_put_boundary_network/artifacts/"
EXTRAS = (
    "AGENTS.md",
    "LICENSE",
    "NOTICE",
    OLD + "RECOVERY.md",
    OLD + "RECOVERY_VERIFICATION_20261028.json",
    OLD + "COMPLETE_EVIDENCE_PARTS.json",
    OLD + "FROZEN_INPUTS.json",
)
DEPENDENCY = {
    "filename": "rebuild001_complete_evidence.tar.gz",
    "bytes": 207264800,
    "sha256": "d3be953325ff8e4fc2ffaf94c6a3dd9084892501598cbda92efe747cca594cf7",
    "manifest_sha256": "0fa3aac6356607492ff5f84813f8e3eb76d24a5b876f65f85c93f88bc47a8bd8",
    "included_in_this_archive": False,
}
CONTENT = PREFIXES[0] + "/results/followup001"
NORMALIZED = PREFIXES[1] + "/results/normalized001"
RUNTIME = PREFIXES[2] + "/results/runtime004"
BALANCED = PREFIXES[4] + "/results/balanced001"
DEFAULT_GATES = {
    "content": CONTENT + "/TRAIN_COMPLETE.json",
    "normalized": NORMALIZED + "/COMPLETE.json",
    "balanced": BALANCED + "/COMPLETE.json",
    "selected_solver": PREFIXES[3] + "/results/selected001/SUMMARY.json",
    "balanced_appendix": BALANCED + "/appendix001/SUMMARY.json",
    "runtime": RUNTIME + "/SUMMARY.json",
    "content_runtime": CONTENT + "/RUNTIME.json",
}
PRIMARY = {
    "analytic",
    "continuous_rnn",
    "two_gates",
    "lif_snn",
    "cfc",
    "mamba1",
    "transformer",
}
CONTENT_ARMS = {
    "content_analytic",
    "content_matched_c1",
    "content_sigmoid",
    "analytic",
    "two_gates",
    "mamba1",
    "transformer",
}
CONDITIONS = {"original", "mask_image", "mask_audio", "shuffle_image", "shuffle_audio"}


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(Path(path).read_bytes(), parse_constant=invalid)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_name(name):
    require(
        isinstance(name, str) and bool(name), "Evidence path must be a nonempty string"
    )
    path = PurePosixPath(name)
    require(
        not path.is_absolute()
        and str(path) == name
        and "\\" not in name
        and ":" not in name
        and "\x00" not in name
        and all(p not in (".", "..") and not p.startswith(".") for p in path.parts),
        f"Unsafe evidence path: {name}",
    )
    return name


def checked(root, name):
    path = root / safe_name(name)
    require(path.resolve().is_relative_to(root), f"Path escapes evidence root: {name}")
    require(
        not any(p.is_symlink() for p in (path, *path.parents) if p != root.parent),
        f"Symlink is not evidence: {name}",
    )
    return path


def inventory(root, extras=EXTRAS, excluded=()):
    paths = set(extras)
    excluded = set(excluded) | {MANIFEST}
    for name in extras:
        safe_name(name)
        require(
            not name.startswith(OLD + DEPENDENCY["filename"]),
            "Do not duplicate the original evidence archive or parts",
        )
    for prefix in PREFIXES:
        directory = checked(root, prefix)
        require(directory.is_dir(), f"Missing evidence subtree: {prefix}")
        for current, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = sorted(
                d for d in dirs if not d.startswith(".") and d != "__pycache__"
            )
            for d in dirs:
                checked(root, (Path(current) / d).relative_to(root).as_posix())
            for name in files:
                if name.startswith(".") or name.endswith((".pyc", ".pyo")):
                    continue
                paths.add((Path(current) / name).relative_to(root).as_posix())
    records = {}
    for name in sorted(paths - excluded):
        path = checked(root, name)
        require(path.is_file(), f"Missing regular evidence file: {name}")
        records[name] = {
            "path": name,
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        }
    return records


class Reader:
    def __init__(self, root, files):
        self.root, self.files = root, files

    def name(self, path):
        path = Path(path)
        name = (
            path.relative_to(self.root).as_posix()
            if path.is_absolute()
            else path.as_posix()
        )
        require(
            safe_name(name) in self.files, f"Gate dependency is not bundled: {name}"
        )
        return name

    def json(self, path):
        return read(checked(self.root, self.name(path)))

    def digest(self, path):
        return self.files[self.name(path)]["sha256"]

    def artifact(self, entry, base=None):
        path = Path(entry["path"])
        if base is not None and not str(path).startswith("experiments/"):
            path = base / path
        require(
            self.digest(path) == entry["sha256"], f"Artifact binding mismatch: {path}"
        )


def _training(reader, path, role):
    study = path.parent
    content = role == "content"
    expected = 84 if content else 36 if role == "normalized" else 18
    aliases = 252 if content else expected
    complete, plan = reader.json(path), reader.json(study / "PLAN.json")
    require(complete.get("status") == "complete", f"{role} is incomplete")
    specs = plan["candidates" if content else "specs"]
    ids = {s["id"] for s in specs}
    require(
        len(specs) == len(ids) == expected, f"{role} candidate inventory is incomplete"
    )
    tasks = (
        ("selective_copy", "mqar")
        if content
        else ("fsdd", "multimodal_select")
        if role == "normalized"
        else ("multimodal_select",)
    )
    arms = CONTENT_ARMS if content else {"analytic", "two_gates", "mamba1"}
    seeds = (7201, 7202, 7203) if content else (7501, 7502, 7503)
    arm_key = "arm" if content else "architecture"
    require(
        {(s["task"], s[arm_key], s["seed"], s["lr"]) for s in specs}
        == set(itertools.product(tasks, arms, seeds, (0.001, 0.003))),
        "Training factorial differs from the declared study",
    )
    attempts = complete["attempts"] if content else reader.json(study / "ATTEMPTS.json")
    require(
        len(attempts) == expected
        and {a["id"] for a in attempts} == ids
        and all(a["returncode" if content else "exit_code"] == 0 for a in attempts),
        f"{role} contains missing or failed attempts",
    )
    checkpoints, groups = 0, {}
    budgets = (
        {"cpu": {15, 30, 60}, "updates": {192, 384, 768}}
        if content
        else {"cpu": {10, 20}, "updates": {128, 256}}
    )
    for spec in specs:
        hash_key = "id" if content else "sha256"
        require(
            hashlib.sha256(
                encoded({k: v for k, v in spec.items() if k != hash_key})
            ).hexdigest()
            == spec[hash_key],
            "Candidate identity changed",
        )
        require(
            spec["protocol_sha256"] == reader.digest(study / "PROTOCOL.json")
            and spec["data_sha256"] == reader.digest(study / "DATA.json"),
            "Candidate input bindings changed",
        )
        directory = study / "candidates" / spec["id"]
        result, start = (
            reader.json(directory / "RESULT.json"),
            reader.json(directory / "START.json"),
        )
        expected_start = (
            {"spec": spec, "probe": False, "test_loaded": False} if content else spec
        )
        require(
            start == expected_start
            and result.get("status") == "complete"
            and result["spec"] == spec,
            f"{role} candidate receipt mismatch",
        )
        require(
            (directory / "FAILURE.json").as_posix() not in reader.files,
            "Selected training stage has a failure receipt",
        )
        require(
            result["steps"] >= (768 if content else 256)
            and result["loop_cpu_seconds" if content else "training_loop_cpu_seconds"]
            >= (60 if content else 20),
            "A candidate has not reached both budgets",
        )
        seen = {"cpu": set(), "updates": set()}
        for cp in result["checkpoints"]:
            cp_path = Path(cp["path"])
            cp_path = study / cp_path if content else cp_path
            require(
                cp_path.is_relative_to(directory), "Checkpoint outside its candidate"
            )
            manifest = reader.json(cp_path / "MANIFEST.json")
            require(
                reader.digest(cp_path / "MANIFEST.json") == cp["manifest_sha256"]
                and reader.digest(cp_path / "weights.npz")
                == cp["weights_sha256"]
                == manifest["weights_sha256"],
                "Checkpoint bytes differ from completed training receipt",
            )
            metadata = manifest["metadata"]
            require(
                metadata.get("spec") == spec
                if content
                else metadata.get("spec_sha256") == spec["sha256"]
                and metadata.get("model_config") == spec["config"],
                "Checkpoint candidate binding changed",
            )
            tags = (
                [
                    {"kind": k, "value": v}
                    for k, key in (("cpu", "cpu_tags"), ("updates", "update_tags"))
                    for v in cp[key]
                ]
                if content
                else cp["tags"]
            )
            for tag in tags:
                kind, value = tag["kind"], tag["value"]
                require(
                    kind in budgets
                    and value in budgets[kind]
                    and value not in seen[kind],
                    "Illegal or duplicate checkpoint budget tag",
                )
                actual = (
                    cp["cpu_before_validation" if content else "cpu_trigger"]
                    if kind == "cpu"
                    else cp["step" if content else "update"]
                )
                require(
                    actual >= value if kind == "cpu" else actual == value,
                    "Checkpoint does not correspond to its budget",
                )
                seen[kind].add(value)
            groups.setdefault((spec["task"], spec[arm_key], spec["seed"]), []).append(
                (spec, cp, tags)
            )
            checkpoints += 1
        require(seen == budgets, "Candidate checkpoint budgets are incomplete")
    selection, scores = (
        reader.json(study / "SELECTION.json"),
        reader.json(study / "SCORES.json"),
    )
    require(
        len(selection["records"])
        == len(scores["rows" if content else "records"])
        == aliases,
        f"{role} selection or scoring coverage is incomplete",
    )
    require(
        len(selection["costs" if content else "candidate_costs"]) == expected,
        "Learning-rate costs are missing",
    )
    expected_aliases = {
        (task, arm, seed, kind, budget)
        for task, arm, seed in itertools.product(tasks, arms, seeds)
        for kind, values in budgets.items()
        for budget in (values if content else (max(values),))
    }
    require(
        {
            tuple(r[k] for k in ("task", arm_key, "seed", "regime", "budget"))
            for r in selection["records"]
        }
        == expected_aliases,
        "Selection aliases differ from declared budgets",
    )
    for row in selection["records"]:
        eligible = [
            (spec, cp)
            for spec, cp, tags in groups[(row["task"], row[arm_key], row["seed"])]
            if any(
                t["kind"] == row["regime"] and t["value"] <= row["budget"] for t in tags
            )
        ]
        best = min(
            eligible,
            key=lambda item: (item[1]["validation"]["ce"], item[1]["manifest_sha256"])
            if content
            else (item[1]["validation"]["ce"], item[1]["update"], item[0]["lr"]),
        )
        require(
            row["checkpoint"] == best[1] and (content or row["spec"] == best[0]),
            "Validation-only budget selection does not reproduce",
        )
    if content:
        summary = reader.json(study / "SUMMARY.json")
        require(
            summary["candidate_count"] == 84
            and summary["selected_curve_records"] == 252,
            "Content summary is incomplete",
        )
        require(
            scores["selection_file_sha256"] == reader.digest(study / "SELECTION.json"),
            "Content score selection binding differs",
        )
        for row in scores["rows"]:
            reader.artifact(
                {"path": row["prediction_path"], "sha256": row["prediction_sha256"]},
                study,
            )
    else:
        require(scores.get("status") == "complete", f"{role} scoring is incomplete")
        for row in scores["records"]:
            require(
                set(row["scores"]) == {"train", "val", "test"}, "Missing scored split"
            )
            for split in row["scores"].values():
                reader.artifact(split["artifact"])
    return {
        "candidates": expected,
        "checkpoints": checkpoints,
        "selected_aliases": aliases,
    }


def _numerical(reader, records, aliases):
    observed = []
    for row in records:
        observed.extend(row["aliases"] if "aliases" in row else row["item"]["aliases"])
        evaluations = row["evaluations"]
        require(
            len(evaluations) == 4
            and {e["max_step"] for e in evaluations} == {0.25, 0.125, 0.0625, 0.03125},
            "Numerical refinement grid is incomplete",
        )
        require(
            sum(
                e["precision"] == "torch.float64" and e["max_step"] == 0.03125
                for e in evaluations
            )
            == 1,
            "Numerical reference is absent",
        )
        for entry in evaluations:
            reader.artifact(entry["artifact"])
    require(
        len(observed) == aliases and len({encoded(a) for a in observed}) == aliases,
        "Numerical alias coverage is incomplete or duplicated",
    )
    return {"aliases": aliases, "physical_checkpoints": len(records)}


def _timings(value, repetitions):
    for key in ("cpu_seconds", "wall_seconds"):
        require(
            len(value[key]) == repetitions
            and all(math.isfinite(t) and t >= 0 for t in value[key]),
            "Runtime sample inventory is incomplete or nonfinite",
        )


def completion_gates(root, gates, files):
    require(
        set(gates) == set(DEFAULT_GATES) | {"report"},
        "All eight completion roles are required",
    )
    reader, bindings = Reader(root, files), {}
    for role, name in sorted(gates.items()):
        name = reader.name(name)
        path = Path(name)
        if role == "report":
            require(
                path.suffix.lower() in {".html", ".md", ".pdf"}
                and files[name]["bytes"] > 0,
                "A nonempty final report is required",
            )
            receipt_path = path.parent / "REPORT_RECEIPT.json"
            receipt = reader.json(receipt_path)
            require(
                receipt.get("status") == "complete"
                and receipt.get("schema") == "hepta-followup-synthesis-v1"
                and receipt.get("generator_sha256")
                == reader.digest(PREFIXES[5] + "/report.py"),
                "Final report receipt is incomplete or its generator changed",
            )
            for collection in ("inputs", "outputs"):
                entries = receipt[collection]
                require(
                    entries
                    and len({entry["path"] for entry in entries}) == len(entries),
                    f"Report {collection} must be nonempty and unique",
                )
                for entry in entries:
                    reader.artifact(entry)
                    require(
                        files[reader.name(entry["path"])]["bytes"] == entry["bytes"],
                        "Report artifact size binding changed",
                    )
            require(
                name in {entry["path"] for entry in receipt["outputs"]},
                "Final report is absent from its receipt outputs",
            )
            summary = {
                "bytes": files[name]["bytes"],
                "receipt_sha256": reader.digest(receipt_path),
                "bound_inputs": len(receipt["inputs"]),
                "bound_outputs": len(receipt["outputs"]),
            }
        elif role in ("content", "normalized", "balanced"):
            summary = _training(reader, path, role)
        else:
            data = reader.json(path)
            if role == "selected_solver":
                require(
                    data.get("status") == "complete"
                    and not data["failures"]
                    and data["aliases"] == 36
                    and data["test_split_loaded"] is False
                    and data["checkpoint_selection_changed"] is False,
                    "Selected-solver stage is incomplete or changed selection",
                )
                require(
                    len(data["results"]) == data["physical_checkpoints"]
                    and all(r.get("status") == "complete" for r in data["results"]),
                    "Numerical results are incomplete",
                )
                summary = _numerical(reader, data["results"], 36)
            elif role == "balanced_appendix":
                require(
                    data.get("status") == "complete"
                    and data["test_used_for_selection"] is False
                    and data["numerical_uses_test"] is False,
                    "Balanced appendix is incomplete",
                )
                rows = data["intervention_records"]
                require(
                    len(rows) == len({encoded(r["alias"]) for r in rows}) == 18,
                    "Balanced intervention aliases are incomplete",
                )
                for row in rows:
                    require(
                        set(row["conditions"]) == CONDITIONS,
                        "Missing modality intervention",
                    )
                    for condition in row["conditions"].values():
                        reader.artifact(condition["artifact"])
                summary = {
                    **_numerical(reader, data["numerical_records"], 6),
                    "intervention_aliases": 18,
                }
            elif role == "runtime":
                require(
                    data.get("status") == "complete"
                    and len(data["records"]) == 7
                    and {r["architecture"] for r in data["records"]} == PRIMARY,
                    "Seven runtime models are required",
                )
                prepared = reader.json(path.parent / "PREPARED.json")
                require(
                    prepared.get("status") == "complete",
                    "Runtime preparation is incomplete",
                )
                count = 0
                for row in data["records"]:
                    require(
                        row["preparation_sha256"]
                        == reader.digest(path.parent / "PREPARED.json"),
                        "Runtime preparation binding changed",
                    )
                    require(
                        len(row["cases"]) == 3
                        and {(c["mode"], c["batch"]) for c in row["cases"]}
                        == {("prefill", 1), ("prefill", 32), ("step", 1)},
                        "Runtime case coverage is incomplete",
                    )
                    for case in row["cases"]:
                        require(
                            case["status"] == "measured"
                            and case["fidelity"]["allclose"],
                            "A required runtime case was not measured with parity",
                        )
                        _timings(case["eager"], 31)
                        _timings(case["compiled"], 31)
                        count += 1
                for row in prepared["records"]:
                    for case in row["cases"]:
                        reader.artifact(case, path.parent)
                summary = {"architectures": 7, "measured_cases": count}
            else:
                rows = data["records"]
                keys = {(r["record"]["task"], r["record"]["arm"]) for r in rows}
                require(
                    len(rows) == 14
                    and keys
                    == set(itertools.product(("selective_copy", "mqar"), CONTENT_ARMS)),
                    "Fourteen content runtime cases are required",
                )
                for row in rows:
                    require(
                        (
                            row["record"]["seed"],
                            row["record"]["regime"],
                            row["record"]["budget"],
                        )
                        == (7201, "cpu", 60),
                        "Wrong content runtime selection scope",
                    )
                    require(
                        set(row["sequence_timings"]) == {"1", "32"},
                        "Missing content batch timing",
                    )
                    for timings in (*row["sequence_timings"].values(), row["decode"]):
                        _timings(timings, 15)
                summary = {
                    "measured_models": 14,
                    "parity_failures_retained": sum(
                        not r["streaming_parity"] for r in rows
                    ),
                }
        bindings[role] = {
            "path": name,
            "sha256": files[name]["sha256"],
            "summary": summary,
        }
    return bindings


def verify_archive(path, manifest_bytes, files):
    expected = {
        **files,
        MANIFEST: {
            "path": MANIFEST,
            "bytes": len(manifest_bytes),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    }
    seen = set()
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            name = safe_name(member.name)
            require(
                member.isfile() and name not in seen and name in expected,
                "Unexpected archive member or link",
            )
            require(
                member.size == expected[name]["bytes"], "Archive member size differs"
            )
            with archive.extractfile(member) as stream:
                require(
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    == expected[name]["sha256"],
                    "Archive member hash differs",
                )
            seen.add(name)
    require(seen == expected.keys(), "Archive member inventory is incomplete")


def create(root, output, gates, extras=EXTRAS):
    root, output = Path(root).resolve(), Path(output).resolve()
    receipt = output.with_name(output.name + ".receipt.json")
    require(
        not output.exists() and not receipt.exists(), "Archive and receipt must be new"
    )
    excluded = [
        p.relative_to(root).as_posix()
        for p in (output, receipt)
        if p.is_relative_to(root)
    ]
    files = inventory(root, extras, excluded)
    bindings = completion_gates(root, gates, files)
    manifest = {
        "schema": SCHEMA,
        "scope": list(PREFIXES),
        "extra_files": sorted(set(extras)),
        "excluded_outputs": excluded,
        "dependency": DEPENDENCY,
        "gates": bindings,
        "files": list(files.values()),
        "file_count": len(files),
        "uncompressed_bytes": sum(f["bytes"] for f in files.values()),
        "meaning": "Complete incremental follow-up bytes; original research archive is a separately verified dependency. Original JSON paths remain unchanged.",
    }
    manifest["identity_sha256"] = hashlib.sha256(encoded(manifest)).hexdigest()
    manifest_bytes = encoded(manifest) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as raw,
        gzip.GzipFile(
            filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=6
        ) as compressed,
    ):
        with tarfile.open(
            fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT
        ) as archive:
            for name in (MANIFEST, *files):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = (
                    (len(manifest_bytes) if name == MANIFEST else files[name]["bytes"]),
                    0o644,
                    0,
                )
                stream = (
                    io.BytesIO(manifest_bytes)
                    if name == MANIFEST
                    else checked(root, name).open("rb")
                )
                with stream:
                    archive.addfile(info, stream)
    verify_archive(output, manifest_bytes, files)
    require(
        inventory(root, extras, excluded) == files,
        "Evidence changed while the archive was being written",
    )
    require(
        completion_gates(root, gates, files) == bindings,
        "Completion gates changed during packaging",
    )
    result = {
        "schema": "hepta-followup-evidence-receipt-v1",
        "status": "complete",
        "archive": {
            "filename": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha(output),
        },
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_identity_sha256": manifest["identity_sha256"],
        "file_count": len(files),
        "uncompressed_bytes": manifest["uncompressed_bytes"],
        "gates": bindings,
        "dependency": DEPENDENCY,
        "verification": "Every tar member checked; no scientific rerun",
    }
    with receipt.open("xb") as stream:
        stream.write(encoded(result) + b"\n")
    return result


def verify(root, dependency_archive=None):
    root = Path(root).resolve()
    manifest = read(root / MANIFEST)
    require(
        manifest["schema"] == SCHEMA
        and manifest["scope"] == list(PREFIXES)
        and manifest["dependency"] == DEPENDENCY,
        "Unknown evidence scope or dependency",
    )
    require(
        hashlib.sha256(
            encoded({k: v for k, v in manifest.items() if k != "identity_sha256"})
        ).hexdigest()
        == manifest["identity_sha256"],
        "Manifest identity changed",
    )
    for name in manifest["excluded_outputs"]:
        safe_name(name)
    files = inventory(root, manifest["extra_files"], manifest["excluded_outputs"])
    require(
        list(files.values()) == manifest["files"]
        and len(files) == manifest["file_count"]
        and sum(f["bytes"] for f in files.values()) == manifest["uncompressed_bytes"],
        "Evidence inventory, size or hash mismatch",
    )
    gates = {k: v["path"] for k, v in manifest["gates"].items()}
    require(
        completion_gates(root, gates, files) == manifest["gates"],
        "Completion gate bindings changed",
    )
    dependency = "declared_not_supplied"
    if dependency_archive is not None:
        path = Path(dependency_archive)
        require(
            path.stat().st_size == DEPENDENCY["bytes"]
            and sha(path) == DEPENDENCY["sha256"],
            "Original dependency archive does not match",
        )
        dependency = "size_and_sha256_verified"
    return {
        "status": "verified",
        "files": len(files),
        "bytes": manifest["uncompressed_bytes"],
        "manifest_sha256": sha(root / MANIFEST),
        "dependency": dependency,
        "gates": manifest["gates"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("create")
    pack.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument(
        "--gate", action="append", default=[], metavar="ROLE=RELATIVE_PATH"
    )
    pack.add_argument("--include", action="append", default=[], metavar="RELATIVE_PATH")
    check = commands.add_parser("verify")
    check.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    check.add_argument("--dependency-archive", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        gates = dict(DEFAULT_GATES)
        supplied = set()
        for assignment in args.gate:
            role, separator, path = assignment.partition("=")
            require(
                separator
                and role not in supplied
                and role in set(DEFAULT_GATES) | {"report"},
                "Use each known role once as role=relative_path",
            )
            supplied.add(role)
            gates[role] = safe_name(path)
        result = create(
            args.root, args.output, gates, tuple(EXTRAS) + tuple(args.include)
        )
    else:
        result = verify(args.root, args.dependency_archive)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
