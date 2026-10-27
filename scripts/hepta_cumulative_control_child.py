#!/usr/bin/env python3
"""Continue one real control for ten steps; never grant Hepta authority."""

import argparse
import gc
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_cumulative_controls as campaign


def run(args):
    raw = args.input.read_bytes()
    campaign.require(hashlib.sha256(raw).hexdigest() == args.input_sha256, "input pin")
    request = json.loads(raw)
    runtime, plan = campaign.checked_runtime(Path(request["chain"]))
    campaign.require(
        request["schema"] == "hepta-cumulative-control-input-v1"
        and request["plan"] == plan
        and request["child_source_sha256"] == runtime.file_sha(__file__)
        and request["helper_source_sha256"] == runtime.file_sha(campaign.__file__)
        and request["authority"] == campaign.NO_AUTHORITY,
        "frozen cumulative control context",
    )
    role, number = request["role"], request["round"]
    campaign.require(role in campaign.ROLES and number in (2, 3), "control role/round")
    parent = request["parent"]
    campaign.check_parent(parent, role, number - 1, runtime, plan)
    campaign.verify_runtime_snapshot()
    output = Path(request["output"])
    campaign.require(output.is_absolute() and output.is_dir(), "supervisor output")
    observer = runtime.Observer(output, plan["backend"])
    start, cpu_start = time.monotonic_ns(), time.process_time_ns()
    report = dict(
        schema="hepta-cumulative-control-actual-v1",
        scope="public-task-cumulative-control-no-installation-authority",
        request_sha256=args.input_sha256,
        role=role,
        round=number,
        parent=parent,
        chain_commit=campaign.CHAIN_SHA,
        experiment=runtime.identity(plan),
        original_plan_unchanged=True,
        optimizer_state_resumed=False,
        optimizer_reset_each_round=True,
        recipe=plan["recipes"][role],
        seed=plan["seed"],
        authority=campaign.NO_AUTHORITY,
    )
    try:
        materials = Path(request["materials"])
        manifest, _ = observer.stage(
            "public-material-verification", lambda: runtime.verify_materials(materials)
        )
        campaign.require(plan == runtime.experiment_plan(manifest), "exact frozen plan")
        imports = observer.stage("runtime-import", lambda: runtime.runtime_import(plan))
        torch, device, _, _, _, save_file, load_file = imports
        model, tokenizer, shapes, _ = observer.stage(
            "model-load", lambda: runtime.load_model(materials, plan, imports)
        )
        contract, contract_raw, cid = observer.stage(
            "derived-material-check",
            lambda: runtime.make_contract(
                model, tokenizer, shapes, materials, manifest, plan
            ),
        )
        campaign.require(cid == campaign.CONTRACT, "original V2 target")
        campaign.require(
            contract_raw == Path(parent["contract_path"]).read_bytes(),
            "actual loaded target differs from control contract",
        )
        artifact_path = Path(parent["directory"]) / "artifact.safetensors"
        campaign.require(
            runtime.file_sha(artifact_path) == parent["file_sha256"], "parent file"
        )
        if role == "fresh-budget-matched-lora":
            import llm_parent_material as parent_material
            import llm_runtime_parent_step as parent_step

            model = observer.stage(
                "adapter-insertion",
                lambda: runtime.insert_lora(model, plan, role, torch),
            )
            factors, _ = parent_material.verify_parent(
                Path(parent["contract_path"]),
                Path(parent["directory"]) / "wrapped-adapter.json",
                artifact_path,
                expected_contract=cid,
                expected_adapter=parent["artifact"],
                expected_file_sha256=parent["file_sha256"],
            )
            loaded = observer.stage(
                "actual-parent-byte-readback",
                lambda: parent_step.copy_factors(
                    model, contract, factors, parent["artifact"], torch
                ),
            )
            del factors
        else:
            tensors = observer.stage(
                "parent-file-load", lambda: load_file(str(artifact_path))
            )
            target = runtime.backbone_tensors(model, shapes)
            campaign.require(set(target) == set(tensors), "full control tensor set")
            with torch.no_grad():
                for name, parameter in target.items():
                    source = tensors[name]
                    campaign.require(
                        source.shape == parameter.shape
                        and source.dtype == torch.float32
                        and torch.isfinite(source).all().item(),
                        "full control tensor shape/dtype/values",
                    )
                    parameter.copy_(source.to(device))
            index = {
                name: runtime.tensor_descriptor(tensor)
                for name, tensor in target.items()
            }
            loaded = (
                runtime.contract_module()
                .H("llm-tensor-index-v1", runtime.contract_module().canonical(index))
                .hex()
            )
            campaign.require(
                loaded == parent["artifact"], "full control parent readback"
            )
            del tensors, source, index
            gc.collect()
        campaign.require(loaded == parent["artifact"], "exact measured parent")
        rows = [row for row in plan["tasks"] if row["partition"] == "training"]
        schedule = []
        for step in range(plan["training_steps"]):
            row = rows[step % len(rows)]
            prompt = runtime.prompt_tokens(tokenizer, row, plan["input_tokens_max"])
            target_tokens = tokenizer.encode(
                row["expected_output"], add_special_tokens=False
            )
            target_tokens += [tokenizer.eos_token_id] * 3
            schedule.append(
                dict(
                    step=step,
                    task=row["id"],
                    input_ids=prompt + target_tokens,
                    labels=[-100] * len(prompt) + target_tokens,
                )
            )
        runtime.save(output / "token-schedule.json", schedule)
        report.update(
            actual_parent_readback=loaded,
            actual_device=str(device),
            actual_threads=torch.get_num_threads(),
            token_schedule_sha256=runtime.file_sha(output / "token-schedule.json"),
            schedule_observation_scope="actual-tokenizer-inputs-and-fixed-original-trainer; no-independent-instruction-trace",
        )
        training = observer.stage(
            "training",
            lambda: runtime.train(model, tokenizer, plan, role, torch, device),
        )
        campaign.require(
            training["steps"] == plan["training_steps"]
            and training["tokens"] == sum(len(row["input_ids"]) for row in schedule)
            and training["supervised_tokens"]
            == sum(sum(x != -100 for x in row["labels"]) for row in schedule),
            "actual measured training schedule",
        )
        after_index = {
            name: runtime.tensor_descriptor(tensor)
            for name, tensor in runtime.backbone_tensors(model, shapes).items()
        }
        after_backbone = (
            runtime.contract_module()
            .H("llm-tensor-index-v1", runtime.contract_module().canonical(after_index))
            .hex()
        )
        kind = plan["recipes"][role]["kind"]
        if kind == "lora":
            campaign.require(
                after_backbone == contract["backbone"]["index_root"], "frozen backbone"
            )
            wrapped, artifact, tensors = runtime.wrap_adapter(model, contract, cid)
            (output / "wrapped-adapter.json").write_bytes(wrapped)
        else:
            campaign.require(
                after_backbone != loaded, "full control changed from actual parent"
            )
            artifact, tensors = after_backbone, runtime.backbone_tensors(model, shapes)
        campaign.require(artifact != loaded, "control training changed parent")
        observer.stage(
            "artifact-save",
            lambda: save_file(
                {
                    name: tensor.detach().cpu().contiguous()
                    for name, tensor in tensors.items()
                },
                str(output / "artifact.safetensors"),
            ),
        )
        (output / "target-contract.json").write_bytes(contract_raw)
        artifact_record = dict(
            schema="hepta-cumulative-control-artifact-v1",
            role=role,
            cumulative_control_label=campaign.ROLES[role],
            round=number,
            artifact=artifact,
            contract=cid,
            kind=kind,
            source_model=runtime.WEIGHT_SHA,
            experiment=runtime.identity(plan),
            parent_backbone=contract["backbone"]["index_root"]
            if kind == "lora"
            else loaded,
            resulting_backbone=after_backbone,
            file_sha256=runtime.file_sha(output / "artifact.safetensors"),
            actual_parent=parent,
            native_admission_accepted=False,
            scope="cumulative-diagnostic-protocol-role-is-not-a-fresh-control",
        )
        runtime.save(output / "artifact.json", artifact_record)
        campaign.check_parent(parent, role, number - 1, runtime, plan)
        report.update(
            outcome="success",
            artifact=artifact_record,
            training=training,
            inherited_campaign=parent["cumulative_campaign"],
            cumulative_campaign={
                name: parent["cumulative_campaign"][name] + training[name]
                for name in campaign.COUNT_FIELDS
            },
        )
    except BaseException as error:
        report.update(
            outcome="failed", error_type=type(error).__name__, reason=str(error)[:512]
        )
        raise
    finally:
        report.update(
            cost_events=observer.events,
            observed_wall_ns=time.monotonic_ns() - start,
            observed_cpu_ns=time.process_time_ns() - cpu_start,
            process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * 1024,
            cost_scope="own Linux process observations; not equal total resource cost",
        )
        runtime.save(output / "actual-receipt.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
