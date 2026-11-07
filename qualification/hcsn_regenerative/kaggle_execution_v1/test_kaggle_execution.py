"""CPU execution controls with explicit fixtures; zero training/provider calls.

Temporary checkpoints are arbitrary labelled bytes. Selection uses the original
pure function extracted without importing Torch, NumPy or a task generator.
Capsule, ledger, publication-fixture and pinned-source IO are real local IO.
The cloud-window test substitutes only scientific workers and mounted inputs.
"""
import ast
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import capsule_contract as capsule
import cloud_batch as cloud
import finalize_mechanism as finalizer
import native_owner as owner

ARMS = ["regenerative_dual", "smooth_dual", "margin_only", "call_only",
        "risk_only", "endpoint", "no_reset", "no_refractory", "uniform_tick",
        "conditional_boundary"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_selection(plan, fits, terminals, identity):
    path = HERE.parent / "mechanism_contract.py"
    tree = ast.parse(path.read_text())
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"canonical", "digest", "select_group"}]
    namespace = dict(json=json, hashlib=hashlib, math=math)
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace["select_group"](plan, fits, terminals, identity)


class KaggleExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cpu-execution-control-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.control = self.source / owner.CONTROL_RELATIVE
        pins = {}
        for name in sorted(owner.CONTROL_FILES):
            path = self.write(self.control / name, (HERE / name).read_bytes())
            pins[owner.CONTROL_RELATIVE + "/" + name] = sha(path)
        controls = {name: pins[owner.CONTROL_RELATIVE + "/" + name] for name in owner.CONTROL_FILES}
        roster = []
        for gi in range(8):
            for arm in reversed(ARMS):  # Deliberately different from plan arm order.
                for li, lr in enumerate((.001, .003)):
                    index = len(roster)
                    roster.append(dict(index=index, fit_id=f"fit-{index:03d}",
                        group_id=f"fixture-group-{gi}", task=("delayed_recall", "adding")[gi // 4],
                        training_seed=(1103, 2207, 3301, 4409)[gi % 4],
                        arm=arm, lr_index=li, learning_rate=lr))
        groups = [dict(group_id=f"fixture-group-{gi}", fit_ids=[r["fit_id"] for r in roster
                  if r["group_id"] == f"fixture-group-{gi}"]) for gi in range(8)]
        environment = dict(python="3.13.18", numpy="2.1.3", torch="2.11.0+cpu",
            cuda_build=None, device="cpu", cpu_threads=1, deterministic_algorithms=True,
            gpu_uuid_policy="not_applicable")
        provider = dict(account_selector="fixture_account", expected_username="fixtureowner",
            expected_user_id=424242, accelerator="cpu", timeout_seconds=3000,
            internet=False, is_private=True, mode="batch", artifact_root=str(self.root / "artifacts"),
            native_python=sys.executable, entrypoint=str(self.root / "not-an-executable"), installed_sources={})
        qualified = dict(notebook_ref="fixtureowner/qualified-never-submitted", notebook_version=1,
            kernel_id=123, input_digest="1" * 64, archive_name="suite-artifacts.zip",
            archive_sha256="2" * 64, archive_bytes=123,
            bundle_member="inputs/prior-qualified-bundle/operators-s81.npz",
            metadata_member="inputs/prior-qualified-bundle/operators-s81.json")
        policy = {k: provider[k] for k in ("account_selector", "expected_username", "expected_user_id",
            "accelerator", "internet", "is_private", "mode", "timeout_seconds")}
        self.plan = dict(fixture_only=True, status="FROZEN", study_id=owner.STUDY_ID,
            train_updates=400, max_fit_wall_seconds=480, state_count=81,
            expected_parameter_count=2890, source_pins=pins, arms=ARMS,
            learning_rates=[.001, .003], validation_count=512, test_episode_seeds=[4703, 5801],
            bundle_sha256="a" * 64, bundle_metadata_sha256="b" * 64,
            ordered_fit_roster_sha256=hashlib.sha256(owner.canonical(roster)[:-1]).hexdigest(),
            execution_environment=environment,
            runtime_feasibility_policy=dict(provider="kaggle", cloud_job_max_seconds=3000,
                minimum_remaining_before_operation_seconds=720),
            resource_migration=dict(cpu_provider_commitment=hashlib.sha256(owner.canonical(policy)[:-1]).hexdigest(),
                qualified_input_commitment=hashlib.sha256(owner.canonical(qualified)[:-1]).hexdigest()))
        self.plan_path = self.write(self.source / "plan-fixture.json", self.plan)
        plan_sha = sha(self.plan_path)
        identity = dict(study_id=self.plan["study_id"], plan_sha256=plan_sha,
            bundle_sha256=self.plan["bundle_sha256"], bundle_metadata_sha256=self.plan["bundle_metadata_sha256"],
            source_pins=pins, ordered_fit_roster_sha256=self.plan["ordered_fit_roster_sha256"],
            state_count=81, expected_parameter_count=2890, registered_fit_count=160,
            registered_training_updates=64000, original_campaign_completion_credit=0)
        self.config = dict(schema="hcsn-kaggle-cpu-study-owner-config-v1", formal_training_start_authorized=True,
            published_plan_commit="c" * 40, published_plan_ref=owner.REF,
            state_root=str(self.root / "native" / plan_sha), plan_relative_path="plan-fixture.json",
            plan_sha256=plan_sha, source_pins=pins, control_pins=controls, ordered_roster=roster,
            groups=groups, identity=identity, runtime_policy=self.plan["runtime_feasibility_policy"],
            execution_environment=environment, provider=provider, qualified_input=qualified)
        receipt = self.write(self.root / "publication-fixture.json", dict(fixture_only=True,
            status="published_and_verified", repo="TrillionniumFoundation/hepta-private-ci",
            branch=owner.REF.removeprefix("refs/heads/"), commit=self.config["published_plan_commit"]))
        files = {name: dict(sha256=value) for name, value in pins.items()}
        files["plan-fixture.json"] = dict(sha256=plan_sha)
        readback = self.write(self.root / "readback-fixture.json", dict(fixture_only=True,
            commit=self.config["published_plan_commit"], files=files))
        self.config["publication_receipt"] = dict(receipt_path=str(receipt), receipt_sha256=sha(receipt),
            readback_path=str(readback), readback_sha256=sha(readback))
        self.group = groups[0]
        self.ledgers = []
        self.addCleanup(lambda: [x.lock.close() for x in self.ledgers if not x.lock.closed])

    def write(self, path, value):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else owner.canonical(value))
        return path

    def study(self, name="study"):
        study = self.root / name; study.mkdir()
        self.write(study / "study.json", dict(created_at="fixture", identity=self.config["identity"],
            plan=self.plan, ordered_fit_roster=self.config["ordered_roster"],
            owner_rule="CONTROL_FIXTURE_ONLY_ZERO_TRAINING"))
        return study

    def fit(self, study, fit_id, status="COMPLETED"):
        fit = next(r for r in self.config["ordered_roster"] if r["fit_id"] == fit_id)
        path = study / "attempts" / fit_id; path.mkdir(parents=True)
        checkpoint = self.write(path / "checkpoint.pt", ("NOT_TORCH_WEIGHTS_" + fit_id).encode())
        terminal = dict(fixture_only=True, identity=self.config["identity"], fit=fit, phase="fit", status=status,
            optimizer_updates_completed=400 if status == "COMPLETED" else 7,
            training_examples_completed=25600 if status == "COMPLETED" else 448,
            validation=dict(count=512, mse=.4 + fit["index"] / 1000), checkpoint_sha256=sha(checkpoint),
            environment=self.config["execution_environment"], frozen_environment_check=dict(matched=True),
            source_and_input_pins_unchanged_at_completion=True)
        if status == "FAILED": terminal["error"] = dict(type="FloatingPointError", message="Nonfinite training loss")
        self.write(path / "started.json", dict(fixture_only=True, identity=self.config["identity"], fit=fit))
        self.write(path / "terminal.json", terminal)
        self.write(path / "process-completion.json", dict(fixture_only=True,
            returncode=0 if status == "COMPLETED" else 2, timed_out=status == "TIMEOUT"))
        return terminal

    def selection(self, study):
        fits = self.config["ordered_roster"][:20]
        terminals = {r["fit_id"]: owner.read(study / "attempts" / r["fit_id"] / "terminal.json") for r in fits}
        lock = frozen_selection(self.plan, fits, terminals, self.config["identity"])
        lock["created_at"] = "fixture-before-any-test"
        for field, name in (("fit_terminal_file_sha256", "terminal.json"),
                            ("fit_process_completion_file_sha256", "process-completion.json")):
            lock[field] = {r["fit_id"]: sha(study / "attempts" / r["fit_id"] / name) for r in fits}
        path = self.write(study / "blocks" / self.group["group_id"] / "selection-lock.json", lock)
        self.write(path.with_name("selection-receipt.json"), dict(identity=self.config["identity"],
            group_id=self.group["group_id"], phase="selection", selection_lock_sha256=sha(path),
            selected_fit_ids=[r["fit_id"] for r in lock["selected"].values()],
            all_registered_arms_selected=lock["all_registered_arms_selected"],
            strongest_full_registered_set_eligible=lock["strongest_full_registered_set_eligible"]))
        return lock, sha(path)

    def remote(self, active, state="COMPLETE", verified=True):
        return dict(schema="hepta-kaggle-job-v1", request_id=active["request_id"], identity_verified=verified,
            account=dict(username="fixtureowner", authenticated=True, user_id=424242), remote_effect_unknown=False,
            notebook_ref="fixtureowner/fixture-one", notebook_version=1, kernel_id=321, input_digest="f" * 64,
            remote_submission_state="ACKNOWLEDGED", submission_state="ACCEPTED",
            remote_state=state, remote_submission_replayed=False,
            intent=dict(source_sha256=active["code_sha256"], timeout_seconds=3000, accelerator="cpu",
                is_private=True, internet=False, kernel_sources=active["kernel_sources"]))

    def ledger(self, reserve=True, bind=True):
        ledger = owner.Ledger(self.root / ("ledger-" + str(len(self.ledgers))), self.config)
        self.ledgers.append(ledger)
        if not reserve: return ledger, None
        state = ledger.copy()
        active = dict(request_id="fixture-one", group_id=self.group["group_id"], phase="fit",
            planned_fit_ids=self.group["fit_ids"], planned_evaluation_ids=[],
            ever_claimed_fit_ids=[], ever_claimed_evaluation_ids=[], identity=self.config["identity"],
            source_pins=self.config["source_pins"], control_pins=self.config["control_pins"],
            plan_sha256=self.config["plan_sha256"], published_plan_commit=self.config["published_plan_commit"],
            published_plan_ref=owner.REF, qualified_input=self.config["qualified_input"], prior_capsule=None,
            artifact_root=self.config["provider"]["artifact_root"], code_sha256="1" * 64,
            kernel_sources=[self.config["qualified_input"]["notebook_ref"]], reserved_unix=time.time(),
            producer=None, terminal_observation=None)
        remote = self.remote(active)
        if bind:
            active["producer"] = owner.validate_remote(remote, active, self.config)
            active["terminal_observation"] = remote
        state["active"], state["batch_count"] = active, 1
        for fit_id in active["planned_fit_ids"]:
            state["fits"][fit_id] = dict(state="RESERVED", ever_claimed=False, request_id=active["request_id"])
        ledger.append("RESERVED_BEFORE_SUBMISSION", state)
        return ledger, remote

    def instance(self, ledger, builder=None, adapter=None):
        return owner.Owner(self.config, self.plan, self.source, self.control, ledger, builder, adapter or object())

    def artifacts(self, study, ledger, remote, status="EXPORTED"):
        active = ledger.state["active"]
        output = Path(active["artifact_root"]) / active["request_id"] / "artifacts/v1"
        output.mkdir(parents=True)
        manifest = capsule.create_capsule(study, output / "study-capsule.tar.gz", output / "capsule-manifest.json",
            self.config["identity"], self.group["group_id"], self.group["fit_ids"])
        cap = dict(archive_name="study-capsule.tar.gz", manifest_name="capsule-manifest.json",
            archive_sha256=manifest["archive"]["sha256"], archive_bytes=manifest["archive"]["bytes"],
            manifest_sha256=sha(output / "capsule-manifest.json"))
        report = {k: active[k] for k in ("request_id", "group_id", "phase", "identity", "source_pins", "control_pins",
            "plan_sha256", "published_plan_commit", "published_plan_ref", "planned_fit_ids", "planned_evaluation_ids",
            "qualified_input", "prior_capsule")}
        report.update(schema="hcsn-mechanism-provider-batch-v1", status=status, capsule=cap,
            source_unchanged=True, environment_verified=True, worker_children_stopped=True,
            final_state_attested=status == "EXPORTED", capsule_verified=True, halt_owner=status != "EXPORTED",
            observed_environment=dict(environment=self.config["execution_environment"], check=dict(matched=True)),
            unclaimed_remaining_planned_fit_ids=[i for i in active["planned_fit_ids"] if i not in manifest["claimed_fit_ids"]],
            unclaimed_remaining_planned_evaluation_ids=[], costs=dict(full_physical_energy_joules=None,
                monetary_cost=None, scope="SYNTHETIC_CONTROL_FIXTURE_NOT_PROVIDER_MEASUREMENT"))
        self.write(output / "execution.json", report)
        files = [dict(path=p.name, bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(output.iterdir())]
        manifest_path = self.write(output / "artifact-manifest.json", dict(schema="hepta-artifact-manifest-v1",
            request_id=active["request_id"], files=files))
        files.append(dict(path=manifest_path.name, bytes=manifest_path.stat().st_size, sha256=sha(manifest_path)))
        for row in files: row["http_content_length_verified"] = True
        result = {k: remote[k] for k in ("request_id", "notebook_ref", "notebook_version", "input_digest")}
        result.update(remote_manifest_verified=True, remote_manifest_name="artifact-manifest.json",
            verification_policy="manifest-and-http-v1", directory=str(output), files=files)
        return result

    def test_config_full160_binding_and_private_provider_commitments(self):
        no_installed_calls = types.SimpleNamespace(validate_installed=lambda _: None)
        with patch.object(owner, "load_control", return_value=no_installed_calls):
            result = owner.validate_config(self.config, self.source, self.plan_path, self.control,
                self.config["published_plan_commit"], owner.REF)
            self.assertEqual(result["train_updates"], 400)
            for key, value in (("expected_username", "different"), ("accelerator", "NvidiaTeslaT4")):
                changed = copy.deepcopy(self.config); changed["provider"][key] = value
                with self.subTest(key=key), self.assertRaises(owner.OwnerHalt):
                    owner.validate_config(changed, self.source, self.plan_path, self.control,
                        self.config["published_plan_commit"], owner.REF)
            changed = copy.deepcopy(self.config); changed["identity"]["registered_fit_count"] = 20
            with self.assertRaisesRegex(owner.OwnerHalt, "research identity"):
                owner.validate_config(changed, self.source, self.plan_path, self.control,
                    self.config["published_plan_commit"], owner.REF)

    def test_group_reservation_preserves_full160_and_single_owner(self):
        ledger, _ = self.ledger()
        report = self.instance(ledger).summary()
        self.assertEqual(report["fit_counts"], {"RESERVED": 20, "UNSTARTED": 140})
        self.assertEqual(report["registered_fit_count"], 160)
        self.assertEqual(report["registered_optimizer_updates"], 64000)
        self.assertEqual(report["ever_claimed_fit_count"], 0)
        with self.assertRaises((BlockingIOError, OSError)):
            owner.Ledger(ledger.root, self.config)

    def test_reservation_release_needs_all_three_actual_proofs(self):
        ledger, _ = self.ledger()
        state = ledger.copy(); state["fits"]["fit-000"] = dict(state="UNSTARTED", ever_claimed=False)
        proof = dict(provider_terminal_verified=True, full_capsule_verified=True, final_state_attested=True)
        for missing in proof:
            bad = dict(proof); bad[missing] = False
            with self.subTest(missing=missing), self.assertRaises(owner.OwnerHalt):
                ledger.append("CAPSULE_ACCEPTED", state, bad)
        ledger.append("CAPSULE_ACCEPTED", state, proof)
        self.assertEqual(ledger.state["fits"]["fit-000"]["state"], "UNSTARTED")

    def test_unknown_claim_cannot_be_erased_replayed_or_removed_from_group(self):
        ledger, _ = self.ledger()
        state = ledger.copy(); state["fits"]["fit-000"] = dict(state="UNKNOWN", ever_claimed=True)
        state["groups"][self.group["group_id"]]["ever_claimed_fit_ids"] = ["fit-000"]
        ledger.append("CLAIMS_OBSERVED", state)
        for replacement in (dict(state="UNSTARTED", ever_claimed=False), dict(state="COMPLETED", ever_claimed=True)):
            changed = ledger.copy(); changed["fits"]["fit-000"] = replacement
            with self.assertRaises(owner.OwnerHalt): ledger.append("CAPSULE_ACCEPTED", changed)
        changed = ledger.copy(); changed["groups"][self.group["group_id"]]["ever_claimed_fit_ids"] = []
        with self.assertRaises(owner.OwnerHalt): ledger.append("CAPSULE_ACCEPTED", changed)

    def test_full_capsule_acceptance_counts_one_fit_not_twenty_or160(self):
        study = self.study(); self.fit(study, "fit-000")
        ledger, remote = self.ledger(); artifacts = self.artifacts(study, ledger, remote)
        instance = self.instance(ledger); instance.accept(remote, artifacts)
        report = instance.summary()
        self.assertEqual(report["fit_counts"], {"COMPLETED": 1, "UNSTARTED": 159})
        self.assertEqual(report["known_optimizer_updates_lower_bound"], 400)
        self.assertIsNone(report["full_physical_energy_joules"])
        self.assertEqual(report["original_campaign_completion_credit"], 0)
        self.assertEqual(report["scientific_admission"], "HOLD")
        self.assertIsNone(ledger.state["active"])

    def test_provider_complete_without_full_capsule_releases_no_reservation(self):
        study = self.study(); self.fit(study, "fit-000")
        ledger, remote = self.ledger(); artifacts = self.artifacts(study, ledger, remote)
        artifacts["files"] = [row for row in artifacts["files"] if row["path"] != "study-capsule.tar.gz"]
        with self.assertRaisesRegex(owner.OwnerHalt, "capsule artifacts"):
            self.instance(ledger).accept(remote, artifacts)
        self.assertEqual(self.instance(ledger).summary()["fit_counts"], {"RESERVED": 20, "UNSTARTED": 140})

    def test_blocked_export_retains_claim_before_halting_and_never_releases_rest(self):
        study = self.study(); self.fit(study, "fit-000", "FAILED")
        ledger, remote = self.ledger(); artifacts = self.artifacts(study, ledger, remote, "BLOCKED")
        with self.assertRaisesRegex(owner.OwnerHalt, "accepted bounded batch"):
            self.instance(ledger).accept(remote, artifacts)
        self.assertEqual(ledger.state["fits"]["fit-000"]["state"], "FAILED")
        self.assertTrue(ledger.state["fits"]["fit-000"]["ever_claimed"])
        self.assertEqual(ledger.state["fits"]["fit-001"]["state"], "RESERVED")
        self.assertIsNotNone(ledger.state["active"])

    def test_cpu_environment_and_authoritative_producer_differences_halt(self):
        ledger, remote = self.ledger()
        for key, value in (("device", "cuda"), ("cpu_threads", 2), ("torch", "2.11.0+cu130")):
            environment = dict(self.config["execution_environment"], **{key: value})
            with self.subTest(key=key), self.assertRaises(owner.OwnerHalt):
                owner.check_environment(self.config["execution_environment"], environment)
        for key, value in (("kernel_id", 322), ("notebook_version", 2), ("input_digest", "0" * 64),
                           ("identity_verified", False), ("remote_effect_unknown", True)):
            changed = copy.deepcopy(remote); changed[key] = value
            with self.subTest(key=key), self.assertRaises(owner.OwnerHalt):
                owner.validate_remote(changed, ledger.state["active"], self.config)
        for key, value in (("accelerator", "NvidiaTeslaT4"), ("source_sha256", "0" * 64)):
            changed = copy.deepcopy(remote); changed["intent"][key] = value
            with self.subTest(key=key), self.assertRaises(owner.OwnerHalt):
                owner.validate_remote(changed, ledger.state["active"], self.config)

    def test_initial_unobserved_ack_then_same_request_resume_without_replay(self):
        # Actual ACK/resume field shapes are from 0c6c1394... / 2a71841f...;
        # identities below remain local synthetic fixtures, not remote receipts.
        for resolved in (True, False):
            ledger, _ = self.ledger(reserve=False)
            calls = []
            def build(batch, *_):
                raw = "# never submitted; local fixture only\n"
                return dict(request_id=batch["request_id"], source_text=raw, code_bytes=len(raw.encode()),
                    code_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                    kernel_sources=[self.config["qualified_input"]["notebook_ref"]])
            def call(operation, args, timeout=150):
                calls.append((operation, list(args)))
                active = ledger.state["active"]
                if operation == "submit":
                    return self.remote(active, "UNKNOWN", verified=False)
                if operation == "resume":
                    return self.remote(active, "RUNNING" if resolved else "UNKNOWN", verified=resolved)
                raise owner.OwnerHalt("Explicit fixture observation stop; no provider exists")
            adapter = types.SimpleNamespace(call=call)
            with self.assertRaises(owner.OwnerHalt):
                self.instance(ledger, build, adapter).run()
            self.assertEqual([op for op, _ in calls], ["submit", "resume", "wait"] if resolved else ["submit", "resume"])
            request = ledger.state["active"]["request_id"]
            self.assertTrue(all(args[args.index("--request-id") + 1] == request for _, args in calls))
            self.assertEqual(ledger.state["batch_count"], 1)
            self.assertEqual(self.instance(ledger).summary()["ever_claimed_fit_count"], 0)
            self.assertIsNotNone(ledger.state["halted"])
            self.assertEqual(ledger.state["active"]["producer"] is not None, resolved)

    def test_complete20_selection_matches_original_and_retains_losing_lr_weights(self):
        study = self.study()
        for fit_id in self.group["fit_ids"]: self.fit(study, fit_id)
        lock, expected_sha = self.selection(study)
        selected, lock_sha = owner.verify_selection(study, self.group, self.plan, self.config)
        self.assertEqual(lock_sha, expected_sha)
        self.assertEqual(selected, [f"fit-{i:03d}" for i in range(0, 20, 2)])
        self.assertTrue(lock["strongest_full_registered_set_eligible"])
        self.assertEqual(len(list((study / "attempts").glob("*/checkpoint.pt"))), 20)
        (study / "attempts/fit-019/process-completion.json").unlink()
        with self.assertRaises((FileNotFoundError, owner.OwnerHalt)):
            owner.verify_selection(study, self.group, self.plan, self.config)

    def test_failed_lr_pair_keeps_failure_and_disables_strongest_full_set(self):
        study = self.study()
        for index, fit_id in enumerate(self.group["fit_ids"]):
            self.fit(study, fit_id, "FAILED" if index == 1 else "COMPLETED")
        lock, _ = self.selection(study)
        selected, _ = owner.verify_selection(study, self.group, self.plan, self.config)
        self.assertEqual(len(selected), 9)
        self.assertFalse(lock["strongest_full_registered_set_eligible"])
        self.assertIsNone(lock["strongest_registered_comparator"])
        self.assertEqual(owner.read(study / "attempts/fit-001/terminal.json")["status"], "FAILED")

    def test_selection_lock_cannot_change_comparator_even_with_new_receipt_hash(self):
        study = self.study()
        for fit_id in self.group["fit_ids"]: self.fit(study, fit_id)
        lock, _ = self.selection(study)
        lock["strongest_registered_comparator"] = "regenerative_dual"
        path = self.write(study / "blocks" / self.group["group_id"] / "selection-lock.json", lock)
        receipt_path = path.with_name("selection-receipt.json")
        receipt = owner.read(receipt_path); receipt["selection_lock_sha256"] = sha(path)
        self.write(receipt_path, receipt)
        with self.assertRaisesRegex(owner.OwnerHalt, "validation evidence"):
            owner.verify_selection(study, self.group, self.plan, self.config)

    def test_phase_barriers_and_exact_evaluation_lock_before_dispatch(self):
        study = self.study(); fits = self.config["ordered_roster"][:20]
        known = {r["fit_id"]: dict(status="UNSTARTED") for r in fits}
        dispatch = dict(phase="fit", group_id=self.group["group_id"],
            planned_fit_ids=self.group["fit_ids"], planned_evaluation_ids=[])
        known["fit-000"]["status"] = "UNKNOWN"
        with self.assertRaisesRegex(cloud.OwnerHalt, "UNKNOWN"):
            cloud.phase_dispatch(dispatch, fits, known, study, self.plan, self.config["identity"], None)
        known["fit-000"]["status"] = "UNSTARTED"; dispatch["phase"] = "selection"
        with self.assertRaisesRegex(cloud.OwnerHalt, "twenty"):
            cloud.phase_dispatch(dispatch, fits, known, study, self.plan, self.config["identity"], None)
        for fit in fits: self.fit(study, fit["fit_id"]); known[fit["fit_id"]]["status"] = "COMPLETED"
        lock, lock_sha = self.selection(study)
        ids = [r["fit_id"] for r in fits if r["fit_id"] in {v["fit_id"] for v in lock["selected"].values()}]
        dispatch.update(phase="evaluation", planned_fit_ids=[], planned_evaluation_ids=ids,
                        verified_selection_lock_sha256=lock_sha)
        validate = lambda *_: (lock, lock_sha)
        self.assertEqual(cloud.phase_dispatch(dispatch, fits, known, study, self.plan,
            self.config["identity"], validate), ids)
        dispatch["verified_selection_lock_sha256"] = "different"
        with self.assertRaisesRegex(cloud.OwnerHalt, "native readback"):
            cloud.phase_dispatch(dispatch, fits, known, study, self.plan, self.config["identity"], validate)

    def test_capsule_transition_cannot_drop_loser_or_modify_old_bytes(self):
        study = self.study(); self.fit(study, "fit-000"); self.fit(study, "fit-001")
        prior = capsule.create_capsule(study, self.root / "old.tar.gz", self.root / "old.json",
            self.config["identity"], self.group["group_id"], self.group["fit_ids"])
        (study / "attempts/fit-001/checkpoint.pt").unlink()
        with self.assertRaises(capsule.CapsuleError):
            capsule.create_capsule(study, self.root / "lost.tar.gz", self.root / "lost.json",
                self.config["identity"], self.group["group_id"], self.group["fit_ids"], prior)
        self.write(study / "attempts/fit-001/checkpoint.pt", b"different-losing-checkpoint")
        with self.assertRaises(capsule.CapsuleError):
            capsule.create_capsule(study, self.root / "changed.tar.gz", self.root / "changed.json",
                self.config["identity"], self.group["group_id"], self.group["fit_ids"], prior)

    def test_exact_fixed_budget_and_stopped_worker_required(self):
        study = self.study(); terminal = self.fit(study, "fit-000")
        path = study / "attempts/fit-000"; fit = self.config["ordered_roster"][0]
        terminal["optimizer_updates_completed"] = 399; self.write(path / "terminal.json", terminal)
        with self.assertRaises(cloud.OwnerHalt): cloud.guard_terminal(path, fit, self.config["identity"], "fit")
        terminal["optimizer_updates_completed"] = 400; self.write(path / "terminal.json", terminal)
        (path / "process-completion.json").unlink()
        with self.assertRaisesRegex(cloud.OwnerHalt, "UNKNOWN"):
            cloud.guard_terminal(path, fit, self.config["identity"], "fit")

    def test_cpu_finalizer_partial_observation_needs_no_colab_continuation_field(self):
        # Exercise the actual CLI through its first partial/HOLD receipt. Only
        # native launch and native process observations are explicit fixtures.
        # CPU config/source/publication checks and output files are real IO.
        bundle = self.write(self.root / "operators-fixture.npz", b"NONNUMERICAL_FIXTURE")
        metadata = self.write(bundle.with_suffix(".json"), b'{"fixture_only":true}')
        self.plan.update(bundle_sha256=sha(bundle), bundle_metadata_sha256=sha(metadata))
        self.write(self.plan_path, self.plan)
        self.config["plan_sha256"] = sha(self.plan_path)
        self.config["state_root"] = str(self.root / "native" / self.config["plan_sha256"])
        self.config["identity"].update(plan_sha256=self.config["plan_sha256"],
            bundle_sha256=sha(bundle), bundle_metadata_sha256=sha(metadata))
        proof = self.config["publication_receipt"]
        readback = owner.read(proof["readback_path"])
        readback["files"]["plan-fixture.json"]["sha256"] = self.config["plan_sha256"]
        self.write(proof["readback_path"], readback); proof["readback_sha256"] = sha(proof["readback_path"])
        config_path = self.write(self.root / "cpu-config.json", self.config)
        output = self.root / "cpu-analysis"
        now = datetime.now(timezone.utc)
        binding = dict(schema="hcsn-s81-kaggle-cpu-analysis-owner-binding-v1",
            plan_sha256=self.config["plan_sha256"], continuation_source_sha256=sha(finalizer.__file__),
            output=str(output), binding_created_at_utc=now.isoformat(),
            observer_deadline_utc=(now + timedelta(seconds=60)).isoformat(),
            config_path=str(config_path), config_sha256=sha(config_path),
            control_pins=self.config["control_pins"], source_root=str(self.source), control_root=str(self.control),
            native_host="fixture-host-not-contacted", native_job_root=str(self.root / "native-jobs"),
            owner=dict(job_id="fixture-job", job_directory=str(self.root / "native-jobs/fixture-job")),
            bundle=str(bundle))
        path = self.write(self.root / "analysis-binding.json", binding)
        self.assertNotIn("continuation_lineage", self.config)
        no_installed_calls = types.SimpleNamespace(validate_installed=lambda _: None)
        with patch.object(finalizer, "dependencies", return_value=(owner, capsule)), \
             patch.object(owner, "load_control", return_value=no_installed_calls), \
             patch.object(finalizer, "verify_launch_role", return_value={"fixture_only": True}), \
             patch.object(finalizer, "owner_observation", return_value={"state": "UNVERIFIED"}), \
             contextlib.redirect_stdout(io.StringIO()):
            result = finalizer.main(["--binding", str(path), "--binding-sha256", sha(path), "--output", str(output)])
        self.assertEqual(result, 2)
        receipt = owner.read(output / "continuation-terminal.json")
        self.assertEqual(receipt["status"], "OBSERVATION_ONLY_PARTIAL_HOLD")
        self.assertFalse(receipt["analysis_started"])
        self.assertEqual(receipt["progress"]["fit_counts"], {"UNSTARTED": 160})
        self.assertEqual(receipt["provider_submissions"], 0)
        self.assertIsNone(receipt["full_physical_energy_joules"])

    def test_cpu_windows_exact720_restore_full_snapshot_and_export_blocked_claim(self):
        source = self.root / "cloud-source"; controls = self.root / "cloud-controls"
        science = self.write(source / "fixture.py", b"# not scientific execution\n")
        pins = {"fixture.py": sha(science)}
        control_pins = {name: sha(self.write(controls / name, (HERE / name).read_bytes())) for name in cloud.CONTROL_FILES}
        roster = self.config["ordered_roster"]; group = roster[:20]
        operator, metadata = b"EXPLICIT_FIXTURE_NOT_NPZ", b'{"fixture_only":true}'
        plan = dict(source_pins=pins, runtime_feasibility_policy=dict(cloud_job_max_seconds=3000,
            minimum_remaining_before_operation_seconds=720), max_fit_wall_seconds=480)
        plan_path = self.write(source / "plan.json", plan)
        identity = dict(study_id="CONTROL_ONLY_NO_SCIENTIFIC_EXECUTION", source_pins=pins,
            plan_sha256=sha(plan_path), registered_fit_count=160,
            ordered_fit_roster_sha256=hashlib.sha256(cloud.canonical(roster)).hexdigest(),
            bundle_sha256=hashlib.sha256(operator).hexdigest(), bundle_metadata_sha256=hashlib.sha256(metadata).hexdigest())
        archive_path = self.root / "qualified-fixture.zip"
        with zipfile.ZipFile(archive_path, "x") as archive:
            archive.writestr("inputs/operators.npz", operator); archive.writestr("inputs/operators.json", metadata)
        config = dict(formal_training_start_authorized=True, published_plan_commit="c" * 40,
            published_plan_ref=cloud.PUBLISHED_REF, request_id="control-fixture-never-submitted", phase="fit",
            group_id=self.group["group_id"], planned_fit_ids=self.group["fit_ids"], planned_evaluation_ids=[],
            expected_group_fit_ids=self.group["fit_ids"], source_pins=pins, control_pins=control_pins,
            source_root=str(source), control_root=str(controls), plan_relative_path="plan.json", plan_sha256=sha(plan_path),
            identity=identity, admission_epoch_unix=time.time(), ever_claimed_fit_ids=[],
            ever_claimed_evaluation_ids=[], prior_capsule=None,
            qualified_input=dict(notebook_ref="fixture/qualified", archive_name="suite-artifacts.zip",
                archive_sha256=sha(archive_path), archive_bytes=archive_path.stat().st_size,
                bundle_member="inputs/operators.npz", metadata_member="inputs/operators.json"))
        def read_attempt(study, fit, ident):
            path = study / "attempts" / fit["fit_id"]
            if not path.exists(): return dict(status="UNSTARTED")
            return cloud.read_json(path / "terminal.json") if (path / "terminal.json").exists() else dict(status="UNKNOWN")
        contract = types.ModuleType("qualification.hcsn_regenerative.mechanism_contract")
        contract.load_contract = lambda *_: (plan, {}, {}, roster, identity)
        training = types.ModuleType("qualification.hcsn_regenerative.mechanism_training")
        training.read_attempt = read_attempt
        training.validate_selection_lock = lambda *_: self.fail("Fit window must not evaluate test selection")
        mode = {"blocked": False}; observed = {}; executions = []
        def process(argv, cwd, env, logs, label, timeout, attempt=None):
            self.assertEqual(env["OMP_NUM_THREADS"], "1")
            if label == "environment-preflight":
                self.assertIn("configure_torch('cpu')", argv[3]); self.assertNotIn("set_device", argv[3])
                self.write(Path(argv[-1]), dict(environment=dict(device="cpu", cpu_threads=1), check=dict(matched=True)))
                rc = 0
            else:
                self.assertEqual(argv[argv.index("--device") + 1], "cpu")
                self.assertEqual(timeout, 520); executions.append(argv[-1])
                fit = next(row for row in group if row["fit_id"] == argv[-1]); attempt.mkdir(parents=True)
                checkpoint = self.write(attempt / "checkpoint.pt", b"NOT_MODEL_WEIGHTS_" + argv[-1].encode())
                terminal = dict(identity=identity, fit=fit, phase="fit", status="COMPLETED", optimizer_updates_completed=400,
                    validation=dict(mse=.2), checkpoint_sha256=sha(checkpoint), frozen_environment_check=dict(matched=True),
                    source_and_input_pins_unchanged_at_completion=True, fixture_only=True)
                rc = 2 if mode["blocked"] else 0
                if mode["blocked"]: terminal.update(status="FAILED", error=dict(type="ValueError", message="Execution environment mismatch"))
                self.write(attempt / "started.json", dict(identity=identity, fit=fit, fixture_only=True))
                self.write(attempt / "terminal.json", terminal)
                self.write(attempt / "process-completion.json", dict(returncode=rc, timed_out=False, fixture_only=True))
            return dict(returncode=rc, timed_out=False, worker_children_stopped=True, fixture_only=True)
        def mounted(producer, name, expected, expected_bytes=None):
            path = archive_path if producer == "fixture/qualified" else observed[name]
            self.assertEqual(sha(path), expected)
            if expected_bytes is not None: self.assertEqual(path.stat().st_size, expected_bytes)
            return path
        modules = {contract.__name__: contract, training.__name__: training}
        self.assertEqual(cloud.OPERATION_WAIT_SECONDS + cloud.OPERATION_DRAIN_SECONDS + cloud.EXPORT_RESERVE_SECONDS, 720)
        self.assertEqual(cloud.remaining_budget(1000, 20, 100, 2200), 720)
        with patch.dict(sys.modules, modules), patch.object(cloud, "input_file", side_effect=mounted), \
             patch.object(cloud, "run_process", side_effect=process), contextlib.redirect_stdout(io.StringIO()):
            for window, claimed in ((1, 2), (2, 3), (3, 4)):
                work = self.root / f"work-{window}"; work.mkdir()
                temp = self.root / f"cloud-temp-{window}"; temp.mkdir(); config["temporary_root"] = str(temp)
                mode["blocked"] = window == 3
                budget = [720., 720., 719.999] if window == 1 else [720., 719.999]
                with patch.object(cloud, "remaining_budget", side_effect=budget):
                    self.assertEqual(cloud.run_batch(config, work_root=work), 0)
                result = cloud.read_json(work / "execution.json")
                manifest = cloud.read_json(work / "capsule-manifest.json")
                self.assertEqual(manifest["claimed_fit_ids"], [f"fit-{i:03d}" for i in range(claimed)])
                self.assertIn("attempts/fit-000/checkpoint.pt", manifest["files"])
                self.assertIsNone(result["costs"]["full_physical_energy_joules"])
                if window == 3:
                    self.assertEqual(result["status"], "BLOCKED")
                    self.assertTrue(result["halt_owner"]); self.assertFalse(result["final_state_attested"])
                    self.assertNotIn("unclaimed_remaining_planned_fit_ids", result)
                else:
                    self.assertEqual(result["status"], "EXPORTED"); self.assertTrue(result["final_state_attested"])
                    observed = {name: work / name for name in ("study-capsule.tar.gz", "capsule-manifest.json")}
                    config["prior_capsule"] = dict(producer_ref="fixture/previous", archive_sha256=manifest["archive"]["sha256"],
                        archive_bytes=manifest["archive"]["bytes"], manifest_sha256=sha(work / "capsule-manifest.json"))
                    config["ever_claimed_fit_ids"] = manifest["claimed_fit_ids"]
                    config["planned_fit_ids"] = result["unclaimed_remaining_planned_fit_ids"]
        self.assertEqual(executions, ["fit-000", "fit-001", "fit-002", "fit-003"])


if __name__ == "__main__":
    unittest.main()
