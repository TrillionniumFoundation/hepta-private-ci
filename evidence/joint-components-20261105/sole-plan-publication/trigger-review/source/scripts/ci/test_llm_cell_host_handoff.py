#!/usr/bin/env python3
"""Real native Cell transport and exec-contract controls; no model qualification.

Set TRNM_CELL_BIN to the freshly built trnm-cell. The ELF echo probe observes
only argv/FD transfer, never Hepta model admission, FinalUse or installation.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import llm_cell_host_handoff as handoff

NATIVE = os.environ.get("TRNM_CELL_BIN")
CAPS = ["--cache-max-bytes", "67108864", "--cache-max-chunks", "4096",
        "--cache-max-manifests", "256", "--cache-max-db-bytes", "134217728"]


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)
    return {"path": str(path), "sha256": handoff.checksum(raw)}


def fixture(root):
    chain, materials, parent_dir = root / "chain", root / "materials", root / "parent"
    public = {}
    for name in handoff.NAMES[3:]:
        if name == "base/material-manifest.json":
            continue
        raw = ("explicit synthetic transport fixture: " + name).encode()
        save(materials / name.removeprefix("base/"), raw)
        public[name.removeprefix("base/")] = {"size": len(raw), "sha256": handoff.checksum(raw)}
    family = {"id": "smollm2-135m-cpu-dev-v1", "reference": {"model": "HuggingFaceTB/SmolLM2-135M-Instruct",
        "revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac"}, "material_pins": {"files": public}}
    for name, relative in handoff.SOURCES.items():
        save(chain / relative, handoff.canonical(family) if name.endswith(".json") else ("# fixture " + name).encode())
    save(materials / "material-manifest.json", handoff.canonical(dict(model=family["reference"]["model"],
        revision=family["reference"]["revision"], files=public)))
    target = save(parent_dir / "target-contract.json", handoff.canonical({"backbone": {"index_root": "11" * 32}, "tokenizer": {"files_root": "22" * 32}}))
    wrapped = save(parent_dir / "wrapped-adapter.json", b'{"scope":"synthetic-not-model"}')
    payload = save(parent_dir / "artifact.safetensors", b"transport-only-not-neural-weights")
    parent = {"directory": str(parent_dir), "generation": 3, "file_sha256": payload["sha256"], "contract": "33" * 32, "adapter": "44" * 32}
    save(parent_dir / "parent.json", handoff.canonical(parent))
    sources = {name: handoff.checksum((chain / relative).read_bytes()) for name, relative in sorted(handoff.SOURCES.items())}
    snapshot = save(root / "runtime-snapshot.json", b"explicit transport-only snapshot fixture; never a model runtime")
    actions = [dict(action_id="native-answer-no", completion="no"), dict(action_id="native-answer-yes", completion="yes")]
    profile = handoff.checksum(handoff.canonical(["hepta-smollm-runtime-bound-execution-v2", "hepta-smollm-single-token-action-score-v1", sources, actions, snapshot["sha256"],
        parent["contract"], parent["adapter"], target["sha256"], wrapped["sha256"], "11" * 32, "22" * 32, 4]))
    context = dict(family=family["id"], base="11" * 32, parent=payload["sha256"], tokenizer="22" * 32,
                   layout=parent["contract"], runtime=sources["llm_neural_read_worker.py"])
    producer = root / "pinned-producer.sqlite"
    members, declared, files = [], [], []
    flags = [value for key in ("family", "base", "parent", "tokenizer", "layout", "runtime") for value in ("--" + key, context[key])]
    for index, name in enumerate(handoff.NAMES):
        source = (parent_dir if name.startswith("adapter/") else materials) / name.split("/", 1)[1]
        result = subprocess.run([NATIVE, "pack", *CAPS, "--store", str(producer), "--input", str(source), *flags], check=True, capture_output=True, text=True)
        packed = json.loads(result.stdout)
        raw = source.read_bytes()
        manifest = b"TCM1" + handoff.codec.context_bytes(context) + len(raw).to_bytes(8, "big") + bytes.fromhex(handoff.checksum(raw))
        manifest += (1024**2).to_bytes(4, "big") + (1).to_bytes(4, "big") + len(raw).to_bytes(4, "big") + bytes.fromhex(handoff.checksum(raw))
        if handoff.checksum(b"trnm.cell-manifest.v1\0" + manifest) != packed["manifest"]:
            raise AssertionError("independent one-chunk wire differs from actual native pack")
        members.append({"name": name, "source": str(source), "pack": packed})
        declared.append(dict(name=name, manifest_id=packed["manifest"], payload_sha256=packed["payload_sha256"], size=packed["bytes"], tcm1_hex=manifest.hex()))
        role = {"adapter/artifact.safetensors": 4, "base/model.safetensors": 1,
                "base/special_tokens_map.json": 2, "base/tokenizer.json": 2, "base/tokenizer_config.json": 2}.get(name, 6)
        files.append(dict(path=name, role=role, manifest=packed["manifest"], payload_sha256=packed["payload_sha256"], payload_bytes=packed["bytes"], dependencies=list(range(1, 11)) if index == 0 else []))
    tcr = handoff.codec.release_bytes(context, [member["manifest_id"] for member in declared])
    release = dict(release=handoff.checksum(b"trnm.cell-release-manifest.v1\0" + tcr), cells=11,
                   payload_bytes=sum(member["size"] for member in declared), chunks=11)
    release_file = root / "prepared.tcr1"
    save(release_file, tcr)
    tcd = handoff.codec.encode(dict(context=context, selected_generation=3, loader_profile=profile, roots=[0], files=files))
    sidecar = dict(schema="hepta-smollm-controlled-cell-release-v1", scope="controlled-native-load-only", profile="smollm2-135m-f32-r4-dense-single-adapter-no-fallback-v1",
        operation_id="original-transport-only-fixture", generation=3, family_id=family["id"], family_file_sha256=sources["model-family-smollm2-135m-v1.json"],
        model=family["reference"]["model"], revision=family["reference"]["revision"], artifact_sha256=payload["sha256"], adapter_digest=parent["adapter"],
        contract_digest=parent["contract"], backbone_digest=context["base"], tokenizer_digest=context["tokenizer"], execution_profile_sha256=profile,
        sources=[dict(name=key, sha256=value) for key, value in sources.items()], actions=actions, tcr1_hex=tcr.hex(), tcr1_id=release["release"], members=declared)
    output = root / "handoff-run"
    descriptor = save(root / "owned-descriptor.json", b'{"scope":"present-for-pin-read-only-not-qualified"}')
    issuer = save(root / "owned-issuer.json", b'{"scope":"not-an-issuer-config"}')
    worker = dict(python=str(Path(sys.executable).resolve()), script=str(chain / handoff.SOURCES["llm_neural_read_worker.py"]), materials=str(output / "consumer-materials"),
        run_directory=str(root / "must-not-claim-a-model-run"), runtime_snapshot=snapshot,
        source_pins={str(chain / relative): sources[name] for name, relative in handoff.SOURCES.items()}, action_completions={row["action_id"]: row["completion"] for row in actions},
        target_contract=dict(path=str(output / "consumer-parent/target-contract.json"), sha256=target["sha256"]),
        wrapped_adapter=dict(path=str(output / "consumer-parent/wrapped-adapter.json"), sha256=wrapped["sha256"]),
        contract_digest=parent["contract"], adapter_digest=parent["adapter"], backbone_digest=context["base"], tokenizer_digest=context["tokenizer"])
    owner = dict(schema="hepta-smollm-cognitive-host-v2", worker=worker, descriptor=descriptor,
        worker_id="explicit-unqualified-probe", resource_grant=dict(grant_id="unissued-fixture",
            authority_epoch=1, generation=1, expires_at_ms=9_999_999_999_999, revoked=False,
            maximum_models=1, maximum_active_requests=1, maximum_memory_bytes=8 * 1024**3, semantic_digest="55" * 32),
        inference_journal=str(root / "not-opened.control"), inference_journal_capacity=8,
        final_use_authorizer_config=issuer["path"])
    host = dict(schema=handoff.HOST_SCHEMA, owner=owner,
        sidecar=dict(path=str(output / "consumer-cell-sidecar.json"), sha256=handoff.checksum(handoff.canonical(sidecar))),
        dependency_closure=dict(path=str(output / "consumer-release.tcd1"), sha256=handoff.checksum(tcd)), dependency_closure_id=handoff.checksum(handoff.codec.DOMAIN + tcd), operation_id=sidecar["operation_id"])
    host_pin = save(root / "owned-host-v2.json", handoff.canonical(host))
    executable = root / "native-argv-probe"
    shutil.copyfile(shutil.which("echo"), executable)
    executable.chmod(0o700)
    value = dict(schema=handoff.SCHEMA, host=host_pin, executable=dict(path=str(executable), sha256=handoff.checksum(executable.read_bytes())), workspace=str(root),
                 generation=3, loader_profile=profile, context=context, authentication={"profile": "content-cache-v1"})
    config_pin = save(root / "owned-handoff-v2.json", handoff.canonical(value))
    args = SimpleNamespace(chain=chain, source_parent=parent_dir / "parent.json", source_materials=materials, output=output,
                           python=Path(worker["python"]), cell_bin=Path(NATIVE),
                           runtime_snapshot=Path(snapshot["path"]), runtime_snapshot_sha256=snapshot["sha256"])
    for name in ("empty-fleet", "agent-home", "agent-run"):
        (root / name).mkdir()
    environment = dict(HEPTA_FLEET_ROOT=str(root / "empty-fleet"),
        HEPTA_AGENT_ID="00000000-0000-4000-8000-000000000219", HEPTA_AGENT_GENERATION="1",
        HEPTA_AGENT_HOME=str(root / "agent-home"), HEPTA_AGENT_RUN_ROOT=str(root / "agent-run"),
        CODEX_HOME=str(root / "agent-home"))
    return SimpleNamespace(args=args, family=family, parent=parent, members=members, release_file=release_file,
        release=release, producer=producer, host=host, value=value, config_pin=config_pin, environment=environment, tcd=tcd, sidecar=sidecar)


class MissingOwnerTests(unittest.TestCase):
    def test_loader_overrides_reject_before_owner_reads_without_rewriting_environment(self):
        environment = {name: "original-" + name for name in handoff.REQUIRED_ENV}
        for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG", "LD_TRACE_LOADED_OBJECTS", "GLIBC_TUNABLES"):
            for value in ("controlled-forbidden-override", ""):
                with self.subTest(name=name, value=value), tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "absent-output"
                    supplied = dict(environment, **{name: value})
                    with self.assertRaisesRegex(ValueError, "loader overrides"):
                        handoff.load(Path(directory) / "absent-owner", "11" * 32, output, supplied)
                    self.assertEqual(supplied[name], value)
                    self.assertFalse(output.exists())
        original = dict(environment, LANG="C.UTF-8")
        self.assertEqual(handoff.checked_environment(original), original)

    def test_missing_owner_never_creates_output_or_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent-output"
            with self.assertRaisesRegex(handoff.NotConfigured, "independent"):
                handoff.load(None, None, output, {})
            with self.assertRaisesRegex(handoff.NotConfigured, "environment"):
                handoff.load(Path(directory) / "missing", "01" * 32, output, {})
            self.assertFalse(output.exists())

    def test_actual_cli_reports_not_configured_before_creating_any_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = [sys.executable, str(SCRIPTS / "run_llm_cell_native_handoff.py"), *CAPS,
                    "--runtime-snapshot", str(root / "unused-runtime-snapshot.json"),
                    "--runtime-snapshot-sha256", "00" * 32,
                    "--consumer-mode", "cell-host-v2"]
            for name in ("chain", "hepta", "source-parent", "source-materials", "output", "python", "cell-bin", "just", "hepta-target"):
                argv.extend(("--" + name, str(root / name)))
            result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)["status"], "NOT_CONFIGURED")
            self.assertEqual(list(root.iterdir()), [])

    def test_unknown_profile_or_old_json_cannot_select_content_fallback(self):
        for value in ({"profile": "unknown"}, {"profile": "cell-pq-v2"}, {"profile": "content-cache-v1", "authority": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                handoff.authentication(value)
        with self.assertRaises(ValueError):
            handoff.unique([("schema", "one"), ("schema", "two")])


@unittest.skipUnless(NATIVE, "requires exact freshly built TRNM_CELL_BIN; no native evidence without it")
class NativeProducerTests(unittest.TestCase):
    def test_empty_loader_trace_is_effective_but_cannot_skip_native_host_main(self):
        # A real glibc empty-value counterexample: exit zero need not mean main ran.
        environment = {name: value for name, value in os.environ.items()
                       if not name.startswith("LD_") and name != "GLIBC_TUNABLES"}
        marker = "controlled-ELF-main-was-reached"
        clean = subprocess.run([shutil.which("echo"), marker], env=environment, capture_output=True, text=True)
        trace = subprocess.run([shutil.which("echo"), marker], env=dict(environment, LD_TRACE_LOADED_OBJECTS=""), capture_output=True, text=True)
        self.assertEqual((clean.returncode, clean.stdout.strip()), (0, marker))
        self.assertEqual(trace.returncode, 0)
        self.assertNotIn(marker, trace.stdout)
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory))
            plan = handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            try:
                pid = os.fork()
                if pid == 0:
                    try:
                        os.environ["LD_TRACE_LOADED_OBJECTS"] = ""
                        plan.exec_owner()
                    except ValueError as error:
                        os._exit(73 if "loader overrides" in str(error) else 74)
                    finally:
                        os._exit(123)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                self.assertFalse(f.args.output.exists())
            finally:
                plan.close()

    def test_loader_override_inserted_after_load_cannot_reach_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory))
            plan = handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            try:
                pid = os.fork()
                if pid == 0:
                    try:
                        os.environ["LD_PRELOAD"] = "/controlled-must-never-be-loaded.so"
                        plan.exec_owner()
                    except ValueError as error:
                        os._exit(73 if "loader overrides" in str(error) else 74)
                    finally:
                        os._exit(123)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                self.assertFalse(f.args.output.exists())
            finally:
                plan.close()

    def test_native_pq_swap_cannot_replace_independently_pinned_withdrawal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            f = fixture(root)
            seed = root / "explicit-test-only-seed"
            save(seed, b"\x4d" * 32)
            spki = root / "original-signer.spki"
            public = subprocess.run([NATIVE, "pq-key-public", "--pq-seed-file", str(seed),
                "--output", str(spki)], check=True, capture_output=True, text=True)
            key_id = json.loads(public.stdout)["key_id"]
            now = int(time.time())
            signed = {}
            for name, withdrawn in (("A", "true"), ("B", "false")):
                path = root / (name + ".cpr2")
                subprocess.run([NATIVE, "sign-release", "--authentication-profile", "cell-pq-v2",
                    "--release-file", str(f.release_file), "--release", f.release["release"],
                    "--output", str(path), "--pq-seed-file", str(seed), "--pq-signer-key-id", key_id,
                    "--pq-network", "61" * 32, "--pq-parameters", "62" * 32,
                    "--pq-generation", "1", "--pq-sequence", "1", "--pq-issued", str(now - 1),
                    "--pq-expires", str(now + 600), "--pq-withdrawn", withdrawn],
                    check=True, capture_output=True)
                signed[name] = path.read_bytes()
                self.assertEqual(len(signed[name]), 3509)
            original = root / "original-authorization.cpr2"
            f.value["authentication"] = dict(profile="cell-pq-v2",
                authorization=save(original, signed["A"]),
                signer_spki=dict(path=str(spki), sha256=handoff.checksum(spki.read_bytes())),
                signer_key_id=key_id, generation=1, sequence=1, network="61" * 32,
                parameters="62" * 32, key_not_before=now - 60, key_expires=now + 600, key_revoked_at=None)
            config = save(Path(f.config_pin["path"]), handoff.canonical(f.value))
            plan = handoff.load(Path(config["path"]), config["sha256"], f.args.output, f.environment)
            try:
                # Load pins A's file bytes, not a native successful-use decision.
                self.assertFalse(f.args.output.exists())
                with self.assertRaisesRegex(ValueError, "not prepared"):
                    _ = plan.auth
                original.write_bytes(signed["B"])
                f.args.output.mkdir(mode=0o700)
                closure = handoff.prepare(plan, f.args, f.family, f.parent, f.members,
                    f.release_file, f.release, f.producer, time.monotonic() + 120)
                auth = dict(zip(plan.auth[::2], plan.auth[1::2]))
                frozen_authorization = Path(auth["--pq-authorization"])
                frozen_spki = Path(auth["--pq-signer-spki"])
                self.assertEqual(frozen_authorization.parent, f.args.output)
                self.assertEqual(frozen_spki.parent, f.args.output)
                self.assertEqual(frozen_authorization.read_bytes(), signed["A"])
                self.assertEqual(frozen_spki.read_bytes(), spki.read_bytes())
                self.assertEqual(f.args.output.stat().st_mode & 0o777, 0o700)
                for path in (frozen_authorization, frozen_spki):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(FileExistsError):
                    plan.publish_auth(f.args.output)
                context = [item for key, value in f.value["context"].items()
                           for item in ("--" + key, value)]

                def fetch(arguments, store, marker):
                    return subprocess.run([NATIVE, "fetch-closure", *CAPS, *arguments,
                        "--store", str(store), "--closure-file", str(closure),
                        "--closure", f.host["dependency_closure_id"], "--loader-generation", "3",
                        "--loader-profile", f.value["loader_profile"], "--required-roles", "base,tokenizer,adapter,configuration",
                        *context, "--peers", "", "--output", str(marker),
                        "--max-bytes", str(f.release["payload_bytes"]), "--max-chunks", "11",
                        "--overall-ms", "2000", "--request-ms", "1000", "--max-response-bytes", "0",
                        "--max-connections", "1", "--parallelism", "1"], capture_output=True, text=True, timeout=5)

                accepted = dict(auth, **{"--pq-authorization": str(original)})
                positive = fetch([value for pair in accepted.items() for value in pair],
                                 f.producer, root / "actual-B-native-complete.tcd1")
                self.assertEqual(positive.returncode, 0, positive.stderr)
                self.assertEqual(json.loads(positive.stdout)["closure"], f.host["dependency_closure_id"])
                for swapped_spki in (False, True):
                    if swapped_spki:
                        spki.write_bytes(b"\0" * 1974)
                    store = root / ("must-remain-absent-" + str(swapped_spki) + ".sqlite")
                    marker = root / ("must-remain-absent-" + str(swapped_spki) + ".tcd1")
                    denied = fetch(plan.auth, store, marker)
                    self.assertNotEqual(denied.returncode, 0)
                    self.assertIn("PQ Cell release withdrawn", denied.stderr)
                    self.assertFalse(store.exists())
                    self.assertFalse(marker.exists())
            finally:
                plan.close()

    def test_sealed_executable_keeps_original_elf_after_same_inode_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory))
            plan = handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            try:
                original = Path(f.value["executable"]["path"])
                inode = original.stat().st_ino
                original.write_bytes(Path(shutil.which("false")).read_bytes())
                self.assertEqual(original.stat().st_ino, inode)
                self.assertNotEqual(handoff.checksum(original.read_bytes()), f.value["executable"]["sha256"])
                self.assertEqual(subprocess.run([str(original)]).returncode, 1)
                fd = plan.executable.fileno()
                self.assertEqual(handoff.fcntl.fcntl(fd, handoff.GET_SEALS) & handoff.EXECUTABLE_SEALS,
                                 handoff.EXECUTABLE_SEALS)
                for mutation in (lambda: os.pwrite(fd, b"changed", 0),
                                 lambda: os.ftruncate(fd, 1),
                                 lambda: os.ftruncate(fd, os.fstat(fd).st_size + 1)):
                    with self.assertRaises(PermissionError):
                        mutation()
                read_fd, write_fd = os.pipe()
                pid = os.fork()
                if pid == 0:
                    try:
                        os.close(read_fd)
                        os.dup2(write_fd, 1)
                        os.close(write_fd)
                        plan.exec_owner()
                    finally:
                        os._exit(123)
                os.close(write_fd)
                with os.fdopen(read_fd, "rb") as stream:
                    observed = stream.read()
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                self.assertIn(b"--host-format cell-v2 --host-config", observed)
                self.assertFalse(f.args.output.exists())
            finally:
                plan.close()

    def test_missing_executable_seals_cannot_fall_back_to_original_path(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory))
            with mock.patch.object(handoff.os, "memfd_create", side_effect=OSError("controlled unavailable")):
                with self.assertRaisesRegex(handoff.NotConfigured, "sealed"):
                    handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            self.assertFalse(f.args.output.exists())

    def test_deadline_expiring_during_real_publication_keeps_handoff_unprepared(self):
        # Real files/fsync and native manifest exports; only this control's clock is synthetic.
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory)); f.args.output.mkdir(mode=0o700)
            plan = handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            clock, actual_publish = [100.0], handoff.publish

            def publish_then_expire(path, raw):
                actual_publish(path, raw)
                clock[0] = 220.001

            try:
                with mock.patch.object(handoff.time, "monotonic", side_effect=lambda: clock[0]), \
                        mock.patch.object(handoff, "publish", side_effect=publish_then_expire):
                    with self.assertRaisesRegex(TimeoutError, "after protected publication"):
                        handoff.prepare(plan, f.args, f.family, f.parent, f.members,
                            f.release_file, f.release, f.producer, 220.0)
                self.assertEqual((f.args.output / "source-closure.tcd1").read_bytes(), f.tcd)
                self.assertIsNone(plan.sidecar)
                with self.assertRaisesRegex(ValueError, "not prepared"):
                    _ = plan.auth
                self.assertFalse(Path(plan.host["dependency_closure"]["path"]).exists())
                self.assertFalse(Path(plan.host["sidecar"]["path"]).exists())
            finally:
                plan.close()

    def test_actual_native_manifests_produce_exact_pinned_sidecar_and_tcd(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory)); f.args.output.mkdir(mode=0o700)
            plan = handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            try:
                path = handoff.prepare(plan, f.args, f.family, f.parent, f.members, f.release_file, f.release, f.producer, time.monotonic() + 120)
                self.assertEqual(path.read_bytes(), f.tcd)
                self.assertEqual(plan.sidecar, handoff.canonical(f.sidecar))
                self.assertFalse(Path(plan.host["dependency_closure"]["path"]).exists())
                self.assertFalse(Path(plan.host["sidecar"]["path"]).exists())
            finally:
                plan.close()

    def test_owner_mismatch_missing_member_or_expired_preparation_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory)); f.args.output.mkdir(mode=0o700)
            plan = handoff.load(Path(f.config_pin["path"]), f.config_pin["sha256"], f.args.output, f.environment)
            try:
                for field in ("generation", "loader_profile", "context"):
                    original = copy.deepcopy(plan.value[field])
                    plan.value[field] = 4 if field == "generation" else "77" * 32 if field == "loader_profile" else dict(original, parent="77" * 32)
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        handoff.prepare(plan, f.args, f.family, f.parent, f.members, f.release_file, f.release, f.producer, time.monotonic() + 120)
                    plan.value[field] = original
                with self.assertRaises(ValueError):
                    handoff.prepare(plan, f.args, f.family, f.parent, f.members[:-1], f.release_file, f.release, f.producer, time.monotonic() + 120)
                with self.assertRaises(TimeoutError):
                    handoff.prepare(plan, f.args, f.family, f.parent, f.members, f.release_file, f.release, f.producer, time.monotonic())
                self.assertFalse((f.args.output / "source-closure.tcd1").exists())
                self.assertIsNone(plan.sidecar)
            finally:
                plan.close()

    def test_protected_pins_reject_tampering_symlink_and_wrong_schema_before_native_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory)); path = Path(f.config_pin["path"])
            with self.assertRaises(ValueError):
                handoff.load(path, "77" * 32, f.args.output, f.environment)
            alias = path.with_name("alias.json"); alias.symlink_to(path)
            with self.assertRaises(ValueError):
                handoff.load(alias, f.config_pin["sha256"], f.args.output, f.environment)
            bad = dict(f.value, schema="pon-smollm-cell-native-handoff-v1")
            raw = handoff.canonical(bad); path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "schema"):
                handoff.load(path, handoff.checksum(raw), f.args.output, f.environment)
            legacy = copy.deepcopy(f.host)
            legacy["owner"]["schema"] = "hepta-smollm-cognitive-host-v1"
            host_pin = save(Path(f.value["host"]["path"]), handoff.canonical(legacy))
            raw = handoff.canonical(dict(f.value, host=host_pin)); path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "nested owner-v2"):
                handoff.load(path, handoff.checksum(raw), f.args.output, f.environment)
            self.assertFalse(f.args.output.exists())

    def test_real_transport_to_exec_contract_probe_never_claims_model_success(self):
        with tempfile.TemporaryDirectory() as directory:
            f = fixture(Path(directory))
            argv = [sys.executable, str(SCRIPTS / "run_llm_cell_native_handoff.py"), *CAPS,
                    "--runtime-snapshot", str(f.args.runtime_snapshot),
                    "--runtime-snapshot-sha256", f.args.runtime_snapshot_sha256,
                "--consumer-mode", "cell-host-v2", "--handoff-config", f.config_pin["path"],
                "--handoff-config-sha256", f.config_pin["sha256"]]
            for key, value in {"chain": f.args.chain, "hepta": Path(directory) / "hepta-not-used-for-probe",
                "source-parent": f.args.source_parent, "source-materials": f.args.source_materials, "output": f.args.output,
                "python": f.args.python, "cell-bin": f.args.cell_bin, "just": Path(directory) / "just-not-invoked",
                "hepta-target": Path(directory) / "target-not-invoked"}.items():
                argv.extend(("--" + key, str(value)))
            result = subprocess.run(argv, env=dict(os.environ, **f.environment), capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--host-format cell-v2 --host-config", result.stdout)
            report = json.loads((f.args.output / "handoff.json").read_bytes())
            self.assertEqual(report["status"], "transport-complete-handoff-pending")
            self.assertEqual(report["native_receipt_status"], "UNVERIFIED")
            self.assertEqual(report["producer_exit_code_before_consumer_load"], 0)
            self.assertTrue(report["transfer"]["within_original_deadline"])
            self.assertEqual(report["transfer"]["limit_seconds"], 35)
            self.assertEqual((f.args.output / "consumer-release.tcd1").read_bytes(), f.tcd)
            self.assertEqual(json.loads((f.args.output / "consumer-cell-sidecar.json").read_bytes()), f.sidecar)
            for key in ("installation_observed", "final_use_observed", "product_qualification", "production_activation"):
                self.assertIs(report[key], False)
            self.assertTrue(all(member["fetch"]["downloaded_chunks"] == 0 for member in report["members"]))


if __name__ == "__main__":
    unittest.main()
