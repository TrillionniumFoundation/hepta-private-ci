"""Read actual local Circuit tensors and an original HEPLCP02 operation side by side.

Supply source trees containing cell_experiments and the Chain scripts on PYTHONPATH.
Usage: python compare_native_source.py MODEL_RUN OFFLINE_EVALUATION_RUN CHAIN_EVIDENCE_ROOT NEW_REPORT
No trust, checkpoint, ledger request or payout is created by this content review.
"""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import struct

from safetensors import safe_open
from cell_experiments import coding_sft, data
from cell_experiments.online_v4 import circuit_bundle
from cell_learning_iteration_join import (
    bundle_digest,
    decode_native_learning_checkpoint,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pon_digest(tag, raw):
    name = tag.encode()
    return sha(
        b"TRNM-PON1\0"
        + struct.pack("<H", len(name))
        + name
        + struct.pack("<I", len(raw))
        + raw
    )


def tensor_inventory(path):
    with safe_open(path, framework="pt", device="cpu") as f:
        values = {}
        for name in f.keys():
            t = f.get_tensor(name).detach().contiguous()
            raw = t.numpy().tobytes()
            values[name] = dict(
                shape=list(t.shape),
                dtype=str(t.dtype),
                nbytes=len(raw),
                sha256=sha(raw),
            )
        return values


def checked(value, reason):
    if not value:
        raise ValueError(reason)


def native_evidence(root):
    checkpoints = root / "chain-reader" / "adopt-v1"
    inputs = root / "adopt-v1" / "model" / "training" / "worker"
    initial_raw = (checkpoints / "initial.bin").read_bytes()
    final_raw = (checkpoints / "completed.bin").read_bytes()
    initial, _ = decode_native_learning_checkpoint(initial_raw)
    final, replay = decode_native_learning_checkpoint(final_raw)
    checked(
        initial["request"] == final["request"] and not initial["receipts"],
        "different historical operations",
    )
    descriptor = next(
        r["observation"]["candidate"]
        for r in final["receipts"]
        if r["observation"]["tag"] == 2
    )
    selected = bundle_digest(descriptor)
    checked(selected == replay["next_task_bundle"], "historical use differs")
    manifest = json.loads((inputs / "parent-material.json").read_bytes())
    path = inputs / "artifact.safetensors"
    contract_raw = (inputs / "target-contract.json").read_bytes()
    wrapped_raw = (inputs / "wrapped-adapter.json").read_bytes()
    raw_hash = sha(path.read_bytes())
    adapter = pon_digest("wrapped-decoder-lora-material-v1", wrapped_raw)
    contract = pon_digest("target-decoder-adapter-contract-v1", contract_raw)
    checked(
        raw_hash == manifest["file_sha256"]
        and adapter == manifest["adapter"] == descriptor["components"]["cell_adapter"]
        and contract == manifest["contract"] == descriptor["components"]["composition"],
        "historical component bytes differ",
    )
    targets = json.loads(contract_raw)["targets"]
    tensors = tensor_inventory(path)
    return dict(
        operation_id=final["request"]["operation_id"],
        initial_sha256=sha(initial_raw),
        completed_sha256=sha(final_raw),
        receipt_count=len(final["receipts"]),
        version_digest=selected,
        adapter_file_sha256=raw_hash,
        adapter_wrapper_digest=adapter,
        composition_digest=contract,
        tensor_count=len(tensors),
        insertion_count=len(targets),
        dimensions=sorted(
            {(t["in_features"], t["out_features"], t["rank"]) for t in targets}
        ),
        layer_projections=sorted({t["module"].split(".")[-1] for t in targets}),
    )


def tiny_source(root):
    req = json.loads((root / "request.json").read_bytes())
    candidate = req["candidate"]
    checked(
        circuit_bundle.checked_bundle(candidate, root) == data.digest(candidate),
        "candidate custody",
    )
    model = candidate["models"]["source"]
    parent = req["parent"]["models"]["source"]
    checked(model["parent"] == data.digest(parent), "source lineage differs")
    path = root / model["runtime"]["adapter_directory"] / "adapter_model.safetensors"
    config = json.loads(path.with_name("adapter_config.json").read_bytes())
    tensors = tensor_inventory(path)
    after = hashlib.sha256()
    with closing(coding_sft.load_predictor(model, root)) as active:
        for key, param in active.model.named_parameters():
            if "lora_" in key:
                raw = param.detach().cpu().contiguous().numpy().tobytes()
                checked(
                    sha(raw)
                    == tensors[key.replace(".default.weight", ".weight")]["sha256"],
                    "on-disk adapter differs from live tensor",
                )
                after.update(key.encode())
                after.update(raw)
        training = json.loads((root / "TRAINING_RECORD.json").read_bytes())
        replay = active.predict(training)
    receipt = json.loads(path.with_name("TRAINING.json").read_bytes())
    checked(
        after.hexdigest() == receipt["parameter_after"]
        and receipt["parent"] == data.digest(parent)
        and receipt["child"] == data.digest(model)
        and replay["answer"] == receipt["corrected_prediction"]["answer"]
        and data.verify_answer(training, replay["answer"])["success"],
        "source training readback differs",
    )
    with closing(coding_sft.load_predictor(parent, root)) as initial:
        old_output = initial.predict(training)
    checked(
        old_output["answer"] == receipt["initial_answer"]
        and not data.verify_answer(training, old_output["answer"])["success"],
        "original parent action differs",
    )
    control_rows = {}
    for arm in ("parent", "candidate"):
        row = json.loads((root / arm / "0000.json").read_bytes())
        trace = row["prediction"]["circuit_trace"]
        checked(
            trace["nodes"][0]["output"]["loaded_model_digest"]
            == data.digest(req[arm]["models"]["source"]),
            "future generation belongs to a different source",
        )
        control_rows[arm] = dict(
            answers=[n["output"]["answer"] for n in trace["nodes"]],
            success=row["verification"]["success"],
        )
    return dict(
        circuit_bundle_sha256=data.digest(candidate),
        source_manifest_sha256=data.digest(model),
        source_parent_manifest_sha256=data.digest(parent),
        adapter_file_sha256=sha(path.read_bytes()),
        file_nbytes=path.stat().st_size,
        rank=config["r"],
        alpha=config["lora_alpha"],
        insertion_modules=config["target_modules"],
        tensors=tensors,
        readback_parameter_state_sha256=after.hexdigest(),
        training_before=old_output["answer"],
        training_after=replay["answer"],
        training_reference=training["final_answer"],
        starting_loss=receipt["loss"],
        future=control_rows,
    )


def formal_run(model_run, evaluation):
    req = json.loads((evaluation / "request.json").read_bytes())
    committed = json.loads((evaluation / "READBACK.json").read_bytes())
    result = json.loads((evaluation / "evaluation" / "RESULT.json").read_bytes())
    freeze = json.loads((evaluation / "FROZEN.json").read_bytes())
    checked(
        req == json.loads((model_run / "request.json").read_bytes())
        and data.digest(result) == committed["result_sha256"]
        and data.digest(req) == committed["request_sha256"] == result["request_sha256"]
        and data.digest(freeze) == committed["freeze_sha256"],
        "two-phase run commitment differs",
    )
    totals = {}
    for a, arm in enumerate(("parent", "candidate")):
        material = req[arm]
        circuit_bundle.checked_bundle(material, model_run)
        trace_end = json.loads(
            (evaluation / "evaluation" / arm / "END.json").read_bytes()
        )
        checked(
            trace_end == result["cold_receipts"][a]
            and trace_end["model_digest"] == data.digest(material),
            "cold arm identity differs",
        )
        rows = []
        with closing(
            coding_sft.load_predictor(
                circuit_bundle.input_manifest(material), model_run
            )
        ) as bound:
            for i, panel in enumerate(("future", "retention")):
                record = req[panel][0]
                row = json.loads(
                    (evaluation / "evaluation" / arm / f"{i:04d}.json").read_bytes()
                )
                pred = row["prediction"]
                checked(
                    row["panel"] == panel
                    and row["task_sha256"] == data.digest(record)
                    and pred["pid"] == trace_end["pid"]
                    and data.digest(row) == trace_end["row_hashes"][i]
                    and data.digest(row["outcome"])
                    == data.digest(data.verify_answer(record, pred["answer"])),
                    "task or outcome binding differs",
                )
                circuit_bundle.check_prediction(material, pred, record, bound.tokenizer)
                cost = pred["circuit_trace"]["cost"]
                rows.append(
                    dict(
                        panel=panel,
                        answer=pred["answer"],
                        passed=row["outcome"]["success"],
                        model_calls=cost["model_calls"],
                        input_tokens=cost["input_tokens"],
                        output_tokens=cost["output_tokens"],
                    )
                )
        totals[arm] = rows
    return dict(
        request_canonical_sha256=data.digest(req),
        freeze_canonical_sha256=data.digest(freeze),
        result_canonical_sha256=data.digest(result),
        result_file_sha256=sha(
            (evaluation / "evaluation" / "RESULT.json").read_bytes()
        ),
        rows=totals,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("evaluation", type=Path)
    p.add_argument("chain_evidence", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    old = native_evidence(args.chain_evidence)
    tiny = tiny_source(args.run)
    checked(
        old["adapter_file_sha256"] != tiny["adapter_file_sha256"]
        and old["version_digest"] != tiny["circuit_bundle_sha256"],
        "expected distinct material",
    )
    checked_evaluation = formal_run(args.run, args.evaluation)
    factor_shapes = [
        v["shape"] for name, v in tiny["tensors"].items() if "lora_" in name
    ]
    mismatches = {
        "target_module": tiny["insertion_modules"] != old["layer_projections"],
        "rank": all(dim[2] != tiny["rank"] for dim in old["dimensions"]),
        "insertion_count": len(tiny["insertion_modules"]) != old["insertion_count"],
        "factor_count": len(factor_shapes) != old["tensor_count"],
        "interface_shape": all(
            [tiny["rank"], dim[0]] not in factor_shapes for dim in old["dimensions"]
        ),
    }
    report = dict(
        schema="hepta.research.native-circuit-byte-comparison.v1",
        historical_native=old,
        authored_circuit=tiny,
        matches_original_native_material_interface=not any(mismatches.values()),
        measured_interface_mismatches=mismatches,
        current_two_phase_evaluation=checked_evaluation,
        scope="historical native identity readback and current tiny source tensor equality only",
        generated_native_checkpoint_count=0,
        distinct_real_users=0,
        native_full_learning_settlements_established_by_this_review=0,
    )
    coding_sft.write_new(args.out, report)
    print(sha(args.out.read_bytes()))


if __name__ == "__main__":
    main()
