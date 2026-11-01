"""Actual frozen B/C replay kernels, called only after complete archive admission.

New physical work and literal files are append-only and outside model snapshots.
This newly reconstructed candidate is not asserted identical to lost scratch code.
"""
from copy import deepcopy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import random
import time

from . import counterfactual as k, native_common as n

PREFIX = "experiments.parameter_field_fullstudy_20261029."
V3 = "experiments.multimodal_output_portfolio.field_bridge_v3_20261027."


def original_module(source, name):
    module = importlib.import_module(name)
    expected = Path(source) / (name.replace(".", "/") + ".py")
    k.need(Path(module.__file__).resolve() == expected, "Original module imported from another source")
    return module


def physical_steps(values):
    return sum(value for key, value in values.items()
               if key == "scheduled_gradient_microsteps" or key.endswith(".scheduled_gradient_microsteps"))


def semantic_receipt(stage, value):
    excluded = {"resources"} if stage == "B" else {"work_before", "work_after"}
    return {key: deepcopy(item) for key, item in value.items() if key not in excluded}


def normalized(spec, receipt, fixed_guard):
    stage = spec["stage"]
    if stage == "B":
        count = physical_steps(receipt["resources"])
        tape = receipt["schedule_sha256"]
        action, schedule = receipt["action_index"], receipt["schedule_id"]
        advances = receipt["clock_advances_on_rejection"]
    else:
        count = physical_steps(receipt["work_after"]["counts"]) - physical_steps(receipt["work_before"]["counts"])
        rows = receipt["microsteps"]
        k.need([row["step"] for row in rows] == list(range(receipt["start"], receipt["end"])),
               "C physical tape trace is incomplete")
        tape = k.digest([{key: row[key] for key in ("step", "tape_identity", "noise_seed")} for row in rows])
        action, schedule, advances = receipt["action"], receipt["schedule"], receipt["clock_advances"]
    return {
        "action": action, "start": receipt["start"], "end": receipt["end"],
        "schedule": schedule, "multiplier": receipt["multiplier"],
        "native_before": deepcopy(receipt["before"]), "native_candidate": deepcopy(receipt["candidate"]),
        "native_after": deepcopy(receipt["after"]), "accepted": receipt["accepted"],
        "guard_delta": receipt["guard_delta"],
        "guard_outputs_sha256": k.digest({"values": receipt["guard_values"], "outputs": receipt["guard_output_sha256"]}),
        "fixed_guard_sha256": fixed_guard, "tape_sha256": tape,
        "clock_advances": advances, "scheduled_gradient_microsteps": count,
    }


class LiteralOutput:
    def __init__(self, root, health=lambda *args: None):
        self.root, self.health = Path(root), health
        k.need(self.root.is_absolute() and self.root.resolve() == self.root, "Noncanonical output root")
        self.root.mkdir(parents=True, exist_ok=False)
        self.files = {}

    def bytes(self, relative, raw):
        path = Path(relative)
        k.need(not path.is_absolute() and ".." not in path.parts and str(path) == relative
               and relative not in self.files, "Unsafe or repeated literal output")
        self.health(len(raw))
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            k.need(stream.write(raw) == len(raw), "Partial literal write")
            stream.flush()
            os.fsync(stream.fileno())
        item = n.descriptor(target)
        k.need(item["bytes"] == len(raw) and item["sha256"] == hashlib.sha256(raw).hexdigest(), "Literal readback differs")
        self.files[relative] = item
        return item

    def json(self, relative, value):
        return self.bytes(relative, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())

    def unchanged(self):
        for item in self.files.values():
            n.checked(item)


class PhysicalLedger:
    def __init__(self, output):
        self.output, self.count = output, 0
        self.path = output.root / "PHYSICAL_WORK.jsonl"
        self.stream = self.path.open("xb")

    def add(self, phase, name, amount):
        k.need(name == "scheduled_gradient_microsteps" and type(amount) is int and amount == 1,
               "Physical counter changed its completed-step unit")
        self.count += 1
        raw = (json.dumps({"sequence": self.count, "phase": phase, "name": name, "amount": amount},
                          sort_keys=True, allow_nan=False) + "\n").encode()
        self.stream.write(raw)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.output.health()

    def close(self):
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
        item = n.descriptor(self.path)
        self.output.files["PHYSICAL_WORK.jsonl"] = item
        return item


