"""Independent source, ownership, full-wire and raw-accounting engineering review."""
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import tempfile
import time

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..planner_r20_20261101 import execution as old
from ..support_retention_r16_20261101.compression import AnchoredPackedMemory, BlockLaw, PackedBeliefMemory
from . import execution as new

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def semantic(value):
    return {k:v for k,v in value.items() if k not in ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}


class ExpectedChange(ast.NodeTransformer):
    def visit_Assign(self, node):
        node = self.generic_visit(node)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "correct":
            return [node, ast.parse("snapshot = memory.checkpoint()").body[0]]
        return node

    def visit_keyword(self, node):
        node = self.generic_visit(node)
        if node.arg == "checkpoint_sha256":
            assert ast.unparse(node.value) == "memory.checkpoint()['sha256']"
            node.value = ast.parse("snapshot['sha256']", mode="eval").body
        elif node.arg == "memory":
            assert ast.unparse(node.value) == "memory.checkpoint()"
            node.value = ast.Name(id="snapshot", ctx=ast.Load())
        return node


def source_proof():
    left = ast.parse(Path(old.__file__).read_text())
    right = ast.parse(Path(new.__file__).read_text())
    a = next(x for x in left.body if isinstance(x, ast.FunctionDef) and x.name == "execute")
    b = next(x for x in right.body if isinstance(x, ast.FunctionDef) and x.name == "execute")
    assert ast.dump(ExpectedChange().visit(a), include_attributes=False) == ast.dump(b, include_attributes=False)
    def imports(tree):
        result = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                module = node.module
                if node.level == 1 and module in ("planner", "persistence"):
                    module = "planner_r20_20261101." + module
                result.append((module, [(item.name, item.asname) for item in node.names]))
        return result
    assert imports(left) == imports(right)
    return dict(exact_expected_function_transform=True, imports_resolve_to_same_implementations=True)


def actor_state(memory):
    result = dict(clock=memory.clock, operations=copy.deepcopy(memory.operations))
    for name in ("beliefs", "packed", "anchor_times"):
        if name in memory.__dict__:
            result[name] = memory.__dict__[name].tolist()
    return result


def ownership(models):
    records = []
    for name, cls, projection in [("full", BeliefMemory, "full"), ("block", PackedBeliefMemory, "block"),
                                  ("anchored", AnchoredPackedMemory, "block")]:
        memory = cls(BlockLaw.from_payload(models["hx"]["payload"]), [0, 1, 2, 3], projection)
        before = actor_state(memory)
        first, second = memory.checkpoint(), memory.checkpoint()
        assert actor_state(memory) == before and first == second
        stable = canonical(first)
        field = "packed" if "packed" in memory.__dict__ else "beliefs"
        memory.__dict__[field][0, 0] += 1e-7
        memory.clock += .1
        memory.operations["writes"] += 7
        if "anchor_times" in memory.__dict__:
            memory.anchor_times[0] += .01
        assert canonical(first) == stable
        current = actor_state(memory)
        first[field][0][0] += .01
        first["operations"]["writes"] += 8
        if "anchor_times" in first:
            first["anchor_times"][0] += .02
        assert actor_state(memory) == current
        records.append(dict(memory=name, pure_repeat=True, actor_to_snapshot_isolated=True, snapshot_to_actor_isolated=True))
    return records


def actual_wire(module, law, episode, variant, representation, path):
    cls = module.AnchoredPackedMemory if representation == "anchored" else module.BeliefMemory
    checkpoint, persist, fsync = cls.checkpoint, module.persist, os.fsync
    calls, wires, bodies, descriptors = [], [], [], []
    def exported(memory):
        calls.append(memory.clock)
        return checkpoint(memory)
    def committed(target, body):
        before = canonical(body)
        saved = persist(target, body)
        assert canonical(body) == before
        raw = target.read_bytes()
        assert canonical(saved) == raw
        copied = dict(saved); checksum = copied.pop("sha256")
        assert sha(canonical(copied)) == checksum
        bodies.append(before); wires.append(raw)
        return saved
    def synced(fd):
        descriptors.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        return fsync(fd)
    cls.checkpoint, module.persist, os.fsync = exported, committed, synced
    try:
        result = module.execute(law, episode, variant, representation, path, KernelCache())
    finally:
        cls.checkpoint, module.persist, os.fsync = checkpoint, persist, fsync
    return dict(result=result, calls=calls, bodies=bodies, wires=wires, fsync=descriptors)


