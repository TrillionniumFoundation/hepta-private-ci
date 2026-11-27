"""Actual child workers and metadata-only source resolution for edge trials."""

import json
from importlib import metadata
from pathlib import Path
import sys

from evolution_common import digest, file_digest, read_json, require, retain
from edge_budget import ModelBudget


class EdgeRuntime:
    def __init__(self, repo, output, budget_scripts, protocol):
        self.repo, self.output, self.protocol = (
            Path(repo).resolve(),
            Path(output),
            protocol,
        )
        retain(
            self.output / "runtime-identity.json",
            dict(
                executable=sys.executable,
                executable_sha256=file_digest(Path(sys.executable).resolve()),
                python=sys.version,
                packages={
                    d.metadata["Name"]: d.version for d in metadata.distributions()
                },
                complete_dependency_bytes_verified=False,
            ),
        )
        for name in ("memory_cell", "memory_cell_service", "memory_cell_network"):
            sys.path.insert(0, str(self.repo / "scripts" / name))
        from model_process import run_child
        from source_store import SourceStore

        self.run_child = run_child
        self.authority = SourceStore(
            self.output / "sources.sqlite",
            protocol["scope"],
            "graph-authority",
            "semantic",
        )
        self.budget = ModelBudget(self.output, budget_scripts, digest(protocol))
        self.model = self.output / "tiny-base"
        self.reader_count = 0
        self.entry_template = protocol["source_templates"][0]

    def source_setup(self):
        writes = []
        for case in self.protocol["cases"]:
            for relation in ("hint", "color"):
                receipt = self.authority.write(
                    case["case_id"] + "_" + relation,
                    case["case_id"],
                    relation,
                    case[relation],
                )
                writes.append(receipt.__dict__)
        snapshot = self.authority.snapshot()
        retain(self.output / "initial-source-events.json", writes)
        retain(self.output / "initial-source-snapshot.json", snapshot)
        return snapshot

    def frontier(self):
        snapshot = self.authority.snapshot()
        return {k: snapshot[k] for k in ("scope", "epoch", "roots", "revoked")}

    def resolver(self, cell, entity, relation):
        read = self.authority.read(entity, relation)
        if read.status.value != "answered":
            return None
        template = (
            self.entry_template
            if relation == "hint"
            else "What is the color for {entity}?"
        )
        return dict(
            entity=entity,
            relation=relation,
            source_roots=list(read.source_roots),
            question=template.format(entity=entity),
        )

    def worker(self, request, label):
        receipt = self.run_child(
            Path(__file__).with_name("edge_model_worker.py"),
            input_text=json.dumps(request),
            timeout=120,
            receipt_dir=self.output / "processes",
            operation="edge-" + request["mode"],
        )
        retain(self.output / "worker-results" / (label + ".process.json"), receipt)
        value = json.loads(receipt["stdout"])
        retain(self.output / "worker-results" / (label + ".json"), value)
        return value

    def build(self):
        request = dict(mode="build", protocol=self.protocol, output=str(self.model))
        return self.budget.effect(
            "base", request, lambda: self.worker(request, "base"), lambda _: {}
        )

    def train(self, label, facts):
        p = self.protocol
        request = dict(
            mode="train",
            repo=str(self.repo),
            model=str(self.model),
            output=str(self.output / "training" / label / "checkpoint"),
            scope=p["scope"],
            rank=p["rank"],
            seed=p["seed"],
            steps=p["steps_per_training"],
            learning_rate=p["learning_rate"],
            templates=p["training_templates"],
            facts=facts,
        )
        retain(self.output / "training" / label / "source-request.json", request)

        def measured(result):
            training = result["training"]
            require(
                training["steps"]
                == len(training["losses"])
                == training["actual_model_forwards"],
                "actual optimizer/forward evidence mismatch",
            )
            return dict(
                decoder_updates=training["steps"], train_tokens=training["input_tokens"]
            )

        return self.budget.effect(
            "train",
            request,
            lambda: self.worker(request, label),
            measured,
            updates=p["steps_per_training"],
        )

    def reader(self, active, prompt):
        label = f"read-{self.reader_count:04d}"
        self.reader_count += 1
        request = dict(
            model=str(self.model),
            snapshot=active.directory,
            manifest_sha256=active.manifest_sha256,
            scope=active.scope,
            allowed_roots=list(active.roots),
            questions=[prompt],
            rank=self.protocol["rank"],
            seed=self.protocol["seed"],
            control="adapter",
        )
        retain(self.output / "reads" / (label + ".request.json"), request)

        def invoke():
            receipt = self.run_child(
                self.repo / "scripts/memory_cell/parametric_worker.py",
                input_text=json.dumps(request),
                timeout=120,
                receipt_dir=self.output / "processes",
                operation="edge-decoder",
            )
            journal = json.loads(receipt["stdout"])
            require(
                len(journal["rows"]) == 1 and journal["rows"][0]["question"] == prompt,
                "raw reader question alignment",
            )
            require(
                not any(
                    journal[k]
                    for k in ("fact_input", "retrieval_input", "answer_lexicon_input")
                ),
                "source answer entered decoder",
            )
            journal["decoder_process"] = {
                k: v for k, v in receipt.items() if k != "stdout"
            }
            retain(self.output / "reads" / (label + ".journal.json"), journal)
            return journal

        def measured(journal):
            row = journal["rows"][0]
            require(
                row["input_tokens"] == len(row["prompt_token_ids"])
                and row["generated_tokens"] == len(row["token_ids"]),
                "raw token counter mismatch",
            )
            return dict(
                decoder_queries=1,
                input_tokens=row["input_tokens"],
                output_tokens=row["generated_tokens"],
            )

        return self.budget.effect("infer", request, invoke, measured, queries=1)[
            "rows"
        ][0]

    def component_inventory(self):
        kinds = {
            "tiny-base": "base",
            "training": "adapter",
            "topology": "owner",
            "learned-policy": "router",
            "sources.sqlite": "source",
            "source-snapshot": "runtime",
        }
        components = [
            dict(
                name=p.name,
                path=str(p),
                kind=kinds.get(p.name, "evidence"),
                private=p.name in ("training", "topology", "learned-policy"),
            )
            for p in sorted(self.output.iterdir())
            if p.name != "inventories"
        ]
        if (self.output / "inventories").exists():
            components.append(
                dict(
                    name="inventories",
                    path=str(self.output / "inventories"),
                    kind="evidence",
                    private=False,
                )
            )
        return self.budget.inventory(components)