def tracked_cost_type(original, ledger):
    class Tracked(original):
        def add(self, name, amount=1):
            super().add(name, amount)
            if name == "scheduled_gradient_microsteps":
                ledger.add(getattr(self, "phase", "B"), name, amount)
    return Tracked


def consumed_path(admission, relative, role):
    item = admission["store"].descriptor(relative)
    admission["inputs"].hash_only(item["path"], item["sha256"], item["bytes"], role)
    return n.checked(item)


class Base:
    def __init__(self, admission, spec, output):
        k.spec_checked(spec)
        k.need(admission["store"].admitted is True and admission["receipt"]["complete"] is True,
               "Scientific model construction blocked before full original admission")
        self.admission, self.spec, self.output = admission, spec, output
        self.source = n.SOURCE
        self.ledger = PhysicalLedger(output)
        self.calls = {name: {"calls": 0, "wall_seconds": 0., "self_cpu_seconds": 0.}
                      for name in (k.PREDICTORS if spec["stage"] == "B" else ("field12",))}
        self.np, self.torch = importlib.import_module("numpy"), importlib.import_module("torch")
        self.torch.set_num_threads(2 if spec["stage"] == "B" else 1)
        if self.torch.get_num_interop_threads() != 1:
            self.torch.set_num_interop_threads(1)
        self.torch.use_deterministic_algorithms(True)
        self.head_module = original_module(self.source, PREFIX + "heads")
        self.sources = original_module(self.source, PREFIX + "sources")
        self.assets = original_module(self.source, V3 + "assets")

    def source_stable(self):
        run = original_module(self.source, PREFIX + "run_v2")
        run.ensure_loaded_closure(self.admission["config"])
        self.admission["inputs"].unchanged()
        self.admission["metadata"].stable()
        self.output.unchanged()

    def choice(self, name, feature, head):
        k.need(all(self.np.isfinite(value).all() for value in head.values()
                   if isinstance(value, self.np.ndarray)), "Frozen head has a nonfinite array")
        before, cpu = time.monotonic(), time.process_time()
        try:
            action, choice = self.head_module.choose(head, feature, self.spec["baseline"])
            k.need(k.choice_action(self.spec, choice) == action, "Original finite chooser differs")
            return choice
        finally:
            row = self.calls[name]
            row["calls"] += 1
            row["wall_seconds"] += time.monotonic() - before
            row["self_cpu_seconds"] += time.process_time() - cpu

    def scheduled_microsteps(self):
        k.need(physical_steps(self.costs.values) == self.ledger.count, "Physical ledger differs from original counter")
        return self.ledger.count

    def save_features(self, features):
        raw = io.BytesIO()
        self.np.savez_compressed(raw, **features)
        return self.output.bytes(self.prefix + "/FEATURES.npz", raw.getvalue())

    def prepare(self, spec):
        raise NotImplementedError

    def lock(self, choices, measured):
        spec = self.spec
        old = self.old["trace"][spec["decision"]]
        k.need(choices["field12"] == old["choice"], "Reconstructed original field choice differs")
        self.features_item = self.save_features(measured)
        value = {
            "parent_id": spec["id"], "parent_state_sha256": old["before"],
            "actual_successor_sha256": self.successor(spec["decision"]),
            "original_transaction_fingerprint": k.digest(normalized(spec, old["transaction"], self.fixed_guard)),
            "fixed_guard_sha256": self.fixed_guard,
            "source_trace": self.source_trace, "frozen_head": self.head_items["field12"],
            "original_choice": choices["field12"],
        }
        if spec["stage"] == "B":
            value["frozen_predictors"] = {name: {"head": self.head_items[name], "choice": choices[name]}
                                          for name in k.PREDICTORS}
        item = self.output.json(self.prefix + "/CHOICE_LOCK.json", value)
        value["persisted_choice_lock"] = item
        k.check_lock(spec, value)
        return value


