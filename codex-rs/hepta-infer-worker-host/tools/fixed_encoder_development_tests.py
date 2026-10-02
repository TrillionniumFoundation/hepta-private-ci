"""Closed measurement admission/cost tests; live Root registration is separate."""

import copy
import os
import socket
import subprocess
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fixed_encoder_development as dev


def source(path):
    return {"path": path, "sha256": "a" * 64, "size": 1}


def service(name, uid, pid):
    return {
        "unit_name": name + ".service",
        "unit_source": source("/etc/systemd/system/" + name + ".service"),
        "exec_start": "{ path=/usr/bin/python3.12 ; argv[]=/usr/bin/python3.12 -I -S /opt/fixed/g.py ; }",
        "user": str(uid) if uid else "",
        "group": str(uid) if uid else "",
        "uid": uid,
        "gid": uid,
        "main_pid": pid,
        "start_ticks": 10 + pid,
        "cgroup": "/system.slice/" + name + ".service",
        "cgroup_device": 1,
        "cgroup_inode": 2,
        "cpu_millis_per_second": 2000,
        "memory_max_bytes": 1024 * 1024 * 1024,
    }


def fixture():
    producer = service("generator", os.getuid(), os.getpid())
    encoder = service("encoder", 0, os.getpid())
    encoder_declaration = {
        key: value
        for key, value in encoder.items()
        if key not in ("main_pid", "start_ticks", "cgroup_device", "cgroup_inode")
    }
    encoder_declaration["process_binding"] = "EncoderSelfV1"
    backend = service("backend", 968, os.getpid() + 1)
    pair = {
        "pair_id": "public.one",
        "source_row_sha256": "b" * 64,
        "claim_text": "Public claim",
        "title": "Public article",
        "abstract_sentences": ["Public text."],
    }
    config = {
        "backend_pid": backend["main_pid"],
        "backend_uid": 968,
        "backend_cgroup": backend["cgroup"],
        "backend_start_time": str(backend["start_ticks"]),
        "backend_unit_source": backend["unit_source"],
        "expires_at_ms": time.time_ns() // 1_000_000 + 60_000,
        "timeout_ms": 2000,
        "max_requests": 4,
        "model_sources": [source("/opt/model/manifests/nomic")],
        "program_sources": [],
        "runtime_sources": [],
        "numpy_sources": [],
        "preprocessor_source": source("/opt/fixed/norm.json"),
        "pairs_source": source("/opt/fixed/pairs.json"),
    }
    config["public_development"] = {
        "systemctl_source": source("/usr/bin/systemctl"),
        "encoder_service": encoder_declaration,
        "backend_service": backend,
        "batches": [
            {
                "batch_id": "batch.one",
                "purpose": dev.PURPOSE,
                "producer": producer,
                "producer_sources": [source("/usr/bin/python3.12"), source("/opt/fixed/g.py")],
                "pairs": [{"pair_id": pair["pair_id"], "source_row_sha256": pair["source_row_sha256"]}],
                "expires_at_ms": config["expires_at_ms"],
                "max_requests": 2,
            }
        ],
    }
    request = {
        "purpose": dev.PURPOSE,
        "batch_id": "batch.one",
        "pair_id": pair["pair_id"],
        "source_row_sha256": pair["source_row_sha256"],
    }
    return config, {pair["pair_id"]: pair}, request


def fingerprint(_):
    return (1, 2, 0, 0, 0o100444, 1, 1, 10, 10)


def new_measurements(config, pairs):
    declaration = config["public_development"]["encoder_service"]
    encoder = {
        **{key: value for key, value in declaration.items() if key != "process_binding"},
        "main_pid": os.getpid(),
        "start_ticks": 10 + os.getpid(),
        "cgroup_device": 1,
        "cgroup_inode": 2,
    }
    with (
        patch.object(dev, "fingerprint", fingerprint),
        patch.object(dev, "verify_large_source"),
        patch.object(dev, "encoder_self_service", return_value=encoder),
    ):
        return dev.DevelopmentMeasurements(config, pairs)


def observation(_, service, _deadline):
    return {
        "unit": service["unit_name"],
        "pid": service["main_pid"],
        "start_ticks": service["start_ticks"],
        "uid": service["uid"],
        "cgroup": service["cgroup"],
        "cpu_usage_usec": 10,
        "memory_current_bytes": 50,
        "memory_peak_bytes": 60,
    }


