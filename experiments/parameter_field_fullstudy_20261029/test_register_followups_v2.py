"""Synthetic metadata integration tests; no model, tensor, or endpoint decoding."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import register_followups_v2 as reg


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.source = {"sha256": hashlib.sha256(b"fixture freeze").hexdigest(),
                       "registered_commit": hashlib.sha1(b"fixture source identity").hexdigest()}
        self.registration = {"_sha256": hashlib.sha256(b"fixture amendment").hexdigest()}

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reg.encode(value) if isinstance(value, (dict, list)) else value)
        return reg.descriptor(path)

    def relative(self, path, value, base):
        return {**self.write(path, value), "path": path.relative_to(base).as_posix()}

    def make_a(self):
        for seed in reg.SEEDS:
            directory = self.raw / "stage_A" / f"seed-{seed}"
            rows = []
            for schedule in range(6000, 6004):
                for method in reg.METHODS:
                    identity = f"seed-{seed}-schedule-{schedule}-{method}"
                    item = self.relative(directory / "paths" / (identity + ".state"), b"opaque fixture state", directory / "paths")
                    rows.append({**item, "id": identity, "seed": seed, "schedule_id": schedule, "method": method})
            self.write(directory / "paths/PATHS.json", {"complete": True, "training_complete": True, "phase": "A", "seed": seed,
                "new_endpoint_roles_opened": [], "paths": rows})
            complete = self.relative(directory / "COMPLETE.json", {"complete": True, "phase": "A", "seed": seed,
                "path_count": 16, "costs": {"scheduled_gradient_microsteps": 39168}, "source_freeze_sha256": self.source["sha256"],
                "registered_commit": self.source["registered_commit"]}, self.raw)
            self.write(self.raw / "operations" / f"A-seed-{seed}.COMPLETE.json", {"complete": True, "phase": "A", "seed": seed,
                "attempt_id": "attempt02", "source_freeze_sha256": self.source["sha256"], "registered_commit": self.source["registered_commit"],
                "scientific_protocol_sha256": reg.PROTOCOL_SHA, "operational_amendment_sha256": self.registration["_sha256"],
                "scientific_source_bytes_unchanged": True, "post_execution_storage_check": True, "scientific_complete": complete})
            bank = directory / "bank"
            records = []
            for schedule in range(6000, 6004):
                for prefix in ("baseline", "balanced"):
                    for step in range(0, 288, 48):
                        stem = f"schedule-{schedule}-{prefix}-step-{step}"
                        parent = self.write(bank / (stem + ".state"), b"opaque fixture parent")
                        for action in range(4):
                            self.write(bank / f"{stem}-action-{action}.npz", b"not an actual NPZ; intentionally opaque")
                        records.append({"seed": seed, "schedule_id": schedule, "prefix": prefix, "step": step,
                            "parent_sha256": parent["sha256"], "parent_bytes": parent["bytes"],
                            "prefix_replay_equal": True, "branches": [{"action": action} for action in range(4)]})
            for method in reg.METHODS[1:]:
                for kind in ("head", "bank"):
                    self.write(bank / f"{method}-{kind}.npz", b"opaque head or feature bytes")
            self.write(bank / "trace.jsonl.gz", b"opaque trace; never decoded")
            self.write(bank / "BANK.json", {"complete": True, "seed": seed, "records": records,
                "heads": {method: {} for method in reg.METHODS[1:]}})

    def test_complete_a_metadata_then_checkpoint_mutation_is_rejected(self):
        self.make_a()
        entries, artifacts = reg.ab_population(self.raw, "A", self.source, self.registration)
        self.assertEqual((len(entries), len({e["id"] for e in entries})), (48, 48))
        self.assertIn(str(self.raw / "operations/A-seed-17.COMPLETE.json"), artifacts)
        reg.bank_population(self.raw)
        Path(entries[0]["path"]).write_bytes(b"mutated")
        with self.assertRaisesRegex(ValueError, "Artifact bytes differ"):
            reg.ab_population(self.raw, "A", self.source, self.registration)

    def test_bank_population_rejects_missing_branch_and_changed_parent(self):
        self.make_a()
        path = self.raw / "stage_A/seed-17/bank/schedule-6000-baseline-step-0-action-2.npz"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Missing or symlink"):
            reg.bank_population(self.raw)
        path.write_bytes(original)
        (path.parent / "schedule-6000-baseline-step-0.state").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Artifact bytes differ"):
            reg.bank_population(self.raw)

    def test_operation_requires_resource_completion_and_actual_training_identity(self):
        self.make_a()
        path = self.raw / "operations/A-seed-29.COMPLETE.json"
        original = reg.read(path)
        for field, changed in (("post_execution_storage_check", False), ("seed", 17), ("source_freeze_sha256", "0" * 64)):
            self.write(path, {**original, field: changed})
            with self.assertRaisesRegex(ValueError, "Operation ancestry"):
                reg.ab_population(self.raw, "A", self.source, self.registration)
        self.write(path, original)
        self.write(path.with_name("A-seed-29.FAILED.json"), {"complete": False})
        with self.assertRaisesRegex(ValueError, "Failed operation"):
            reg.ab_population(self.raw, "A", self.source, self.registration)

    def test_equal_length_duplicate_checkpoint_metadata_does_not_pass_grid(self):
        self.make_a()
        path = self.raw / "stage_A/seed-43/paths/PATHS.json"
        value = reg.read(path)
        value["paths"][-1] = deepcopy(value["paths"][0])
        self.write(path, value)
        with self.assertRaisesRegex(ValueError, "checkpoint grid"):
            reg.ab_population(self.raw, "A", self.source, self.registration)

    def test_safe_artifact_rejects_escape_and_symlink(self):
        target = self.root / "outside"
        item = self.write(target, b"data")
        for relative in ("../outside", str(target)):
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                reg.checked(self.raw, {**item, "path": relative})
        (self.raw / "linked").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "escaped"):
            reg.checked(self.raw, {**item, "path": "linked"})

    def test_git_commit_checks_real_source_bytes_not_only_forty_hex(self):
        repository = self.root / "git"
        repository.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repository), *args], stderr=subprocess.PIPE)
        git("init", "-q")
        source = repository / "source.py"
        source.write_text("registered = True\n")
        git("add", "source.py")
        git("-c", "user.name=Metadata Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        commit = git("rev-parse", "HEAD").decode().strip()
        with patch.object(reg, "ROOT", repository):
            reg.committed_sources(repository, commit, {"source.py": reg.file_hash(source)})
            source.write_text("registered = False\n")
            with self.assertRaisesRegex(ValueError, "absent from the declared local commit"):
                reg.committed_sources(repository, commit, {"source.py": reg.file_hash(source)})
            with self.assertRaisesRegex(ValueError, "full source commit"):
                reg.committed_sources(repository, "0" * 40, {"source.py": reg.file_hash(source)})

    def test_full_fixed_queue_extension_preserves_prior_jobs_and_rejects_duplicates(self):
        queue = reg.read(reg.ROOT / reg.PREFIX / "registrations/QUEUE_ATTEMPT02_INITIAL.json")
        for row in queue["jobs"]:
            row["argv"][row["argv"].index("--root") + 1] = str(self.raw)
        before = deepcopy(queue)
        args = SimpleNamespace(root=self.raw, assets=self.root, amendment=self.root / "ops.json", amendment_sha256="a" * 64)
        additions = [reg.job(p, self.root / f"{p}.json", "b" * 64, args, reg.INITIAL_IDS, seed)
                     for p in ("B", "R") for seed in reg.SEEDS]
        additions.append(reg.job("W", self.root / "W.json", "c" * 64, args, reg.INITIAL_IDS))
        extended = reg.queue_extension(queue, additions, self.raw, False)
        endpoints = [reg.job(p, self.root / f"{p}_endpoint.json", "d" * 64, args,
                            reg.INITIAL_IDS | reg.FOLLOWUP_IDS, endpoint=True) for p in ("A", "B", "C")]
        final = reg.queue_extension(extended, endpoints, self.raw, True)
        self.assertEqual((queue, final["jobs"][:4], len(final["jobs"]), final["finalize"]), (before, before["jobs"], 14, True))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            reg.queue_extension(extended, [additions[0]], self.raw, False)
        changed = deepcopy(endpoints)
        changed[0]["requires"].append("not-registered")
        with self.assertRaisesRegex(ValueError, "Unknown dependency"):
            reg.queue_extension(extended, changed, self.raw, True)

    def seal_phase(self, phase, seed, complete):
        directory = self.raw / ("stage_" + phase)
        if seed is not None:
            directory = directory / f"seed-{seed}"
        binding = {"source_freeze_sha256": self.source["sha256"], "registered_commit": self.source["registered_commit"]}
        if phase == "C":
            complete["binding"].update(binding)
        else:
            complete.update(binding)
        item = self.relative(directory / "COMPLETE.json", complete, self.raw)
        token = f"{phase}-seed-{seed}" if seed is not None else f"{phase}-all"
        self.write(self.raw / "operations" / (token + ".COMPLETE.json"), {**binding, "complete": True,
            "phase": phase, "seed": seed, "attempt_id": "attempt02", "scientific_protocol_sha256": reg.PROTOCOL_SHA,
            "operational_amendment_sha256": self.registration["_sha256"], "scientific_source_bytes_unchanged": True,
            "post_execution_storage_check": True, "scientific_complete": item})

    def test_c_requires_all_own_warmstarts_and_both_policies(self):
        stage = self.raw / "stage_C"
        warmstarts, paths, artifacts = [], [], []
        for role, seeds in (("development", range(701, 703)), ("evaluation", range(801, 809))):
            for seed in seeds:
                for mode in ("ordinary", "dual"):
                    item = self.relative(stage / f"warm-{mode}-{seed}.pt.gz", b"opaque checkpoint", stage)
                    artifacts.append(item)
                    warmstarts.append({"role": role, "seed": seed, "mode": mode, "checkpoint": item})
                    if role == "evaluation":
                        for policy in ("baseline", "field"):
                            item = self.relative(stage / f"end-{mode}-{seed}-{policy}.pt.gz", b"opaque terminal", stage)
                            artifacts.append(item)
                            paths.append({"seed": seed, "mode": mode, "policy": policy, "checkpoint": item})
        plan = {"fixture": "metadata only"}
        complete = {"schema": "hepta.fullstudy.C.complete-seal.1", "complete": True, "training_complete": True,
            "new_endpoint_roles_opened": [], "plan": plan, "audit_count": 4, "literal_tensor_checkpoints": 52,
            "physical_gradient_microsteps": 57536, "scientific_gradient_microsteps": 57152, "replay_gradient_microsteps": 384,
            "binding": {"protocol_sha256": reg.PROTOCOL_SHA, "hcsn_reference_commit": "68eb16caa9c14c7b5729585c86d9c293018a987c"},
            "work": {"counts": {k + ".scheduled_gradient_microsteps": v for k, v in
                {"warmup": 8000, "bank": 46080, "evaluation": 3072, "replay_audit": 384}.items()}},
            "artifacts": artifacts, "warmstarts": warmstarts, "paths": paths}
        self.seal_phase("C", None, complete)
        entries, unused = reg.c_population(self.raw, self.source, self.registration, plan)
        self.assertEqual(len(entries), 48)
        complete["warmstarts"][-1] = deepcopy(complete["warmstarts"][-2])
        self.seal_phase("C", None, complete)
        with self.assertRaisesRegex(ValueError, "paired population"):
            reg.c_population(self.raw, self.source, self.registration, plan)

    def test_w_r_metadata_rejects_a_duplicated_reconstructed_terminal(self):
        self.make_a()
        witness = {"complete": True, "new_endpoint_roles_opened": [], "scheduled_gradient_microsteps": 2880, "records": []}
        for seed in reg.SEEDS:
            directory = self.raw / "stage_W" / f"seed-{seed}"
            record = {"seed": seed, "parent": {"schedule": 6000, "prefix": "baseline", "clock": 48}, "branches": [],
                "original_bank_sha256": reg.file_hash(self.raw / "stage_A" / f"seed-{seed}" / "bank/BANK.json"),
                "original_head_sha256": reg.file_hash(self.raw / "stage_A" / f"seed-{seed}" / "bank/field12-head.npz")}
            for key in ("original_parent", "reflected_parent", "geometry"):
                record[key] = self.relative(directory / (key + ".data"), b"opaque witness", directory)
            for action in range(4):
                branch = {"action": action}
                for key in ("first_state", "terminal_state", "outputs"):
                    item = self.relative(directory / f"{action}-{key}.data", b"opaque witness", directory)
                    if key == "outputs":
                        item["file_sha256"] = item.pop("sha256")
                    branch[key] = item
                record["branches"].append(branch)
            witness["records"].append(record)
        self.seal_phase("W", None, witness)
        for seed in reg.SEEDS:
            rows = []
            for schedule in range(6000, 6004):
                for prefix in ("baseline", "balanced"):
                    for step in range(0, 288, 48):
                        for action in range(4):
                            stem = self.raw / "stage_R" / f"seed-{seed}" / f"schedule-{schedule}-{prefix}-step-{step}-action-{action}"
                            rows.append({"seed": seed, "schedule_id": schedule, "prefix": prefix, "parent_clock": step,
                                "action": action, "all_original_deterministic_receipts_equal": True,
                                "checkpoint": self.relative(Path(str(stem) + ".bin.gz"), b"opaque terminal", self.raw),
                                "trace": self.relative(Path(str(stem) + ".trace.json.gz"), b"opaque trace", self.raw)})
            replay = {"complete": True, "new_endpoint_roles_opened": [], "terminal_count": 192, "scheduled_gradient_microsteps": 32256,
                "all_literal_terminal_restores_equal": True, "all_original_component_and_receipt_hashes_equal": True,
                "original_scientific_counts_changed": False, "new_fitting_or_selection": False,
                "reconstructed_terminal_bytes_not_originally_archived": True, "terminals": rows,
                "source_stage_identity": {"source_freeze_sha256": self.source["sha256"], "source_protocol_sha256": reg.PROTOCOL_SHA}}
            self.seal_phase("R", seed, replay)
        sources = {phase: self.source for phase in ("A", "W", "R")}
        artifacts = reg.diagnostic_population(self.raw, sources, self.registration)
        self.assertIn(str(self.raw / "stage_R/seed-43/COMPLETE.json"), artifacts)
        replay["terminals"][-1] = deepcopy(replay["terminals"][0])
        self.seal_phase("R", 43, replay)
        with self.assertRaisesRegex(ValueError, "terminal grid"):
            reg.diagnostic_population(self.raw, sources, self.registration)

    def test_written_cost_preserves_exact_zero_for_nonzero_unchanged_child_counters(self):
        self.make_a()
        source_root = reg.ROOT
        for name in ("register_followups_v2.py", "witness.py", "replay_terminals.py", "PROTOCOL.json", "PROTOCOL_R.json"):
            self.write(self.root / reg.PREFIX / name, (source_root / reg.PREFIX / name).read_bytes())
        amendment = self.write(self.root / "OPS.json", {"fixture": "metadata only"})
        queue = reg.read(source_root / reg.PREFIX / "registrations/QUEUE_ATTEMPT02_INITIAL.json")
        for row in queue["jobs"]:
            argv = row["argv"]
            argv[argv.index("--root") + 1] = str(self.raw)
            argv[argv.index("--freeze") + 1] = str(self.root / (row["phase"] + ".json"))
            row["freeze_sha256"] = self.source["sha256"]
        saved_queue = self.write(self.root / "QUEUE.json", queue)
        args = SimpleNamespace(stage="followups", root=self.raw, output=self.root / "bundle", assets=self.root,
            amendment=amendment["path"], amendment_sha256=self.registration["_sha256"], source_git_root=self.root,
            source_commit=self.source["registered_commit"], queue=saved_queue["path"], expected_queue_sha256=saved_queue["sha256"],
            a_freeze=str(self.root / "A.json"), c_freeze=str(self.root / "C.json"),
            a_freeze_sha256=self.source["sha256"], c_freeze_sha256=self.source["sha256"])
        def synthetic_parent(path, expected_sha, phase, registration):
            return ({**self.source, "path": str(path), "protocol_sha256": reg.PROTOCOL_SHA, "source_root": str(self.root)},
                    {"source_files": {}, "scientific_parent": {"synthetic": True}})
        original_getrusage = reg.resource.getrusage
        def counters(kind):
            return SimpleNamespace(ru_utime=.01, ru_stime=.02) if kind == reg.resource.RUSAGE_CHILDREN else original_getrusage(kind)
        # Source/Git ancestors are synthetic; all population, hashes, queue construction,
        # immutable bundle writes, and the actual cost-producing code execute.
        with patch.object(reg, "ROOT", self.root), patch.object(reg, "source_descriptor", side_effect=synthetic_parent), \
                patch.object(reg, "load_registration", return_value={**self.registration, "raw_root": str(self.raw)}), \
                patch.object(reg, "verify_job"), patch.object(reg, "committed_sources"), \
                patch.object(reg.resource, "getrusage", side_effect=counters):
            result = reg.register(args)
        cost = reg.read(result["registration_cost"]["path"])
        self.assertEqual(cost["child_process_cpu_seconds"], 0.)
        self.assertEqual(cost["scheduled_gradient_microsteps"], 0)
        self.assertGreater(cost["wall_seconds"], 0)
        self.assertEqual(result["job_count"], 11)
        self.assertFalse(result["queue_activated"])

    def test_existing_bundle_is_never_overwritten(self):
        destination = self.root / "bundle"
        self.write(destination / "proof.txt", b"retained")
        args = SimpleNamespace(root=self.raw, output=destination, assets=self.root, amendment=self.root / "ops")
        with self.assertRaisesRegex(ValueError, "already exists"):
            reg.register(args)
        self.assertEqual((destination / "proof.txt").read_bytes(), b"retained")

    def test_import_does_not_load_numpy_torch_or_scientific_models(self):
        result = subprocess.run([sys.executable, "-B", "-c",
            "import sys; import experiments.parameter_field_fullstudy_20261029.register_followups_v2; "
            "assert 'numpy' not in sys.modules and 'torch' not in sys.modules; print('stdlib only')"],
            cwd=reg.ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "stdlib only")


if __name__ == "__main__":
    unittest.main()