class BBackend(Base):
    def __init__(self, admission, spec, output):
        super().__init__(admission, spec, output)
        self.learning = original_module(self.source, V3 + "learning")
        self.bank = original_module(self.source, PREFIX + "bank")
        self.branching = original_module(self.source, PREFIX + "branching")
        common = original_module(self.source, V3 + "training_common")
        seed = spec["seed"]
        random.seed(291029 + seed)
        self.np.random.seed(291029 + seed)
        self.torch.manual_seed(291029 + seed)
        self.protocol = json.loads((Path(self.learning.__file__).with_name("PROTOCOL.json")).read_text())
        originals, observers, unused = self.assets.load_assets(str(n.ASSETS), [seed], ["reward"])
        corpus = self.sources.load_training_roles(str(n.ASSETS), "B",
            ["development_gradient", "development_rehearsal", "development_probe", "development_guard"])
        self.costs = tracked_cost_type(common.Costs, self.ledger)()
        self.context = self.learning.make_context(originals[seed], corpus, observers, seed, "development", self.protocol, self.costs)
        directory = f"stage_B/seed-{seed}/paths/"
        self.source_trace = admission["store"].descriptor(directory + "PATHS.json")
        paths = admission["store"].read_json(directory + "PATHS.json")
        k.need(paths["complete"] is True and len(paths["paths"]) == 80, "Original B population differs")
        found = [row for row in paths["paths"] if row["method"] == "field12" and row["schedule_id"] == spec["schedule"]]
        k.need(len(found) == 1, "Original field occupancy not unique")
        self.old = found[0]
        terminal = consumed_path(admission, directory + self.old["path"], "original_B_terminal")
        k.need(n.descriptor(terminal)["sha256"] == self.old["sha256"], "B terminal differs from source trace")
        raw = terminal.read_bytes()
        record = self.branching.codec.loads(raw, self.old["sha256"], self.old["bytes"])
        self.binding = record["binding"]
        bank_root = f"stage_A/seed-{seed}/bank/"
        self.head_items = {name: admission["store"].descriptor(bank_root + name + "-head.npz") for name in k.PREDICTORS}
        for name in k.PREDICTORS:
            consumed_path(admission, bank_root + name + "-head.npz", "frozen_original_head")
        self.heads = self.bank.load_heads(admission["store"].root / bank_root)
        self.adapter = self.bank.initialize(self.context, self.binding, spec["schedule"], "field12")
        self.fixed_guard = self.branching.codec.digest(self.context.baseline_guard["values"]["reward"])
        self.source_stable()

    def successor(self, decision):
        return self.old["trace"][decision + 1]["before"] if decision < 5 else self.old["sha256"]

    def snapshot(self):
        raw, digest = self.adapter.seal()
        record = self.branching.codec.loads(raw, digest, len(raw))
        return {"clock": self.adapter.clock, "complete_sha256": digest,
                "dynamics_sha256": self.branching.dynamics_identity(record)["dynamics"],
                "native": self.learning.state_identity(self.adapter.model, self.adapter.optimizer)}

    def prepare(self, spec):
        self.spec, self.prefix = spec, f"parents/{spec['decision']:02d}"
        before, digest = self.adapter.seal()
        k.need(digest == self.old["trace"][spec["decision"]]["before"], "B visited parent did not reconstruct")
        raw, actual, unused, features, receipt = self.bank.measure(self.adapter)
        k.need(raw == before and actual == digest
               and semantic_receipt("B", receipt) == semantic_receipt("B", self.old["trace"][spec["decision"]]["feature_receipt"]),
               "B original feature observation differs")
        self.parent = raw, digest
        self.measured = features
        choices = {name: self.choice(name, features[name], self.heads[name]) for name in k.PREDICTORS}
        return self.lock(choices, features)

    def restore_parent(self):
        self.adapter.restore(*self.parent)

    def transition(self, action, clock):
        k.need(clock == self.adapter.clock, "B transition clock differs")
        return normalized(self.spec, self.adapter.transition(action), self.fixed_guard)

    def advance_original(self, lock):
        action = k.check_lock(self.spec, lock)
        receipt = self.adapter.transition(action)
        k.need(semantic_receipt("B", receipt) ==
               semantic_receipt("B", self.old["trace"][self.spec["decision"]]["transaction"]),
               "B original selected transaction did not replay")
        self.bank.append_history(self.adapter, self.measured["field12"], action, receipt)
        return normalized(self.spec, receipt, self.fixed_guard)

    def seal_state(self, kind, action):
        raw, digest = self.adapter.seal()
        suffix = "parent" if kind == "parent" else f"{kind}-{action}"
        item = self.output.bytes(self.prefix + "/" + suffix + ".state", raw)
        decoded = self.branching.codec.loads(n.checked(item).read_bytes(), item["sha256"], item["bytes"])
        k.need(self.branching.codec.dumps(decoded) == raw, "B literal state round trip differs")
        return {"artifact": item, "state_sha256": digest}

    def restore_literal(self, item, clock):
        self.adapter.restore(n.checked(item).read_bytes(), item["sha256"])
        k.need(self.adapter.clock == clock, "B literal clock differs")


