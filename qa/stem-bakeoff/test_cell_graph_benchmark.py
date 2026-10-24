"""Numerical/ownership mechanics on constructed fixtures; no public model or task data."""

import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import cell_graph_benchmark as bench
from cell_graph_reduce import compare_tensors, read_worker, reduce_graph, validate_recovery
from cell_graph_report import owner_check, recovery_events_valid, report
from cell_graph_worker import HEAD_IDS, array, canonical, execute, infer, inventory, own_cgroup_limits, sha, strict_json, tensor
from cell_learning_models import NumpyCellHead

ROOT = Path(__file__).parent


def fixture():
    rng = np.random.default_rng(20261024)
    features = rng.normal(size=(480, 8))
    features[0] = 0
    heads, portable = [], []
    for index, name in enumerate(HEAD_IDS):
        head = NumpyCellHead(8, 4, ("linear", "gated")[index % 2], seed=(7, 17, 29)[index // 2])
        for key in head.params:
            head.params[key] += rng.normal(size=head.params[key].shape)
        if head.mode == "gated":
            head.params["g"][0] = 50
            head.params["g"][1] = -50
        heads.append(head)
        portable.append({"id": name, "mode": head.mode, "tensor_sha256": head.digest(),
            "params": {key: tensor(value) for key, value in head.params.items()}})
    return features, heads, portable


def request(features, portable, indices, env_sha):
    return {"schema": "hepta.fixed-cell-graph.worker.v1", "request_id": "b0-A-s0",
        "graph_sha256": "a" * 64, "protocol_sha256": "b" * 64, "environment_sha256": env_sha,
        "features": tensor(features), "heads": [portable[i] for i in indices], "head_indices": list(indices),
        "resource_limits": {"cpu_quota_percent": 200 if len(indices) == 6 else 100,
                            "memory_max_bytes": 2147483648 if len(indices) == 6 else 1073741824}, "authority": "DENY_ALL"}


def protocol_fixture():
    return {"schema": bench.SCHEMA, "status": "FROZEN_BEFORE_GRAPH_INFERENCE", "head_ids": list(HEAD_IDS),
        "block_orders": [list(v) for v in bench.BLOCK_ORDERS], "shards": [list(v) for v in bench.SHARDS],
        "authority": "DENY_ALL", "worker_count": 30, "graph_count": 18,
        "source_code_sha256": {name: sha((ROOT / name).read_bytes()) for name in
            ("cell_graph_worker.py", "cell_graph_benchmark.py", "cell_graph_reduce.py", "cell_graph_report.py", "cell_graph_owner.js")}}


class GraphWorkerTests(unittest.TestCase):
    def test_all_six_original_arithmetic_bitwise_including_clipping_and_zero_row(self):
        features, heads, portable = fixture()
        for head, frozen in zip(heads, portable, strict=True):
            np.testing.assert_array_equal(head.predict_proba(features), infer(features, frozen))

    def test_portable_bytes_exact_and_corruption_fails(self):
        features, _, _ = fixture()
        value = tensor(features)
        np.testing.assert_array_equal(array(value, (480, 8)), features)
        value["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            array(value, (480, 8))

    def test_head_identity_cannot_be_relabelled(self):
        features, _, heads = fixture()
        heads[0]["tensor_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "tensor identity"):
            infer(features, heads[0])

    def test_nonfinite_and_duplicate_json_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(data)
        with self.assertRaisesRegex(ValueError, "finite"):
            tensor(np.array([float("nan")]))

    def test_own_cgroup_reader_uses_only_known_self_kernel_paths(self):
        files = {"/proc/self/cgroup": b"0::/unit-test\n",
                 "/sys/fs/cgroup/unit-test/cpu.max": b"100000 100000\n",
                 "/sys/fs/cgroup/unit-test/memory.max": b"1073741824\n"}
        seen = []
        def reader(path):
            seen.append(str(path))
            return files[str(path)]
        with patch.object(Path, "read_bytes", reader):
            value = own_cgroup_limits()
        self.assertEqual(value["memory_max_bytes"], 1073741824)
        self.assertEqual(set(seen), set(files))
        files["/proc/self/cgroup"] = b"0::/../../outside\n"
        with patch.object(Path, "read_bytes", reader):
            with self.assertRaisesRegex(ValueError, "unambiguous"):
                own_cgroup_limits()

    def test_wrong_own_cgroup_cap_rejected_before_inference(self):
        features, _, heads = fixture()
        spec = request(features, heads, (0, 1, 2), sha(canonical(inventory())))
        payload = canonical(spec)
        caps = {"cpu_quota_us": 50000, "cpu_period_us": 100000, "memory_max_bytes": 1073741824}
        with patch("cell_graph_worker.own_cgroup_limits", return_value=caps):
            with self.assertRaisesRegex(ValueError, "own cgroup ceilings differ"):
                execute(payload, sha(payload))

    def test_original_normalization_overflow_is_rejected(self):
        _, _, heads = fixture()
        with np.errstate(over="ignore"):
            with self.assertRaisesRegex(ValueError, "normalization"):
                infer(np.full((480, 8), 1e300), heads[0])

    def test_wrong_shape_and_oversize_fail_before_numeric_work(self):
        features, _, heads = fixture()
        item = tensor(features)
        item["shape"] = [999999999, 8]
        with self.assertRaises(ValueError):
            array(item, (480, 8))
        data = b"x" * 1_048_577
        with self.assertRaisesRegex(ValueError, "bound"):
            execute(data, sha(data))

    def test_partial_head_census_and_changed_environment_rejected(self):
        features, _, heads = fixture()
        spec = request(features, heads, (0, 1, 2), "0" * 64)
        payload = canonical(spec)
        with self.assertRaisesRegex(ValueError, "environment"):
            execute(payload, sha(payload))
        spec["head_indices"] = [0, 0, 2]
        payload = canonical(spec)
        with self.assertRaisesRegex(ValueError, "bounded fixed"):
            execute(payload, sha(payload))

    def test_real_cold_subprocess_receipts_and_stdout_bound(self):
        path = str(ROOT / "cell_graph_worker.py")
        env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": ""}
        result = subprocess.run([sys.executable, path, "--inventory"], capture_output=True, check=True, env=env, timeout=10)
        preflight = strict_json(result.stdout)
        features, heads, portable = fixture()
        spec = request(features, portable, range(6), sha(canonical(preflight)))
        payload = canonical(spec) + b"\n"
        # Cloud local tests cannot provision native systemd cgroups. Only the
        # own-limit reader is injected here; math/import/serialization are real.
        limits = {"cpu_quota_us": 200000, "cpu_period_us": 100000, "memory_max_bytes": 2147483648,
                  "cpu_max": "200000 100000", "memory_max": "2147483648", "scope": "constructed unit-test limits"}
        wrapper = ("import sys;sys.path.insert(0," + repr(str(ROOT)) + ");import cell_graph_worker as w;"
                   "w.own_cgroup_limits=lambda:" + repr(limits) + ";sys.argv=" + repr([path, "--expected-request-sha256", sha(payload)]) + ";w.main()")
        completed = subprocess.run([sys.executable, "-c", wrapper],
            input=payload, capture_output=True, check=True, env=env, timeout=10)
        expected = {"request_id": spec["request_id"], "request_sha256": sha(payload),
            "environment_sha256": spec["environment_sha256"], "head_indices": list(range(6)), "request_bytes": len(payload),
            "cpu_quota_percent": 200, "memory_max_bytes": 2147483648}
        values, receipt, trailer = read_worker(completed.stdout, expected)
        self.assertLess(len(completed.stdout), 196608)
        self.assertLess(len(payload), 1_048_576)
        self.assertEqual(receipt["child_process_cpu_ns"], 0)
        self.assertGreater(trailer["process_peak_rss_bytes"], 0)
        self.assertGreater(trailer["result_json_encode_wall_ns"], 0)
        for actual, head in zip(values, heads, strict=True):
            np.testing.assert_array_equal(actual, head.predict_proba(features))
        with self.assertRaisesRegex(ValueError, "two-line"):
            read_worker(completed.stdout.splitlines(keepends=True)[0], expected)
        bad = copy.deepcopy(expected);bad["request_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "stale"):
            read_worker(completed.stdout, bad)


class GraphPlanTests(unittest.TestCase):
    def test_exact_thirty_requests_rotation_quota_and_immutable_retry(self):
        features, _, heads = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proto = canonical(protocol_fixture()) + b"\n"
            (root / "protocol.json").write_bytes(proto)
            graph = {"protocol_sha256": sha(proto), "head_order": list(HEAD_IDS), "heads": heads, "features": tensor(features)}
            graph_data = canonical(graph) + b"\n";(root / "graph.json").write_bytes(graph_data)
            env = {"protocol_sha256": sha(proto), "frozen_before_inference": True,
                "inventory_sha256": {host: host * 4 for host in ("main", "pocket4")},
                "inventories": {host: {"python_executable": "/usr/bin/python3", "worker_source_sha256": "c" * 64} for host in ("main", "pocket4")}}
            env_data = canonical(env) + b"\n";(root / "env.json").write_bytes(env_data)
            kwargs = dict(expected_protocol_sha256=sha(proto), expected_graph_sha256=sha(graph_data), expected_environment_sha256=sha(env_data))
            result = bench.prepare_requests(root / "graph.json", root / "env.json", root / "protocol.json", root / "requests", **kwargs)
            self.assertEqual(result["requests"], 30)
            plan = strict_json((root / "requests/dispatch.json").read_bytes())
            keys = []
            for graph in plan["graphs"]:
                self.assertEqual(sum(r["cpu_quota_percent"] for r in graph["requests"]), 200)
                self.assertEqual(sorted(i for r in graph["requests"] for i in r["head_indices"]), list(range(6)))
                if graph["arm"] == "C":
                    self.assertEqual(graph["requests"][graph["block"] % 2]["host"], "pocket4")
                for r in graph["requests"]:
                    data = (root / "requests" / r["request_file"]).read_bytes()
                    self.assertEqual(sha(data), r["request_sha256"])
                    self.assertLess(len(data), 1_048_576)
                    keys.append(r["idempotency_key"])
            self.assertEqual(len(set(keys)), 30)
            with self.assertRaises(FileExistsError):
                bench.prepare_requests(root / "graph.json", root / "env.json", root / "protocol.json", root / "requests", **kwargs)

    def test_all_original_warmup_exports_only_no_outcome_read(self):
        from cell_field_state import CellTrainingState, dataset_digest
        retention = strict_json((ROOT / "cell_field_retention_experiment_protocol.json").read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);run = root / "run";run.mkdir()
            (run / "protocol.json").write_bytes((ROOT / "cell_field_retention_experiment_protocol.json").read_bytes())
            (run / "summary.json").write_text("OUTCOME MUST NEVER BE READ")
            (run / "final_labels.json").write_text("GOLD MUST NEVER BE READ")
            features, _, _ = fixture()
            projection = np.random.default_rng(9).normal(size=(384, 8))
            np.savez_compressed(run / "projected_features.npz", features=features, projection=projection)
            identity = {"projected_tensor_sha256": sha(features.tobytes()), "projection_sha256": sha(projection.tobytes()),
                        "projection": retention["projection"]}
            old, current = (features[:64], np.arange(64) % 4), (features[64:128], np.arange(64) % 4)
            contexts = {"old_train": dataset_digest(*old), "current_train": dataset_digest(*current)}
            for index, name in enumerate(HEAD_IDS):
                seed, mode = (7, 17, 29)[index // 2], ("linear", "gated")[index % 2]
                bindings = {"protocol_sha256": bench.RETENTION_PROTOCOL, "cohort_receipt_sha256": bench.COHORT_RECEIPT,
                    "seed": seed, "head": mode, "source_code_sha256": retention["source_code_sha256"], "feature_identity": identity}
                state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=seed), bindings=bindings,
                    protocol=retention["optimizer"], seed=seed, contexts=contexts, active_context="old_train")
                for _ in range(64):state.advance(*old)
                state.select_context("current_train")
                state.save(run / "initial" / name)
            proto = canonical(protocol_fixture()) + b"\n";(root / "graph_protocol.json").write_bytes(proto)
            receipt = bench.export_graph(run, root / "graph_protocol.json", root / "export", expected_protocol_sha256=sha(proto))
            self.assertFalse(receipt["labels_or_outcomes_read"])
            self.assertEqual(len(receipt["source_files"]), 14)
            self.assertFalse(any("summary" in name or "final_labels" in name for name in receipt["source_files"]))
            graph = strict_json((root / "export/graph.json").read_bytes())
            self.assertEqual(graph["head_order"], list(HEAD_IDS))
            self.assertEqual(len(graph["heads"]), 6)


class GraphBoundaryTests(unittest.TestCase):
    def test_two_shard_reducer_canonical_order_and_failed_node_preserved(self):
        features, heads, portable = fixture()
        truth = np.stack([head.predict_proba(features) for head in heads])
        requests, workers = [], []
        for shard, indices in enumerate(bench.SHARDS):
            req = {"request_id": f"b0-C-s{shard}", "request_sha256": str(shard) * 64,
                "environment_sha256": "a" * 64, "head_indices": list(indices), "request_bytes": 100,
                "host": "main" if shard else "pocket4", "idempotency_key": f"idem-{shard}", "cpu_quota_percent": 100, "memory_max_bytes": 1073741824}
            header = {"schema": "hepta.fixed-cell-graph.worker.v1", "status": "completed", "request_id": req["request_id"],
                "request_sha256": req["request_sha256"], "environment_sha256": req["environment_sha256"],
                "head_indices": list(indices), "head_ids": [HEAD_IDS[i] for i in indices], "child_process_cpu_ns": 0,
                "authority": "DENY_ALL", "model_checkpoint_or_task_labels_opened": False, "request_bytes": 100,
                "probabilities": [tensor(truth[i]) for i in indices], "phase_ns": {}, "graph_sha256": "b" * 64,
                "protocol_sha256": "c" * 64}
            limits = {"cpu_quota_us": 100000, "cpu_period_us": 100000, "memory_max_bytes": 1073741824,
                "cpu_max": "100000 100000", "memory_max": "1073741824"}
            header.update(own_cgroup_limits=limits, own_cgroup_receipt_sha256=sha(canonical(limits)), local_resource_ceiling_match=True)
            line = canonical(header) + b"\n"
            final = {"schema": "hepta.fixed-cell-graph.worker-final.v1", "status": "completed", "request_sha256": req["request_sha256"],
                "result_line_sha256": sha(line), "result_line_bytes": len(line), "worker_wall_ns_before_final_trailer": 1,
                "worker_cpu_ns_before_final_trailer": 1, "process_peak_rss_bytes": 1, "stdin_read_wall_ns": 1,
                "result_json_encode_wall_ns": 1, "result_stdout_write_wall_ns": 1}
            stdout = line + canonical(final) + b"\n"
            workers.append({"request_id": req["request_id"], "host": req["host"], "idempotency_key": req["idempotency_key"],
                "request_sha256": req["request_sha256"], "status": "completed", "exit_code": 0, "job_id": f"constructed-{shard}",
                "stdout_complete": True, "truncated": False, "stderr_bytes": 0, "stdout_base64": base64.b64encode(stdout).decode(),
                "stdout_sha256": sha(stdout), "effective_cpu_quota_percent": 100, "quota_receipt_sha256": "d" * 64,
                "authoritative_status_sha256": "e" * 64, "start_disposition": "created", "start_disposition_receipt_sha256": "f" * 64,
                "original_start_arguments_sha256": "a" * 64})
            requests.append(req)
        replay = {**workers[0], "start_disposition": "reused", "repeated_start_arguments_sha256": "a" * 64}
        self.assertTrue(validate_recovery(workers[0], replay, requests[0])["passed"])
        bad_original = {**workers[0], "status": "failed"}
        self.assertFalse(validate_recovery(bad_original, replay, requests[0])["passed"])
        replay["job_id"] = "another-job-same-predictions"
        self.assertFalse(validate_recovery(workers[0], replay, requests[0])["passed"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dispatch = {"graphs": [{"graph_id": "b0-C", "block": 0, "arm": "C", "requests": requests}],
                        "graph_sha256": "b" * 64, "protocol_sha256": "c" * 64}
            data = canonical(dispatch) + b"\n";(root / "dispatch.json").write_bytes(data)
            owner = {"schema": "hepta.fixed-cell-graph.collection.v1", "graph_id": "b0-C", "dispatch_sha256": sha(data), "workers": workers}
            (root / "owner.json").write_bytes(canonical(owner))
            result = reduce_graph(root / "dispatch.json", "b0-C", root / "owner.json", root / "complete", expected_dispatch_sha256=sha(data))
            self.assertEqual(result["status"], "completed")
            with np.load(root / "complete/predictions.npz", allow_pickle=False) as arrays:
                np.testing.assert_array_equal(arrays["per_head"], truth)
                np.testing.assert_array_equal(arrays["mean"], truth.mean(axis=0))
            cli = subprocess.run([sys.executable, str(ROOT / "cell_graph_reduce.py"),
                "--dispatch", str(root / "dispatch.json"), "--graph-id", "b0-C",
                "--owner-input", str(root / "owner.json"), "--output", str(root / "fresh-reducer"),
                "--expected-dispatch-sha256", sha(data)], capture_output=True, timeout=10)
            self.assertEqual(cli.returncode, 0, cli.stderr.decode())
            cli_receipt = strict_json((root / "fresh-reducer/receipt.json").read_bytes())
            self.assertTrue(cli_receipt["fresh_reducer_executable"])
            self.assertGreater(cli_receipt["reducer_process_cpu_ns_before_receipt"], cli_receipt["reducer_body_cpu_ns"])
            owner["workers"][0]["start_disposition"] = "reused"
            (root / "cached-owner.json").write_bytes(canonical(owner))
            result = reduce_graph(root / "dispatch.json", "b0-C", root / "cached-owner.json", root / "cached", expected_dispatch_sha256=sha(data))
            self.assertEqual(result["status"], "failed")
            owner["workers"][0]["start_disposition"] = "created"
            owner["workers"][0]["status"] = "failed"
            owner["workers"][0]["native_process_cpu_ns"] = 123
            (root / "failed-owner.json").write_bytes(canonical(owner))
            result = reduce_graph(root / "dispatch.json", "b0-C", root / "failed-owner.json", root / "failed", expected_dispatch_sha256=sha(data))
            self.assertEqual(result["status"], "failed")
            self.assertFalse((root / "failed/predictions.npz").exists())
            record = strict_json((root / "failed/receipt.json").read_bytes())
            self.assertEqual(record["nodes"][0]["native_process_cpu_ns"], 123)
            self.assertTrue(record["failed_process_costs_may_be_unknown"])
            self.assertEqual(record["known_completed_worker_cpu_ns"], 1)

    def test_missing_census_does_not_yield_success_only_statistics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graphs = [{"graph_id": f"b{block}-{arm}", "block": block, "arm": arm, "requests": []}
                for block, arms in enumerate(bench.BLOCK_ORDERS) for arm in arms]
            data = canonical({"graphs": graphs, "requests": 30, "protocol_sha256": "a" * 64, "graph_sha256": "b" * 64})
            (root / "dispatch.json").write_bytes(data)
            result = report(root / "dispatch.json", root, root / "report.json", expected_dispatch_sha256=sha(data))
            self.assertEqual(result["completed_comparable_graphs"], 0)
            actual = strict_json((root / "report.json").read_bytes())
            self.assertEqual(len(actual["rows"]), 18)
            self.assertNotIn("paired_descriptive_wall", actual)
            self.assertEqual(len(actual["separate_idempotency_recovery"]), 3)

    def test_cross_backend_tolerance_is_fixed_and_argmax_separate(self):
        value = np.full((6, 480, 4), .25)
        other = value.copy();other[:, :, 0] += 1e-13;other[:, :, 1] -= 1e-13
        check = compare_tensors(value, other)
        self.assertFalse(check["bitwise_equal"])
        self.assertTrue(check["within_predeclared_tolerance"])
        other = value.copy();other[:, :, 1] += 1e-13;other[:, :, 0] -= 1e-13
        self.assertFalse(compare_tensors(value, other)["all_head_argmax_equal"])
        other[0, 0, 0] += 1e-8
        self.assertFalse(compare_tensors(value, other)["within_predeclared_tolerance"])

    def test_idempotency_recovery_rejects_new_job_or_changed_original_arguments(self):
        original = {"request_id": "b0-A-s0", "host": "main", "idempotency_key": "fixed", "request_sha256": "a" * 64,
            "job_id": "job-original", "stdout_sha256": "b" * 64, "stdout_base64": "YQ==", "status": "completed",
            "exit_code": 0, "stdout_complete": True, "truncated": False, "original_start_arguments_sha256": "c" * 64, "start_disposition": "created"}
        replay = {**original, "repeated_start_arguments_sha256": "c" * 64, "start_disposition": "reused", "start_disposition_receipt_sha256": "e" * 64}
        self.assertFalse(validate_recovery(original, replay, original)["passed"])
        replay["job_id"] = "new-job-same-predictions"
        self.assertFalse(validate_recovery(original, replay, original)["passed"])
        replay = {**original, "repeated_start_arguments_sha256": "d" * 64, "start_disposition": "reused", "start_disposition_receipt_sha256": "e" * 64}
        self.assertFalse(validate_recovery(original, replay, original)["passed"])

    def test_recovery_requires_full_after_census_native_event_contract(self):
        request = {"request_id": "b0-A-s0", "host": "main"}
        events = [{"operation": operation, "request_id": request["request_id"], "host": "main", "status": "completed",
                   "started_ms": 100 + index, "finished_ms": 101 + index, "native_receipt_sha256": "a" * 64}
                  for index, operation in enumerate(("process_start", "process_read"))]
        replay = {"status": "completed", "started_ms": 100, "completed_ms": 102, "api_events": events}
        self.assertTrue(recovery_events_valid(replay, request, 99))
        replay["completed_ms"] = 60101
        self.assertFalse(recovery_events_valid(replay, request, 99))
        replay["completed_ms"] = 102;events[-1]["operation"] = "process_start"
        self.assertFalse(recovery_events_valid(replay, request, 99))
        self.assertFalse(validate_recovery({}, {}, request)["passed"])

    def test_serial_fallback_or_unattested_events_do_not_qualify(self):
        graph = {"graph_id": "b0-C", "arm": "C", "requests": [{"request_id": "s0", "host": "main"}, {"request_id": "s1", "host": "pocket4"}]}
        owner = {"schema": "hepta.fixed-cell-graph.owner.v1", "graph_id": "b0-C", "dispatch_sha256": "f" * 64,
            "no_cross_host_clock_subtraction": True, "no_serial_fallback": True, "started_ms": 1, "completed_ms": 4,
            "critical_path_ms": 3, "collect_path_ms": 2, "reducer_service_path_ms": 1, "events": [],
            "requested_submission": "serial", "concurrent_start_calls_observed": False}
        problems = owner_check(owner, graph, "f" * 64)
        self.assertTrue(any("concurrent" in problem for problem in problems))
        self.assertTrue(any("bounded full-read" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