class DevelopmentTests(unittest.TestCase):
    def test_late_registered_service_derives_peer_without_a_future_pid(self):
        config, pairs, request = fixture()
        batch = config["public_development"]["batches"][0]
        producer = batch["producer"]
        original = dict(producer)
        for key in ("main_pid", "start_ticks", "cgroup_device", "cgroup_inode"):
            del producer[key]
        producer.update(
            user="",
            group="",
            process_binding="RegisteredServiceMainPidV2",
            exec_start=(
                "{ path=/usr/bin/setpriv ; argv[]=/usr/bin/setpriv "
                f"--reuid={os.getuid()} --regid={os.getgid()} --clear-groups --no-new-privs "
                "--bounding-set=-all --inh-caps=-all --ambient-caps=-all -- /opt/fixed/g ; }"
            ),
        )
        batch["producer_sources"].append(source("/usr/bin/setpriv"))
        measurements = new_measurements(config, pairs)
        metadata = type("Metadata", (), {"st_dev": 7, "st_ino": 8})()
        path = type("Cgroup", (), {"stat": lambda _: metadata})()
        identity = (original["start_ticks"], [os.getuid()] * 4, [os.getgid()] * 4, producer["cgroup"])
        left, right = socket.socketpair(socket.AF_UNIX)
        with (
            left,
            right,
            patch.object(dev, "fingerprint", fingerprint),
            patch.object(dev, "kernel_identity", return_value=identity),
            patch.object(dev, "protected_path", return_value=path),
            patch.object(dev, "observe_service", observation),
        ):
            result = measurements.measure(left, request, None, None, "pin", lambda *_: {"features_q24": [1] * 512})
        self.assertEqual(result["cost_context"]["producer_before"]["pid"], os.getpid())
        self.assertFalse("main_pid" in producer)
        for cause in ("pid", "flag", "source"):
            bad = copy.deepcopy(config)
            changed = bad["public_development"]["batches"][0]
            if cause == "pid":
                changed["producer"]["main_pid"] = os.getpid()
            elif cause == "flag":
                changed["producer"]["exec_start"] = changed["producer"]["exec_start"].replace(
                    "--clear-groups", "--keep-groups"
                )
            else:
                changed["producer_sources"].pop()
            with self.assertRaises(ValueError):
                new_measurements(bad, pairs)
        with patch.object(dev, "kernel_identity", return_value=(1, [1] * 4, [2] * 4, producer["cgroup"])):
            with self.assertRaises(ValueError):
                dev.resolve_registered_producer(producer, os.getpid())

    def test_service_manager_rejects_non_main_peer_even_with_the_same_uid(self):
        producer = service("generator", os.getuid(), os.getpid())
        properties = {
            "Id": producer["unit_name"],
            "FragmentPath": producer["unit_source"]["path"],
            "ExecStart": producer["exec_start"],
            "User": producer["user"],
            "Group": producer["group"],
            "MainPID": str(os.getpid() + 1),
            "ControlGroup": producer["cgroup"],
            "Delegate": "no",
        }
        completed = type(
            "Completed", (), {"returncode": 0, "stdout": "".join(f"{k}={v}\n" for k, v in properties.items()).encode()}
        )()
        with patch.object(dev.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(ValueError, "exact Root registration"):
                dev.service_properties("/usr/bin/systemctl", producer, time.monotonic_ns() + 1_000_000_000)

    def test_root_setpriv_launcher_keeps_actual_mainpid_and_final_g_role(self):
        config, pairs, request = fixture()
        producer = config["public_development"]["batches"][0]["producer"]
        producer.update(
            {
                "user": "",
                "group": "",
                "process_binding": "CredentialDroppingMainPidV1",
                "exec_start": (
                    "{ path=/usr/bin/setpriv ; argv[]=/usr/bin/setpriv "
                    f"--reuid={os.getuid()} --regid={os.getgid()} --clear-groups --no-new-privs "
                    "--bounding-set=-all --inh-caps=-all --ambient-caps=-all -- "
                    "/usr/bin/python3.12 -I -S /opt/fixed/g.py ; }"
                ),
            }
        )
        batch = config["public_development"]["batches"][0]
        batch["producer_sources"].append(source("/usr/bin/setpriv"))
        measurements = new_measurements(config, pairs)
        left, right = socket.socketpair(socket.AF_UNIX)
        with (
            left,
            right,
            patch.object(dev, "fingerprint", fingerprint),
            patch.object(dev, "observe_service", observation),
        ):
            result = measurements.measure(left, request, None, None, "pin", lambda *_: {"features_q24": [1] * 512})
            self.assertEqual(result["cost_context"]["producer_before"]["uid"], os.getuid())
        for cause in ("source", "flag", "account"):
            bad = copy.deepcopy(config)
            record = bad["public_development"]["batches"][0]
            if cause == "source":
                record["producer_sources"].pop()
            elif cause == "flag":
                record["producer"]["exec_start"] = record["producer"]["exec_start"].replace(
                    "--clear-groups", "--keep-groups"
                )
            else:
                record["producer"]["user"] = str(os.getuid())
            with self.assertRaises(ValueError):
                new_measurements(bad, pairs)

    def test_kernel_boundary_allows_only_own_primary_group_and_no_capability(self):
        class Proc:
            def __init__(self, parts=()):
                self.parts = parts

            def __truediv__(self, part):
                return Proc((*self.parts, part))

            def read_text(self):
                return files[self.parts[-1]]

        status = (
            "Uid:\t968 968 968 968\nGid:\t968 968 968 968\nGroups:\t{groups}\n"
            "NoNewPrivs:\t1\nCapInh:\t0\nCapPrm:\t0\nCapEff:\t0\nCapBnd:\t0\nCapAmb:\t0\n"
        )
        files = {
            "stat": "123 (process) " + " ".join(["0"] * 19 + ["456"]),
            "cgroup": "0::/system.slice/backend.service\n",
        }
        for groups in ("", "968"):
            files["status"] = status.format(groups=groups)
            with patch.object(dev, "Path", return_value=Proc()):
                self.assertEqual(dev.kernel_identity(123), (456, [968] * 4, [968] * 4, "/system.slice/backend.service"))
        for changed in (
            status.format(groups="968 978"),
            status.format(groups="968").replace("CapBnd:\t0", "CapBnd:\t1"),
        ):
            files["status"] = changed
            with patch.object(dev, "Path", return_value=Proc()), self.assertRaises(ValueError):
                dev.kernel_identity(123)

    def test_real_socket_peer_closed_row_and_entire_service_cost(self):
        config, pairs, request = fixture()
        measurements = new_measurements(config, pairs)
        calls = []

        def encode(actual_config, _preprocessor, _numpy, pair, pin):
            calls.append((actual_config["timeout_ms"], pair["source_row_sha256"], pin))
            return {
                "pair_id": pair["pair_id"],
                "source_row_sha256": pair["source_row_sha256"],
                "features_q24": [2] * 512,
                "physical_elapsed_micros": 25,
            }

        left, right = socket.socketpair(socket.AF_UNIX)
        with (
            left,
            right,
            patch.object(dev, "fingerprint", fingerprint),
            patch.object(dev, "observe_service", observation),
        ):
            result = measurements.measure(left, request, None, None, "pin", encode)
            self.assertEqual(result["features_q24"], [2] * 512)
            self.assertEqual(result["encoder_manifest_sha256"], "a" * 64)
            self.assertEqual(
                result["cost_context"]["accounting"],
                "entire-encoder-and-backend-service-conservative",
            )
            self.assertEqual(len(result["cost_context"]["services_before"]), 2)
            self.assertEqual(result["cost_context"]["producer_before"]["pid"], os.getpid())
            self.assertGreater(result["measurement_elapsed_micros"], 0)
            self.assertTrue(0 < calls[0][0] <= config["timeout_ms"])
            self.assertEqual(calls[0][1:], (request["source_row_sha256"], "pin"))

    def test_foreign_peer_wrong_row_extra_gold_and_exhausted_batch_never_encode(self):
        config, pairs, request = fixture()
        wrong_peer = copy.deepcopy(config)
        wrong_peer["public_development"]["batches"][0]["producer"]["main_pid"] += 10
        for settings, changed in [
            (wrong_peer, request),
            (config, {**request, "source_row_sha256": "c" * 64}),
            (config, {**request, "gold": "support"}),
            (config, {**request, "purpose": "InstallModel"}),
        ]:
            measurements = new_measurements(settings, pairs)
            left, right = socket.socketpair(socket.AF_UNIX)
            with (
                left,
                right,
                patch.object(dev, "observe_service", observation),
                self.assertRaises(ValueError),
            ):
                measurements.measure(left, changed, None, None, "pin", lambda *_: self.fail("must not encode"))
        measurements = new_measurements(config, pairs)
        measurements.remaining[request["batch_id"]] = 0
        with self.assertRaises(ValueError):
            measurements.measure(None, request, None, None, "pin", lambda *_: self.fail("must not encode"))

    def test_changed_sources_expired_window_or_missing_metrics_never_encode(self):
        config, pairs, request = fixture()
        for cause in ("source", "expiry", "metric"):
            measurements = new_measurements(copy.deepcopy(config), pairs)
            if cause == "expiry":
                measurements.config["expires_at_ms"] = 1
            left, right = socket.socketpair(socket.AF_UNIX)
            with (
                left,
                right,
                patch.object(dev, "fingerprint", lambda _: (9,) if cause == "source" else fingerprint(None)),
                patch.object(dev, "observe_service", side_effect=OSError("no metric")),
                self.assertRaises((ValueError, OSError)),
            ):
                measurements.measure(left, request, None, None, "pin", lambda *_: self.fail("must not encode"))

    def test_counter_or_peer_replacement_after_real_encoding_rejects_result(self):
        config, pairs, request = fixture()
        for changed in ("counter", "lifetime"):
            measurements = new_measurements(config, pairs)
            observations = []
            for index, service_record in enumerate(
                [
                    config["public_development"]["batches"][0]["producer"],
                    measurements.encoder,
                    measurements.backend,
                    measurements.encoder,
                    measurements.backend,
                    config["public_development"]["batches"][0]["producer"],
                ]
            ):
                record = observation(None, service_record, None)
                if index == 3:
                    record["cpu_usage_usec" if changed == "counter" else "start_ticks"] = 1
                observations.append(record)
            left, right = socket.socketpair(socket.AF_UNIX)
            with (
                left,
                right,
                patch.object(dev, "fingerprint", fingerprint),
                patch.object(dev, "observe_service", side_effect=observations),
                self.assertRaises(ValueError),
            ):
                measurements.measure(left, request, None, None, "pin", lambda *_: {"features_q24": [1] * 512})

    def test_service_manager_exact_root_registration_and_timeout_fail_closed(self):
        service_record = service("generator", 1000, 123)
        properties = {
            "Id": service_record["unit_name"],
            "FragmentPath": service_record["unit_source"]["path"],
            "ExecStart": service_record["exec_start"],
            "User": "1000",
            "Group": "1000",
            "MainPID": "123",
            "ControlGroup": service_record["cgroup"],
            "Delegate": "no",
        }
        payload = lambda values: "".join(f"{key}={value}\n" for key, value in values.items()).encode()
        with patch.object(
            dev.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=payload(properties)),
        ) as run:
            dev.service_properties("/usr/bin/systemctl", service_record, time.monotonic_ns() + 2_000_000_000)
            self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/usr/bin:/bin", "LANG": "C"})
        for field, bad in [("MainPID", "124"), ("Delegate", "yes"), ("ExecStart", "different")]:
            with (
                patch.object(
                    dev.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout=payload({**properties, field: bad})),
                ),
                self.assertRaises(ValueError),
            ):
                dev.service_properties("/usr/bin/systemctl", service_record, time.monotonic_ns() + 2_000_000_000)
        with (
            patch.object(dev.subprocess, "run", side_effect=subprocess.TimeoutExpired("systemctl", 1)),
            self.assertRaises(ValueError),
        ):
            dev.service_properties("/usr/bin/systemctl", service_record, time.monotonic_ns() + 2_000_000_000)

    def test_unbounded_or_misbound_root_declaration_is_rejected(self):
        config, pairs, _ = fixture()
        for changed in ("cpu", "memory", "backend", "pair", "purpose"):
            bad = copy.deepcopy(config)
            declaration = bad["public_development"]
            if changed == "cpu":
                declaration["encoder_service"]["cpu_millis_per_second"] = 4001
            elif changed == "memory":
                declaration["backend_service"]["memory_max_bytes"] *= 2
            elif changed == "backend":
                declaration["backend_service"]["main_pid"] += 1
            elif changed == "pair":
                declaration["batches"][0]["pairs"][0]["source_row_sha256"] = "c" * 64
            else:
                declaration["batches"][0]["purpose"] = "AnswerAccept"
            with self.assertRaises(ValueError):
                new_measurements(bad, pairs)


if __name__ == "__main__":
    unittest.main()