class CBackend(Base):
    def __init__(self, admission, spec, output):
        super().__init__(admission, spec, output)
        self.kernel = original_module(self.source, PREFIX + "architecture_kernel")
        self.training = original_module(self.source, PREFIX + "architecture_training")
        self.state = original_module(self.source, PREFIX + "architecture_state")
        self.features_module = original_module(self.source, PREFIX + "architecture_features")
        complete = admission["store"].read_json("stage_C/COMPLETE.json")
        self.plan = self.kernel.ArchitecturePlan.from_mapping(complete["plan"])
        k.need(self.plan.to_dict() == self.kernel.ArchitecturePlan.from_mapping(
            admission["protocol"]["stage_C"]["execution_plan"]).to_dict(), "C original plan differs")
        unused_c, portable_adapter, unused_gate = n.portable()
        paths = portable_adapter.joined_c_paths(admission["store"])
        matches = [row for row in paths if row["seed"] == spec["seed"] and row["mode"] == spec["architecture"] and row["policy"] == "field"]
        k.need(len(matches) == 1, "C original field path not unique")
        self.old = matches[0]
        rel = self.old["checkpoint"]["path"].removesuffix(".pt.gz") + ".trace.json.gz"
        self.source_trace = admission["store"].descriptor("stage_C/" + rel)
        warm = [row for row in complete["warmstarts"] if row["seed"] == spec["seed"] and row["mode"] == spec["architecture"]]
        k.need(len(warm) == 1, "C original own warmstart not unique")
        self.warm_item = admission["store"].descriptor("stage_C/" + warm[0]["checkpoint"]["path"])
        path = consumed_path(admission, "stage_C/" + warm[0]["checkpoint"]["path"], "original_C_warmstart")
        self.model, self.optimizer, self.warm_record = self.training.load_generator_checkpoint(path, self.source, self.plan)
        originals, observers, unused = self.assets.load_assets(str(n.ASSETS), [], ["reward"])
        corpus = self.sources.load_training_roles(str(n.ASSETS), "C",
            [self.plan.gradient_role, self.plan.rehearsal_role, self.plan.probe_role, self.plan.guard_role])
        self.costs = tracked_cost_type(self.kernel.Work, self.ledger)()
        self.costs.phase = "native_setup"
        self.context = self.kernel.Context(self.model, corpus, observers["reward"], spec["seed"], self.plan, self.costs, output.health)
        self.context.restore(self.model, self.optimizer, self.warm_record["state"])
        self.clock = 0
        k.need(self.context.identity == self.old["metadata"]["context_sha256"]
               and self.warm_record["state_sha256"] == self.old["metadata"]["warmstart_state_sha256"], "C immutable context differs")
        directory = "stage_C/heads/" + spec["architecture"] + "/"
        head_meta = admission["store"].read_json(directory + "HEAD.json")
        self.head_items = {"field12": admission["store"].descriptor(directory + "HEAD_AND_BANK.npz")}
        path = consumed_path(admission, directory + "HEAD_AND_BANK.npz", "frozen_original_C_head")
        with self.np.load(path, allow_pickle=False) as saved:
            self.head = {**head_meta["head"], **{key: saved[key].copy() for key in ("mean", "scale", "coefficients", "intercept")}}
        self.fixed_guard = self.state.digest(self.context.baseline_guard)
        self.costs.phase = "native_replay"
        self.source_stable()

    def successor(self, decision):
        return self.old["decision_state_sha256"][decision]

    def snapshot(self):
        saved = self.context.snapshot(self.model, self.optimizer)
        digest = self.state.digest(saved)
        return {"clock": self.clock, "complete_sha256": digest,
                "dynamics_sha256": k.digest({"clock": self.clock, "complete_sha256": digest}), "native": digest}

    def prepare(self, spec):
        self.spec, self.prefix = spec, f"parents/{spec['decision']:02d}"
        k.need(self.clock == spec["clock"] and self.snapshot()["complete_sha256"] == self.old["trace"][spec["decision"]]["before"],
               "C visited parent did not reconstruct")
        self.parent = self.context.snapshot(self.model, self.optimizer)
        feature, unused, receipt = self.features_module.measure(self.context, self.model, self.optimizer, self.clock, spec["schedule"])
        old = self.old["trace"][spec["decision"]]
        k.need(feature.tolist() == old["field"] and semantic_receipt("C", receipt) == semantic_receipt("C", old["feature_receipt"]),
               "C original feature observation differs")
        choices = {"field12": self.choice("field12", feature, self.head)}
        return self.lock(choices, {"field12": feature})

    def restore_parent(self):
        self.context.restore(self.model, self.optimizer, self.parent)
        self.clock = self.spec["clock"]

    def transition(self, action, clock):
        k.need(clock == self.clock, "C transition clock differs")
        receipt = self.context.block(self.model, self.optimizer, clock, action, self.spec["schedule"])
        self.clock += self.spec["grain"]
        return normalized(self.spec, receipt, self.fixed_guard)

    def advance_original(self, lock):
        action = k.check_lock(self.spec, lock)
        receipt = self.context.block(self.model, self.optimizer, self.clock, action, self.spec["schedule"])
        self.clock += self.spec["grain"]
        k.need(semantic_receipt("C", receipt) == semantic_receipt("C", self.old["trace"][self.spec["decision"]]["transaction"]),
               "C original selected transaction did not replay")
        return normalized(self.spec, receipt, self.fixed_guard)

    def seal_state(self, kind, action):
        saved = self.context.snapshot(self.model, self.optimizer)
        suffix = "parent" if kind == "parent" else f"{kind}-{action}"
        metadata = {"schema": "hepta.visited-counterfactual.C.literal.1", "execution_episode": n.EPISODE,
                    "parent_id": self.spec["id"], "clock": self.clock, "kind": kind, "action": action,
                    "context_sha256": self.context.identity, "plan_sha256": self.state.digest(self.plan.to_dict()),
                    "binding": self.warm_record["metadata"]["binding"], "config": self.model.config}
        item = self.output.bytes(self.prefix + "/" + suffix + ".pt.gz", self.state.checkpoint_bytes(saved, metadata))
        record = self.state.read_checkpoint(n.checked(item))
        k.need(record["metadata"] == metadata and self.state.digest(saved) == record["state_sha256"], "C literal readback differs")
        return {"artifact": item, "state_sha256": record["state_sha256"]}

    def restore_literal(self, item, clock):
        record = self.state.read_checkpoint(n.checked(item))
        k.need(record["metadata"]["clock"] == clock
               and record["metadata"]["context_sha256"] == self.context.identity, "C literal context/clock differs")
        self.context.restore(self.model, self.optimizer, record["state"])
        self.clock = clock