def main():
    began, parent_cpu = time.perf_counter(), time.process_time()
    protocol = json.loads((HERE / "DEVELOPMENT_PROTOCOL.json").read_text())
    models = json.loads(gzip.decompress((ROOT / protocol["training_archive"]).read_bytes()))["calibration"]["models"]
    raw = json.loads(gzip.decompress((HERE / "development_01/PROOFS.json.gz").read_bytes()))
    checks = 0
    for pair in raw["cases"]:
        a, b = pair["old"], pair["new"]
        assert semantic(a["result"]) == semantic(b["result"])
        assert len(a["wire_sha256"]) == len(b["wire_sha256"]) == 6
        assert a["wire_sha256"] == b["wire_sha256"]
        assert a["checkpoint_count"] == 18 and b["checkpoint_count"] == 12
        assert a["fsync_descriptors"] == b["fsync_descriptors"] == ["file", "directory"] * 6
        for query in range(6):
            assert len(set(a["checkpoint_clocks"][query*3:query*3+3] + b["checkpoint_clocks"][query*2:query*2+2])) == 1
        checks += 11
    assert len(raw["corrupt_restore_guards"]) == 4
    old_total = new_total = 0.0
    for path in sorted((HERE / "development_01").glob("*.json.gz")):
        if path.name == "PROOFS.json.gz":
            continue
        body = json.loads(gzip.decompress(path.read_bytes()))
        group = body["group"]
        for record in body["records"]:
            assert semantic(record["results"]["old"]) == semantic(record["results"]["new"])
            checks += 1
        costs = {version:group["preparation"][version] + sum(row["results"][version]["cpu_seconds"] for row in body["records"])
                 for version in ("old", "new")}
        assert costs == group["cpu_with_preparation"]
        assert abs(costs["new"]/costs["old"] - group["new_old_cpu_ratio"]) < 1e-14
        peaks = group["memory_peaks"]
        assert abs(max(peaks["new"])/max(peaks["old"]) - group["new_old_peak_ratio"]) < 1e-14
        old_total += costs["old"]; new_total += costs["new"]
        checks += 3
    proof = source_proof()
    alias = ownership(models)
    episode = make_episode(Law(), 2100991 * 10**9, "ood")
    captured = []
    with tempfile.TemporaryDirectory(prefix="hcsn-r21-independent-wire-") as temporary:
        for model in protocol["models"]:
            for representation in protocol["representations"]:
                for variant in protocol["variants"]:
                    results = {name:actual_wire(module, BlockLaw.from_payload(models[model]["payload"]), episode,
                                               variant, representation, Path(temporary)/(name+".json"))
                               for name,module in (("old",old),("new",new))}
                    a,b = results["old"],results["new"]
                    assert semantic(a["result"]) == semantic(b["result"])
                    assert a["bodies"] == b["bodies"] and a["wires"] == b["wires"]
                    assert len(a["calls"]) == 18 and len(b["calls"]) == 12
                    assert a["fsync"] == b["fsync"] == ["file", "directory"]*6
                    captured.append(dict(model=model,representation=representation,variant=variant,
                                         body_base64=[base64.b64encode(x).decode() for x in a["bodies"]],
                                         wire_base64=[base64.b64encode(x).decode() for x in a["wires"]],
                                         old_calls=a["calls"],new_calls=b["calls"],fsync=a["fsync"],same=True))
    encoded = canonical(captured)
    compressed = gzip.compress(encoded, mtime=0)
    (HERE / "INDEPENDENT_FULL_WIRES.json.gz").write_bytes(compressed)
    receipt = json.loads((HERE / "development_01/PROCESS_RECEIPT.json").read_text())
    assert receipt["exit_code"] == 0
    result = dict(passed=True, source_proof=proof, snapshot_ownership=alias, retained_raw_checks=checks,
                  independently_executed_pairs=len(captured), full_body_comparisons=len(captured)*6,
                  full_wire_comparisons=len(captured)*6, real_fsync_calls=len(captured)*2*12,
                  raw_wire_sha256=sha(encoded), gzip_sha256=sha(compressed), gzip_bytes=len(compressed),
                  development_cpu=dict(old=old_total,new=new_total,ratio=new_total/old_total),
                  development_complete_child_cpu_seconds=receipt["complete_child_cpu_seconds"],
                  independent_parent_cpu_seconds=time.process_time()-parent_cpu, independent_wall_seconds=time.perf_counter()-began,
                  source_sha256={str(Path(module.__file__).relative_to(ROOT)):sha(Path(module.__file__).read_bytes()) for module in (old,new)},
                  limitation="Exact current classes and synchronous trusted single-writer persist only; no claim for side-effectful checkpoint overrides or concurrent actor mutation. Engineering aggregate gain is small and group ratios mixed; no formal adoption qualification.")
    (HERE / "INDEPENDENT_REVIEW.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__":
    main()
