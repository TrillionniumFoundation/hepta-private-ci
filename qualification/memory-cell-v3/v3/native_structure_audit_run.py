"""Bind independent artifact audits to a unified sealed run or declared development."""

import io
import json
from pathlib import Path
import zipfile

from .native_artifact_audit import audit_native_stage
from .native_structure_audit_core import Reader, require, same, sha
from .structure_artifact_audit import audit_structure_stage


def _current_auditor_sources():
    directory = Path(__file__).resolve().parents[1]
    names = (
        "audit_native_structure.py",
        "v3/bitcell.py",
        "v3/factor_cell.py",
        "v3/native_structure_audit_core.py",
        "v3/native_state_audit.py",
        "v3/native_artifact_audit.py",
        "v3/structure_audit_models.py",
        "v3/structure_artifact_audit.py",
        "v3/native_structure_audit_run.py",
    )
    return {
        "qualification/memory-cell-v3/" + name: sha((directory / name).read_bytes())
        for name in names
    }


def _finish(reader, report):
    # Re-read consumed bytes before publishing the independent report, without
    # writing anything to the sealed experiment. No current checkout is read.
    for name in list(reader.files):
        reader.raw(name)
    report["consumed_files"] = len(reader.files)
    report["consumed_file_identities_sha256"] = sha(
        json.dumps(reader.files, sort_keys=True, separators=(",", ":")).encode()
    )


