"""Try bounded split/recombine/rewire mutations under an oracle task contract."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from structure_probe import verify_freeze
from v5.contracts import INTENTS, canonical, write_json
from v5.graph_assets import Assets, DOMAINS
from legacy_v3.learned_graph import GraphQuery, TypedValue
from legacy_v3.numeric_graph import numeric_executor, shift_month


NEW = ("min3", "sum3", "mean2")


def identity(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Experiment:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.protocol = json.loads((root / "ADAPTIVE_PROTOCOL.json").read_text())
        self.assets = Assets(root.parent / "memory-cell-v5" / "assets")
        self.layout, _ = self.assets.layout()
        self.readers = {domain: self.assets.exact(domain)[0] for domain in DOMAINS}
        self.executors = {domain: numeric_executor(domain, self.readers[domain].read, scope="oracle-adaptive:" + domain) for domain in DOMAINS}
        self.calls = 0
        self.records = []
        self.generation = 0

    def cases(self, operations, dates):
        return [{"domain": domain, "operation": operation, "date": date,
            "key": domain + ":" + operation} for domain in DOMAINS for operation in operations for date in dates]

    def target(self, case):
        t = tuple(map(int, case["date"].split("-")))
        op = case["operation"]
        offsets = (0,) if op == "at" else (-1,) if op == "previous" else (-1, 0) if op in ("change", "mean2") else (-2, -1, 0)
        coordinates = [shift_month(t, offset) for offset in offsets]
        values = self.readers[case["domain"]].read(coordinates)
        if any(value is None for value in values):
            raise ValueError("preregistered numeric task has an unavailable source")
        if op in ("at", "previous"):
            value = values[0]
        elif op == "change":
            value = values[1] - values[0]
        elif op in ("mean3", "mean2"):
            value = sum(values) / len(values)
        elif op == "range3":
            value = max(values) - min(values)
        elif op == "peak3":
            value = max(values)
        elif op == "min3":
            value = min(values)
        else:
            value = sum(values)
        return TypedValue("number", value, tuple(f"{case['domain']}:{y:04d}-{m:02d}" for y, m in coordinates))

    def execute(self, path, case):
        if path is None:
            return None
        if self.calls + len(path) > self.protocol["limits"]["actual_primitive_hop_calls"]:
            raise ValueError("experiment primitive-call budget exhausted")
        address = tuple(map(int, case["date"].split("-")))
        value, receipt = self.executors[case["domain"]].run(tuple(path), TypedValue("address", address),
            GraphQuery("oracle-adaptive:" + case["domain"], "oracle task", case["domain"], case["date"]), expected_generation=1)
        self.calls += receipt["calls"]
        return value

    def discover(self):
        executor = self.executors[DOMAINS[0]]
        paths = [path for path in executor.candidates("address") if executor.specs[path[-1]].output_type == "number"]
        discovered, records = {}, []
        before = self.calls
        for op in NEW:
            cases = self.cases((op,), self.protocol["dates"]["discovery"])
            candidates = []
            for path in paths:
                started = self.calls
                exact = sum(self.execute(path, case) == self.target(case) for case in cases)
                candidates.append({"path": list(path), "exact": exact, "cases": len(cases), "primitive_calls": self.calls - started})
            best = min(candidates, key=lambda row: (-row["exact"], row["primitive_calls"], row["path"]))
            discovered[op] = best["path"]
            records.append({"operation": op, "selected": best, "all_candidates": candidates})
        return discovered, {"records": records, "primitive_calls": self.calls - before, "paths_per_task": len(paths), "gold_paths_consumed": False}

    @staticmethod
    def bindings(state):
        binding = {}
        for cell in state:
            for key in cell["bindings"]:
                if key in binding:
                    raise ValueError("two Cells own the same oracle task")
                binding[key] = cell["path"]
        return binding

    def evaluate(self, state, old_cases, new_cases):
        binding = self.bindings(state)
        before = self.calls
        old = sum(self.execute(binding.get(case["key"]), case) == self.target(case) for case in old_cases)
        new = sum(self.execute(binding.get(case["key"]), case) == self.target(case) for case in new_cases)
        return {"old_exact": old, "old_total": len(old_cases), "new_exact": new, "new_total": len(new_cases), "primitive_calls": self.calls - before}

    @staticmethod
    def utility(metrics, size, calls=0):
        return 0.5 * metrics["old_exact"] / metrics["old_total"] + 0.5 * metrics["new_exact"] / metrics["new_total"] - 1e-6 * size - 1e-7 * calls

    def consider(self, name, candidate, old_cases, new_cases):
        if len(self.records) >= self.protocol["limits"]["mutation_candidates"]:
            raise ValueError("mutation candidate budget exhausted")
        index = len(self.records) + 1
        path = self.output / f"candidate-{index:02d}.json"
        write_json(path, candidate)
        size = len(canonical(candidate))
        record = {"proposal": name, "before_sha256": identity(self.state), "candidate_sha256": identity(candidate),
            "candidate_cells": len(candidate), "candidate_metadata_bytes": size, "candidate_file": path.name,
            "generation_before": self.generation, "migration_bytes": 0, "accepted": False}
        if len(candidate) > self.protocol["limits"]["cells_or_unique_programs"] or size > self.protocol["limits"]["state_metadata_bytes"]:
            record.update(reason="admission budget rejected", evaluation_primitive_calls=0)
        else:
            metrics = self.evaluate(candidate, old_cases, new_cases)
            utility = self.utility(metrics, size, metrics["primitive_calls"])
            previous_utility = self.utility(self.metrics, len(canonical(self.state)))
            retained = metrics["old_exact"] >= self.metrics["old_exact"]
            record.update(metrics=metrics, utility=utility, incumbent_utility=previous_utility,
                retention_pass=retained, evaluation_primitive_calls=metrics["primitive_calls"])
            if retained and utility > previous_utility:
                self.state, self.metrics = candidate, metrics
                self.generation += 1
                record.update(accepted=True, reason="strict utility gain with old-task retention", migration_bytes=size,
                    generation_after=self.generation)
                write_json(self.output / f"checkpoint-{self.generation:02d}.json", self.state)
            else:
                record["reason"] = "old-task retention failed" if not retained else "no strict utility improvement"
        record["active_sha256_after"] = identity(self.state)
        self.records.append(record)
        write_json(self.output / f"receipt-{index:02d}.json", record)

    def merged(self, groups):
        state = copy.deepcopy(self.state)
        picked = [cell for cell in state if cell["id"] in groups]
        if len(picked) < 2:
            raise ValueError("merge requires at least two existing Cells")
        child = {"id": "merge-" + str(len(self.records) + 1), "parents": sorted(groups),
            "path": picked[0]["path"], "bindings": sorted(key for cell in picked for key in cell["bindings"])}
        return [cell for cell in state if cell["id"] not in groups] + [child]

    def consolidate(self):
        grouped = {}
        for cell in self.state:
            grouped.setdefault(tuple(cell["path"]), []).append(cell)
        return [{"id": "consolidated-" + str(i), "parents": [cell["id"] for cell in cells],
            "path": list(path), "bindings": sorted(key for cell in cells for key in cell["bindings"])}
            for i, (path, cells) in enumerate(sorted(grouped.items()))]

    def offspring(self, op, domains, discovered):
        return copy.deepcopy(self.state) + [{"id": "child-" + str(len(self.records) + 1), "parents": [self.state[0]["id"]],
            "path": discovered[op], "bindings": [domain + ":" + op for domain in domains]}]

    def run(self):
        old = self.cases(INTENTS, self.protocol["dates"]["old_retention"])
        new = self.cases(NEW, self.protocol["dates"]["new_selection"])
        # Availability preflight is not policy training. The first attempt's
        # unavailable 2025 unemployment evaluation month is preserved separately.
        for case in self.cases((*INTENTS, *NEW), self.protocol["dates"]["final_evaluation"]):
            self.target(case)
        discovered, discovery = self.discover()
        self.state = [{"id": domain + ":" + op, "parents": [], "path": list(self.layout.select(op, "address")), "bindings": [domain + ":" + op]} for domain in DOMAINS for op in INTENTS]
        write_json(self.output / "checkpoint-00.json", self.state)
        self.metrics = self.evaluate(self.state, old, new)
        initial = {"metrics": self.metrics, "metadata_bytes": len(canonical(self.state)), "cells": len(self.state)}
        self.consider("overbudget-first-split", self.offspring("min3", ("co2",), discovered), old, new)
        self.consider("incompatible-old-merge", self.merged(["co2:at", "co2:peak3"]), old, new)
        self.consider("equivalent-at-merge", self.merged(["co2:at", "temperature:at"]), old, new)
        self.consider("specialist-min3-co2", self.offspring("min3", ("co2",), discovered), old, new)
        self.consider("consolidate-identical-programs", self.consolidate(), old, new)
        for op in ("sum3", "mean2"):
            self.consider("specialist-" + op, self.offspring(op, DOMAINS, discovered), old, new)
        for domain in DOMAINS:
            if domain != "co2":
                self.consider("min3-clone-" + domain, self.offspring("min3", (domain,), discovered), old, new)
        self.consider("destructive-merge-all", self.merged([cell["id"] for cell in self.state]), old, new)
        self.consider("recombine-equivalent-programs", self.consolidate(), old, new)
        binding_ids = {key: cell["id"] for cell in self.state for key in cell["bindings"]}
        self.consider("incompatible-new-merge", self.merged([binding_ids["co2:sum3"], binding_ids["co2:mean2"]]), old, new)
        wrong = copy.deepcopy(self.state)
        for cell in wrong:
            if "co2:mean2" in cell["bindings"]:
                cell["path"] = discovered["sum3"]
        self.consider("wrong-mean2-rewire", wrong, old, new)
        final_path = self.output / "FINAL_STATE.json"
        write_json(final_path, self.state)
        restored = json.loads(final_path.read_text())
        if identity(restored) != identity(self.state):
            raise AssertionError("state persistence changed the selected topology")
        before_final = self.calls
        final_old = self.cases(INTENTS, self.protocol["dates"]["final_evaluation"])
        final_new = self.cases(NEW, self.protocol["dates"]["final_evaluation"])
        final_metrics = self.evaluate(restored, final_old, final_new)
        adaptive_calls = self.calls
        # The static table gets exactly the same discovered programs and shared
        # codec/operation catalog, charged the same discovery work and cap.
        static_programs = {**{op: list(self.layout.select(op, "address")) for op in INTENTS}, **discovered}
        paths = sorted(set(tuple(path) for path in static_programs.values()))
        table = {"programs": paths, "bindings": {domain + ":" + op: paths.index(tuple(path)) for domain in DOMAINS for op, path in static_programs.items()}}
        write_json(self.output / "STATIC_TABLE.json", table)
        static_state = [{"path": path, "bindings": [key for key, index in table["bindings"].items() if index == i]} for i, path in enumerate(paths)]
        static_metrics = self.evaluate(static_state, final_old, final_new)
        report = {"schema": "memory-cell-v6.oracle-adaptive-results.v1", "protocol_sha256": hashlib.sha256((self.root / "ADAPTIVE_PROTOCOL.json").read_bytes()).hexdigest(),
            "discovery": discovery, "initial": initial, "mutations": self.records,
            "final": {"metrics": final_metrics, "cells": len(restored), "metadata_bytes": len(canonical(restored)), "state_sha256": identity(restored), "reloaded": True},
            "static_same_program_baseline": {"metrics": static_metrics, "unique_programs": len(paths), "metadata_bytes": len(canonical(table)), "primitive_calls_with_charged_discovery": discovery["primitive_calls"] + static_metrics["primitive_calls"]},
            "costs": {"adaptive_total_primitive_calls": adaptive_calls, "adaptive_pre_final_calls": before_final,
                "proposed_state_bytes": sum(record["candidate_metadata_bytes"] for record in self.records),
                "accepted_migration_bytes": sum(record["migration_bytes"] for record in self.records),
                "actual_state_proposals": len(self.records), "accepted": sum(record["accepted"] for record in self.records), "rejected": sum(not record["accepted"] for record in self.records)},
            "consumed_assets": self.assets.verify_consumed(), "held_natural_language_rows_read": 0,
            "shared_fixed_asset_bytes": self.assets.consumed_bytes(),
            "new_neural_parameter_training": False, "production_kernel_admission": False,
            "conclusion": "Actual bounded program discovery and mutation/retention decisions; fixed oracle task entry. Compare against the static same-information table before claiming structural value. Natural language entry remains unqualified."}
        write_json(self.output / "RESULTS.json", report)
        print(json.dumps({"final": report["final"], "static": report["static_same_program_baseline"], "costs": report["costs"]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    freeze = verify_freeze(root)
    args.output.mkdir(parents=True, exist_ok=False)
    Experiment(root, args.output).run()
    if verify_freeze(root) != freeze:
        raise AssertionError("adaptive experiment mutated the frozen semantic source/model")
