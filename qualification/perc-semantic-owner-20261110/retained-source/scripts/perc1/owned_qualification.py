"""Reproducible real owned-CLI engineering qualification.

Runs actual capture, pinned MobileNet inference, replay, separate-process cold
readback, exact-span consumption, and failure/budget controls. Generated image
and text are engineering fixtures, never unseen real-task scientific evidence.
All outputs are create-only. Only copies created under inputs are deleted.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from perc1_process_meter import run as measured_run

from .capture_entry import decode_native_wire
from .entry import capture_backend_sha256, read_pinned
from .schema import canonical, require, sha
from .semantic_contract import extract_span, validate_text_evidence


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def journal_rows(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT id,units,state,receipt_sha FROM operations ORDER BY id"
        ).fetchall()


def qualify(args):
    from PIL import Image

    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = Path(args.output).absolute()
    root.mkdir(mode=0o700)
    inputs = root / "inputs"
    inputs.mkdir(mode=0o700)
    repo = Path(__file__).resolve().parents[2]
    code = [
        Path(__file__).with_name(name + ".py")
        for name in (
            "__main__",
            "entry",
            "owner",
            "capture_entry",
            "producer",
            "projection",
            "raster",
            "native",
            "schema",
            "semantic_contract",
            "owned_qualification",
        )
    ]
    source_pins = {str(p.relative_to(repo)): sha(p.read_bytes()) for p in code}
    weights = read_pinned(args.weights, args.weights_sha256, 64 * 1024 * 1024)
    projection = read_pinned(args.projection, args.projection_sha256, 8 * 1024 * 1024)
    weights_copy, projection_copy = inputs / "weights.pth", root / "projection.json"
    with weights_copy.open("xb") as stream:
        stream.write(weights)
    with projection_copy.open("xb") as stream:
        stream.write(projection)
    scope_input = Path(args.scope_input).read_bytes()
    with (root / "scope-input.json").open("xb") as stream:
        stream.write(scope_input)
    rgb = bytes(
        (x * 7 + y * 3 + channel * 71) % 256
        for y in range(48)
        for x in range(48)
        for channel in range(3)
    )
    image_path, text_path = inputs / "image.png", inputs / "text.txt"
    Image.frombytes("RGB", (48, 48), rgb).save(image_path, format="PNG")
    image_bytes = image_path.read_bytes()
    text_bytes = "实体=Hepta Labs; 金额=0042.50; 任务=perception;\n".encode()
    with text_path.open("xb") as stream:
        stream.write(text_bytes)
    for name, raw in (
        ("original.png", image_bytes),
        ("original.rgb", rgb),
        ("original-text.bin", text_bytes),
    ):
        with (root / name).open("xb") as stream:
            stream.write(raw)
    spans = []
    for name, value in (("amount", b"0042.50"), ("entity", b"Hepta Labs")):
        start = text_bytes.index(value)
        end = start + len(value)
        spans.append(
            {
                "span_id": name,
                "start": start,
                "end": end,
                "references": [
                    {
                        "kind": "bytes",
                        "origin_sha256": sha(text_bytes),
                        "start": start,
                        "end": end,
                        "total": len(text_bytes),
                    }
                ],
            }
        )
    evidence = {
        "schema": "perc1.semantic-text.v1",
        "kind": "source_text",
        "content_sha256": sha(text_bytes),
        "fidelity": "source_bytes_preserved",
        "spans": spans,
    }
    validate_text_evidence(evidence, text_bytes)
    write_json(root / "TEXT_EVIDENCE.json", evidence)
    sources = {
        "owned-image-001": {
            "image_path": str(image_path),
            "image_sha256": sha(image_bytes),
            "exact_text": {
                "kind": "source_text",
                "path": str(text_path),
                "sha256": sha(text_bytes),
                "engine": "generated-source-text-v1",
            },
        },
    }
    backend = capture_backend_sha256()
    frontier = sha({"sources": sources, "capture_backend_sha256": backend})
    grant = {
        "schema": "perc1.capture-grant.v1",
        "owner_id": "owned-cli-qualification",
        "generation": 1,
        "source_frontier": frontier,
        "source_ids": list(sources),
        "scope_digest": args.scope_digest,
    }
    config = {
        "schema": "perc1.operator-config.v1",
        "state_dir": str(root / "owner"),
        "owner_id": grant["owner_id"],
        "generation": 1,
        "budget_units": 2,
        "capture_backend_sha256": backend,
        "grant": grant,
        "sources": sources,
        "model": {
            "weights": str(weights_copy),
            "weights_sha256": args.weights_sha256,
            "projection": str(projection_copy),
            "projection_sha256": args.projection_sha256,
            "device": "cpu",
        },
    }
    request = {
        "source_id": "owned-image-001",
        "representation": "dense",
        "regions": [
            {
                "evidence_id": f"tile-{row}-{column}",
                "x": column * 24,
                "y": row * 24,
                "width": 24,
                "height": 24,
            }
            for row in range(2)
            for column in range(2)
        ],
    }
    config_path, request_path = root / "config.json", root / "request.json"
    write_json(config_path, config)
    write_json(request_path, request)
    steps = []

    def invoke(name, operation, command="capture", expected_returncode=0):
        argv = [
            sys.executable,
            "-m",
            "perc1",
            command,
            "--config",
            str(config_path),
            "--operation",
            operation,
        ]
        if command == "capture":
            argv.extend(("--request", str(request_path)))
        envelope = measured_run(
            argv,
            root / name,
            cwd=repo,
            timeout_seconds=180,
            source_paths=[*code, config_path, request_path, projection_copy],
        )
        require(
            envelope["returncode"] == expected_returncode,
            f"{name}: unexpected exit; inspect retained stderr",
        )
        require(envelope["measurement_valid"], f"{name}: process envelope invalid")
        stdout = (root / name / "stdout.bin").read_bytes()
        stderr = (root / name / "stderr.bin").read_bytes()
        result = json.loads(stdout if stdout else stderr)
        write_json(root / name / "result.json", result)
        steps.append(
            {
                "name": name,
                "pid": envelope["pid"],
                "returncode": envelope["returncode"],
                "this_entry": result.get("this_entry"),
                "receipt_sha256": result.get("receipt", {}).get("receipt_sha256"),
                "owner_status": result.get("owner_status"),
                "envelope_path": f"{name}/receipt.json",
                "command_wall_ns": envelope["command_wall_ns"],
                "waited_cpu_ns": envelope["waited_cpu_ns"],
            }
        )
        return result

    zero = {
        "source_callback_invocations": 0,
        "encoder_loaded": False,
        "encoder_completed_calls": 0,
    }
    fresh = invoke("fresh", "original")
    require(
        fresh["this_entry"]
        == {
            "source_callback_invocations": 1,
            "encoder_loaded": True,
            "encoder_completed_calls": 1,
        },
        "real encoder call missing",
    )
    receipt = fresh["receipt"]
    produced = receipt["result"]["producer"]
    require(
        receipt["status"] == "executed" and produced["status"] == "executed",
        "producer did not execute",
    )
    require(
        produced["model"]["backbone_sha256"] == args.weights_sha256,
        "wrong executed backbone",
    )
    require(
        produced["transform"]["features_shape"] == [4, 576],
        "wrong executed feature shape",
    )
    require(
        produced["worker"]["pid"] == steps[0]["pid"] != os.getpid(),
        "encoder did not run in the recorded CLI process",
    )
    require(
        produced["transform"]["raster_rgb_sha256"] == sha(rgb), "captured RGB differs"
    )
    require(
        sum(len(item["raw_bytes"]) for item in produced["observation"]["evidence"])
        == 6912,
        "native evidence byte count differs",
    )
    native = decode_native_wire(receipt["result"])
    require(sha(native) == produced["observation_sha256"], "native wire digest differs")
    with (root / "native.json").open("xb") as stream:
        stream.write(native)
    write_json(root / "producer-receipt.json", produced)
    write_json(root / "owner-receipt.json", receipt)
    print(
        json.dumps(
            {"event": "native_ready", "output": str(root), "native_sha256": sha(native)}
        ),
        flush=True,
    )
    replay = invoke("replay", "original")
    require(
        replay["receipt"] == receipt and replay["this_entry"] == zero,
        "replay caused new work or changed receipt",
    )
    require(
        decode_native_wire(replay["receipt"]["result"]) == native,
        "replayed original wire differs",
    )
    for path in (image_path, text_path, weights_copy):
        require(
            path.parent == inputs and not path.is_symlink(),
            "refuse deletion outside run-owned inputs",
        )
        path.unlink()
    cold = invoke("cold-readback", "original", "capture-read")
    require(
        cold["receipt"] == receipt and cold["this_entry"] == zero,
        "cold readback changed receipt or executed encoder",
    )
    require(
        decode_native_wire(cold["receipt"]["result"]) == native,
        "cold original wire differs",
    )
    retained_text = base64.b64decode(
        cold["receipt"]["result"]["producer"]["exact_text"]["raw_base64"], validate=True
    )
    next_task = {
        "schema": "perc1.next-task-exact-span.v1",
        "receipt_sha256": cold["receipt"]["receipt_sha256"],
        "content_sha256": sha(retained_text),
        "amount": extract_span(evidence, retained_text, "amount"),
        "entity": extract_span(evidence, retained_text, "entity"),
        "source_files_present": image_path.exists() or text_path.exists(),
        "encoder_calls": 0,
        "scope": "registered exact byte spans consumed from a retained receipt; no semantic generalization claim",
    }
    require(
        next_task["amount"] == "0042.50" and next_task["entity"] == "Hepta Labs",
        "next-task exact extraction differs",
    )
    write_json(root / "NEXT_TASK.json", next_task)
    failed = invoke("missing-source", "missing-source", expected_returncode=2)
    require(failed["status"] == "failed", "missing source did not retain failure")
    require(
        failed["this_entry"]
        == {
            "source_callback_invocations": 1,
            "encoder_loaded": False,
            "encoder_completed_calls": 0,
        },
        "failed acquisition loaded encoder",
    )
    require(
        failed["owner_status"]["reserved_units"] == 2, "failed attempt lost reservation"
    )
    before = journal_rows(root / "owner" / "owner.sqlite3")
    captures_before = sorted(
        str(p.relative_to(root)) for p in (root / "owner" / "captures").iterdir()
    )
    denied = invoke("over-budget", "over-budget", expected_returncode=2)
    after = journal_rows(root / "owner" / "owner.sqlite3")
    captures_after = sorted(
        str(p.relative_to(root)) for p in (root / "owner" / "captures").iterdir()
    )
    require(
        before == after and captures_before == captures_after,
        "over-budget attempt changed retained work",
    )
    require(
        "reservation denied" in denied["reason"], "unexpected over-budget rejection"
    )
    require(
        sha(Path(args.weights).read_bytes()) == args.weights_sha256,
        "shared weight file changed",
    )
    require(
        source_pins == {str(p.relative_to(repo)): sha(p.read_bytes()) for p in code},
        "qualification source changed",
    )
    report = {
        "schema": "perc1.owned-cli-qualification.v1",
        "engineering_status": "PASS",
        "scientific_status": "HOLD",
        "production_daemon_integrated": False,
        "source_scope": "operator-pinned local files; generated engineering image/text",
        "source_sha256": source_pins,
        "model_identity": {
            "weights_file_sha256": args.weights_sha256,
            "projection_file_sha256": args.projection_sha256,
            "executed_model": produced["model"],
        },
        "input_identity": {
            "image_sha256": sha(image_bytes),
            "raster_rgb_sha256": sha(rgb),
            "text_sha256": sha(text_bytes),
            "scope_input_sha256": sha(scope_input),
            "scope_digest": args.scope_digest,
            "source_frontier": frontier,
            "native_wire_sha256": sha(native),
            "native_rgb_bytes": len(rgb),
        },
        "steps": steps,
        "next_task": next_task,
        "actual_source_callback_invocations": 2,
        "actual_completed_encoder_calls": 1,
        "replay_exact": True,
        "cold_readback_exact": True,
        "over_budget_no_new_reservation_or_capture": True,
        "shared_original_weights_unchanged": True,
        "phase_wall_ns": time.perf_counter_ns() - started,
        "coordinator_cpu_ns": time.process_time_ns() - cpu,
        "measurement_scope": "phase wall includes setup and all CLI subprocesses; do not add inclusive phase and child wall times; final report write excluded",
        "energy_joules": None,
        "provider_billing": None,
    }
    write_json(root / "REPORT.json", report)
    print(
        json.dumps(
            {
                "engineering_status": "PASS",
                "output": str(root),
                "actual_completed_encoder_calls": 1,
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "output",
        "weights",
        "weights-sha256",
        "projection",
        "projection-sha256",
        "scope-digest",
        "scope-input",
    ):
        parser.add_argument("--" + name, required=True)
    qualify(parser.parse_args())


if __name__ == "__main__":
    main()