def _save_report(report, output, protected):
    if output is None:
        return
    destination = Path(output).resolve()
    require(
        all(not destination.is_relative_to(Path(root).resolve()) for root in protected),
        "audit output must be outside every experiment input directory",
    )
    require(
        not destination.exists(),
        "audit output already exists; preserving earlier validation",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(
            (
                json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
            ).encode()
        )


def audit_run(run, output=None, *, allow_development=False):
    """Recalculate a unified RUN's native/structure stages; return/write JSON."""
    reader = Reader(run)
    report = {
        "schema": "memory-cell-v3.independent-native-structure-audit.v1",
        "run": str(reader.root),
        "verified": False,
        "read_only": True,
        "training_performed": False,
        "auditor_sources": _current_auditor_sources(),
        "stages": {},
        "errors": [],
    }
    try:
        seal = reader.json("MANIFEST.json")
        require(seal["schema"] == "memory-cell-v3.evidence.v1", "unknown run seal")
        reader.seal = seal
        actual_names = []
        for path in reader.root.rglob("*"):
            require(not path.is_symlink(), "symlink in sealed experiment")
            if path.is_file():
                actual_names.append(path.relative_to(reader.root).as_posix())
        require(
            set(actual_names) - {"MANIFEST.json"} == set(seal["files"]),
            "sealed run inventory differs",
        )
        environment = reader.json("environment.json")
        require(
            environment["mode"] in {"development_only", "frozen_protocol_research"},
            "unknown run qualification mode",
        )
        development = environment["mode"] == "development_only"
        require(
            not development or allow_development,
            "development evidence requires --allow-development",
        )
        report["qualification_mode"] = (
            "sealed-development" if development else "formal-source-snapshot"
        )
        status = reader.json("execution_status.json")
        require(
            status["execution"] == "completed",
            "independent gate audit requires a completed run",
        )
        results = reader.json("results.json")
        protocol = reader.json("protocol.json")
        identity = reader.json("source_identity.json")
        same(identity["commit"], seal["source_commit"], "run source commit")
        same(
            {
                "bytes": len(reader.raw("source_identity.json")),
                "sha256": sha(reader.raw("source_identity.json")),
            },
            seal["source_identity"],
            "sealed source inventory",
        )
        source_payloads = {}
        with zipfile.ZipFile(io.BytesIO(reader.raw("source_snapshot.zip"))) as archive:
            require(
                len(archive.namelist()) == len(identity["files"])
                and set(archive.namelist()) == set(identity["files"]),
                "source snapshot inventory differs",
            )
            for name, expected in identity["files"].items():
                require(
                    archive.getinfo(name).file_size == expected["bytes"]
                    and expected["bytes"] <= 256_000_000,
                    "source snapshot size differs",
                )
                payload = archive.read(name)
                same(
                    {"bytes": len(payload), "sha256": sha(payload)},
                    expected,
                    f"source snapshot {name}",
                )
                if name == "codex-rs/Cargo.lock":
                    source_payloads[name] = payload
        for name, expected_hash in report["auditor_sources"].items():
            require(
                name in identity["files"]
                and identity["files"][name]["sha256"] == expected_hash,
                f"current auditor/reader differs from run-frozen source: {name}",
            )
        same(
            {
                "bytes": len(reader.raw("protocol.json")),
                "sha256": sha(reader.raw("protocol.json")),
            },
            identity["files"]["qualification/memory-cell-v3/PROTOCOL.json"],
            "frozen protocol",
        )
        seeds = protocol["development_seeds"] if development else protocol["seeds"]
        same(environment["selected_seeds"], seeds, "run seed selection")
        report["source_commit_claim"] = identity["commit"]
        report["run_manifest_sha256"] = sha(reader.raw("MANIFEST.json"))
        for stage in ("native", "structure"):
            if stage not in results:
                continue
            wrapper = results[stage]
            same(
                wrapper["source_commit"], identity["commit"], f"{stage} wrapper source"
            )
            same(wrapper["selected_seeds"], seeds, f"{stage} wrapper seeds")
            same(wrapper["development_only"], development, f"{stage} wrapper mode")
            stage_data = reader.json(f"{stage}/{stage}.json")
            same(wrapper["data"], stage_data, f"{stage} retained/aggregate summary")
            same(stage_data["source_commit"], identity["commit"], f"{stage} source")
            same(stage_data["seeds"], seeds, f"{stage} seeds")
            same(stage_data["development"], development, f"{stage} mode")
            for key, value in protocol[stage].items():
                same(
                    stage_data["protocol"][key],
                    value,
                    f"{stage} declared protocol {key}",
                )
            if stage == "native":
                report["stages"][stage] = audit_native_stage(
                    reader,
                    source_files=identity["files"],
                    source_commit=identity["commit"],
                    original_lock=source_payloads["codex-rs/Cargo.lock"],
                )
            else:
                report["stages"][stage] = audit_structure_stage(reader)
        require(
            report["stages"], "run contains neither native nor structure experiment"
        )
        _finish(reader, report)
        report["verified"] = True
        report["scope"] = (
            "Consumed native/structural evidence and source snapshot verified; other stages and Git commit ownership require the separate full-run verifier."
        )
    except Exception as error:
        report["errors"].append({"type": type(error).__name__, "message": str(error)})
    _save_report(report, output, [reader.root])
    return report


def audit_development(native=None, structure=None, output=None):
    """Inspect explicitly unsealed historical development without sealing it."""
    report = {
        "schema": "memory-cell-v3.independent-native-structure-audit.v1",
        "verified": False,
        "qualification_mode": "unsealed-development-only",
        "read_only": True,
        "training_performed": False,
        "auditor_sources": _current_auditor_sources(),
        "stages": {},
        "errors": [],
    }
    protected = []
    for stage, root in (("native", native), ("structure", structure)):
        if root is None:
            continue
        reader = Reader(root)
        protected.append(reader.root)
        try:
            summary = reader.json(f"{stage}.json")
            require(
                summary["development"] is True,
                "unsealed mode may only inspect declared development evidence",
            )
            result = (
                audit_native_stage(reader, "")
                if stage == "native"
                else audit_structure_stage(reader, "")
            )
            _finish(reader, result)
            report["stages"][stage] = result
        except Exception as error:
            report["errors"].append(
                {"stage": stage, "type": type(error).__name__, "message": str(error)}
            )
    report["verified"] = bool(report["stages"]) and not report["errors"]
    report["scope"] = (
        "Arithmetic and artifact consistency of unsealed development only; no formal source or Git commit qualification."
    )
    _save_report(report, output, protected)
    return report
