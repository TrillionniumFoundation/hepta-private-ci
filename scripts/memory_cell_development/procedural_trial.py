"""Freeze and run action-alignment development; no prospective-task claims."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from procedural_support import (
    FINAL,
    OPERATIONS,
    SCOPE,
    TARGET,
    TEMPLATES,
    command,
    diagnostic,
    execute,
    extract_fixture,
    save,
    sha,
)


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    original = args.output / "original"
    source = extract_fixture(args.repo, original, args.ruff)
    facts, observations = [], {}
    cases = {
        "F401": "import math\n\ndef identity(value):\n    return value\n",
        "E731": "identity = lambda value: value\n",
    }
    for code, program in cases.items():
        root = args.output / "teaching" / code
        root.mkdir(parents=True)
        (root / "original.py").write_text(program)
        _, codes = diagnostic(args.ruff, root, "original.py", root / "diagnostic")
        assert codes == [code]
        rule = command(
            [str(args.ruff), "rule", code, "--output-format=json"], root, root / "rule"
        )
        assert rule["returncode"] == 0
        entity = code + " " + json.loads((root / "rule/stdout.log").read_text())["name"]
        outcomes = {}
        for index, (operation, flags) in enumerate(OPERATIONS.items()):
            folder = root / str(index)
            folder.mkdir()
            (folder / "case.py").write_text(program)
            action = command(
                [str(args.ruff), "check", "--no-cache", *flags, "case.py"],
                folder,
                folder / "action",
            )
            after = command(
                [str(args.ruff), "check", "--no-cache", "case.py"],
                folder,
                folder / "after",
            )
            semantic = command(
                [
                    str(args.python),
                    "-B",
                    "-c",
                    "import runpy; f=runpy.run_path('case.py')['identity']; assert [f(x) for x in (None,0,7,'a')]==[None,0,7,'a']",
                ],
                folder,
                folder / "semantic",
            )
            outcomes[operation] = dict(
                action=action,
                after=after,
                semantic=semantic,
                success=action["returncode"]
                == after["returncode"]
                == semantic["returncode"]
                == 0,
            )
        candidates = [op for op in OPERATIONS if outcomes[op]["success"]]
        assert candidates
        observation = dict(
            code=code,
            entity=entity,
            program=program,
            outcomes=outcomes,
            label_policy="first successful operation in frozen least-permission order",
        )
        source_digest = save(root / "observation.json", observation)
        observations[code] = observation
        facts.append(
            dict(
                scope=SCOPE,
                entity=entity,
                relation="repair command",
                value=candidates[0],
                source_digest=source_digest,
            )
        )
    _, codes = diagnostic(
        args.ruff, original, TARGET, args.output / "original-diagnostic"
    )
    assert codes == ["E731", "F401"]
    entities = {f["entity"].split()[0]: f["entity"] for f in facts}
    combined = "; ".join(entities[code] for code in codes)
    common = [
        op
        for op in OPERATIONS
        if all(observations[code]["outcomes"][op]["success"] for code in codes)
    ]
    assert common
    training_spec = dict(
        scope=SCOPE,
        facts=facts,
        templates=TEMPLATES,
        rank=8,
        steps=96,
        learning_rate=0.003,
        objective="completion_ce",
    )
    training_pin = save(args.output / "training-spec.json", training_spec)
    protocol = dict(
        schema="hepta.memory.procedural-development.v1",
        registered_at=datetime.now(timezone.utc).isoformat(),
        source_head="ba32a22de7c586ae6a1ac6ebeb5d67b54259021b",
        source=source,
        scope=SCOPE,
        facts=facts,
        templates=TEMPLATES,
        rank=8,
        seeds=[24041, 24043, 24047],
        training_spec_sha256=training_pin,
        steps=96,
        learning_rate=0.003,
        objective="completion_ce",
        questions=[FINAL.format(entities[c]) for c in ("F401", "E731")]
        + [FINAL.format(combined)],
        expected_development_operations=[f["value"] for f in facts],
        task_query_index=2,
        original_task_groups=1,
        prospective_groups=0,
        fixed_operations=OPERATIONS,
        retrieval_operation=common[0],
        input_policy="same typed diagnostic codes and rule names; no source value in model prompts",
        retrieval_policy="intersect successful source operations for all diagnosed codes, then least-permission order",
        exposure="two authored teaching programs and one historical exposed project task; same known failure families",
        task_gate="original pinned Ruff check plus all 76 original semantic tests; only TARGET may change",
        training_cpu_limit_seconds_per_child=180,
        strong_rag_qualified=False,
        full_budget_fission_claim=False,
        retuning_after_outcomes=False,
        base_inventory={
            p.name: dict(bytes=p.stat().st_size, sha256=sha(p.read_bytes()))
            for p in args.model.iterdir()
            if p.is_file()
        },
        implementation={
            str(p.relative_to(args.repo)): sha(p.read_bytes())
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
    )
    pin = save(args.output / "protocol.json", protocol)
    print(
        json.dumps(
            dict(protocol_sha256=pin, frozen_before_training=True, prospective_groups=0)
        )
    )


def trial(args):
    raw = (args.output / "protocol.json").read_bytes()
    assert sha(raw) == args.protocol_sha256
    protocol = json.loads(raw)
    for name, digest in protocol["implementation"].items():
        assert sha((args.repo / name).read_bytes()) == digest
    for name, entry in protocol["base_inventory"].items():
        data = (args.model / name).read_bytes()
        assert len(data) == entry["bytes"] and sha(data) == entry["sha256"]
    runs = args.output / "runs"
    runs.mkdir()
    worker = Path(__file__).with_name("procedural_worker.py")
    pythonpath = args.repo / "scripts/memory_cell"
    records, total_updates, total_queries = [], 0, 0
    for seed in protocol["seeds"]:
        root = runs / str(seed)
        root.mkdir()
        request = dict(
            mode="train",
            training_spec=str(args.output / "training-spec.json"),
            training_spec_sha256=protocol["training_spec_sha256"],
            model=str(args.model),
            seed=seed,
            checkpoint=str(root / "checkpoint"),
        )
        save(root / "train-request.json", request)
        fit = command(
            [str(args.python), str(worker)],
            args.repo,
            root / "train",
            json.dumps(request).encode(),
            pythonpath,
        )
        assert fit["returncode"] == 0, "fit failed; preserve partial work, do not retry"
        result = json.loads((root / "train/stdout.log").read_text())
        total_updates += result["receipt"]["steps"]
        assert result["receipt"]["fact_visits"] == [48, 48]
        for control in (
            ["adapter", "shuffled", "base"]
            if seed == protocol["seeds"][0]
            else ["adapter", "shuffled"]
        ):
            payload = dict(
                model=str(args.model),
                snapshot=result["checkpoint"],
                manifest_sha256=result["manifest_sha256"],
                scope=SCOPE,
                allowed_roots=[f["source_digest"] for f in protocol["facts"]],
                questions=protocol["questions"],
                rank=protocol["rank"],
                seed=seed,
                control=control,
            )
            request = dict(mode="read", payload=payload)
            save(root / (control + "-request.json"), request)
            read = command(
                [str(args.python), str(worker)],
                args.repo,
                root / control,
                json.dumps(request).encode(),
                pythonpath,
            )
            assert read["returncode"] == 0, (
                "read failed; preserve outputs, do not retry"
            )
            journal = json.loads((root / control / "stdout.log").read_text())
            total_queries += len(journal["rows"])
            texts = [row["text"] for row in journal["rows"]]
            execution = execute(
                args.ruff,
                args.python,
                args.output / "original",
                root / (control + "-task"),
                texts[2],
            )
            records.append(
                dict(
                    seed=seed,
                    control=control,
                    raw_texts=texts,
                    read=read,
                    training=fit,
                    known_operations_correct=sum(
                        a.strip() == b
                        for a, b in zip(
                            texts[:2], protocol["expected_development_operations"]
                        )
                    ),
                    task=execution,
                )
            )
        print(
            json.dumps(dict(seed=seed, updates=total_updates, queries=total_queries)),
            flush=True,
        )
    retrieval = execute(
        args.ruff,
        args.python,
        args.output / "original",
        runs / "retrieval-task",
        protocol["retrieval_operation"],
    )
    result = dict(
        schema="hepta.memory.procedural-development-result.v1",
        protocol_sha256=args.protocol_sha256,
        records=records,
        retrieval=retrieval,
        actual_optimizer_updates=total_updates,
        actual_decoder_queries=total_queries,
        model_children=10,
        independent_historical_project_tasks=1,
        prospective_groups=0,
        future_accuracy=None,
        training_cpu_seconds=sum(
            row["training"]["cpu_seconds"]
            for row in records
            if row["control"] == "adapter"
        ),
        full_closure=False,
        production_accepted=False,
        strong_retrieval_advantage=False,
        limitations=[
            "same two known root-cause families",
            "single previously exposed project task repeated across arms/seeds",
            "typed retrieval is not a full RAG repair agent",
            "training/reader costs are measured, OS/runtime and complete deployment costs remain incomplete",
        ],
    )
    save(args.output / "result.json", result)
    print(
        json.dumps(
            dict(
                updates=total_updates,
                queries=total_queries,
                task_successes=[
                    (r["seed"], r["control"], r["task"]["success"]) for r in records
                ],
                retrieval_success=retrieval["success"],
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "run"])
    for name in ("repo", "output", "ruff", "python", "model"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--protocol-sha256")
    args = parser.parse_args()
    for name in ("repo", "output", "ruff", "python", "model"):
        setattr(args, name, getattr(args, name).absolute())
    prepare(args) if args.mode == "prepare" else trial(args)