def backend(admission, spec, output):
    return (BBackend if spec["stage"] == "B" else CBackend)(admission, spec, output)


def execute_path(admission, contract_item, path_id, health):
    specs = [row for row in k.PARENTS.values() if row["path_id"] == path_id]
    k.need(len(specs) == 6, "Unknown trajectory")
    output = LiteralOutput(n.ROOT / "shards" / path_id, health)
    output.json("START.json", {"schema": "hepta.visited-counterfactual.shard-start.1",
                              "execution_episode": n.EPISODE, "execution_contract": contract_item,
                              "path_id": path_id, "original_admission": admission["receipt"],
                              "new_terminal_values_opened": False})
    engine = None
    try:
        engine = backend(admission, specs[0], output)
        rows = []
        for spec in specs:
            health()
            lock = engine.prepare(spec)
            result = k.enumerate_parent(spec, lock, engine)
            rows.append(output.json(f"parents/{spec['decision']:02d}/TRAJECTORIES.json", result))
        count = engine.scheduled_microsteps()
        k.need(count == (5328 if specs[0]["stage"] == "B" else 1776), "Shard physical work incomplete")
        engine.ledger.close()
        engine.source_stable()
        k.need(len(output.files) == 74, "Shard literal population differs")
        return output.json("COMPLETE.json", {
            "schema": "hepta.visited-counterfactual.shard-complete.1", "complete": True,
            "execution_episode": n.EPISODE, "execution_contract": contract_item, "path_id": path_id,
            "parents": rows, "parent_count": 6, "primary_tails": 24, "audit_tails": 6,
            "physical_microsteps": count, "head_scoring": engine.calls, "files": dict(output.files),
            "new_terminal_values_opened": False, "new_independent_samples": 0,
            "failed_partial_step_cpu_not_claimed_zero": True})
    except BaseException as error:
        if engine is not None:
            engine.ledger.close()
        output.json("FAILED.json", {"complete": False, "execution_episode": n.EPISODE, "path_id": path_id,
                                   "error_type": type(error).__name__, "message": str(error),
                                   "physical_completed_steps_lower_bound": None if engine is None else engine.ledger.count,
                                   "partial_evidence_preserved": True, "automatic_retry_permitted": False})
        raise
