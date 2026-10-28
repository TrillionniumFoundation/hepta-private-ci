"""Independent byte, address, program and process checks for skill maintenance.

Only NumPy and the standard library are used. Saved tensors are decoded as
data; no model, trainer, target generator or experiment module is imported.
"""

import hashlib
import json
import math
from pathlib import Path
import sqlite3
import stat
import statistics
import zipfile

import numpy as np


SEEDS = (731, 732, 733)
PROBES = ((0, (5, 3, 11)), (7, (9, 2, 15)), (17, (2, 7, 13)), (5, (11, 1, 8)))
OPCODES = ("keep", "reserve_gap", "pack", "cap", "add_reserve", "halve", "stop")
GROUPS = ("active", "retention", "changed", "revoked")
ARMS = ("parameter", "exact_sql")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate JSON key in " + str(path))
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("Nonfinite JSON value: " + value)

    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs, parse_constant=invalid)


def identity(path):
    if not stat.S_ISREG(Path(path).lstat().st_mode):
        raise ValueError("Regular evidence file required: " + str(path))
    digest, length = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
            length += len(block)
    return {"bytes": length, "sha256": digest.hexdigest()}


def tree_identity(root):
    rows = []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode):
            rows.append((str(path.relative_to(root)), identity(path)))
        elif not stat.S_ISDIR(mode):
            raise ValueError("Nonregular run evidence: " + str(path))
    return {"sha256": sha(canonical(rows)), "files": len(rows),
            "bytes": sum(row[1]["bytes"] for row in rows)}


class EvidencePaths:
    """Rebase explicitly supplied namespaces without rewriting original bytes."""

    def __init__(self, run, checkout, initial, protocol, bundle=None):
        self.run = run.resolve(strict=True)
        self.checkout = checkout.resolve(strict=True)
        self.initial = initial.resolve(strict=True)
        self.bundle = bundle.resolve(strict=True) if bundle else None
        self.resolutions = {}
        if self.bundle:
            declaration = load(self.bundle / "PATHS.json")
            required = {"repo_root", "adapter_root", "output_root", "run_root", "initial_study", "audit_rule"}
            if set(declaration) != required:
                raise ValueError("Unexpected CI path declaration")
            raw_repo = Path(declaration["repo_root"])
            if Path(declaration["adapter_root"]) != raw_repo / "qualification/memory-cell-adapters":
                raise ValueError("CI adapter root is inconsistent")
            if declaration["initial_study"] != protocol["initial_study"]:
                raise ValueError("CI initial-study namespace differs from the protocol")
            raw_output, raw_run = Path(declaration["output_root"]), Path(declaration["run_root"])
            if not raw_run.is_relative_to(raw_output) or not self.run.is_relative_to(self.bundle):
                raise ValueError("CI run must be contained in its declared bundle")
            if self.run.relative_to(self.bundle) != raw_run.relative_to(raw_output):
                raise ValueError("CI run relative path changed during restoration")
            rules = [(raw_run, self.run), (raw_output, self.bundle), (raw_repo, self.checkout)]
            self.declaration_identity = identity(self.bundle / "PATHS.json")
        else:
            rules = [(self.run, self.run), (self.checkout, self.checkout)]
            self.declaration_identity = None
        rules.append((Path(protocol["initial_study"]), self.initial))
        for origin, _ in rules:
            if not origin.is_absolute() or ".." in origin.parts or origin == Path("/"):
                raise ValueError("Absolute bounded original namespace required")
        if len({str(origin) for origin, _ in rules}) != len(rules):
            raise ValueError("Duplicate evidence path namespace")
        self.rules = sorted(rules, key=lambda row: len(row[0].parts), reverse=True)

    def resolve(self, original):
        path = Path(original)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("Absolute bounded evidence path required")
        for origin, destination in self.rules:
            if path.is_relative_to(origin):
                physical = (destination / path.relative_to(origin)).resolve(strict=True)
                if not physical.is_relative_to(destination):
                    raise ValueError("Mapped evidence escapes its explicit destination")
                self.resolutions[str(path)] = str(physical)
                return physical
        raise ValueError("No declared mapping for " + str(path))

    def report(self):
        return {"declaration_identity": self.declaration_identity,
                "rules": [{"original_prefix": str(a), "local_prefix": str(b)} for a, b in self.rules],
                "resolved_paths": len(self.resolutions),
                "resolution_sha256": sha(canonical(sorted(self.resolutions.items()))),
                "raw_evidence_rewritten": False}


def sql_state(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute(
            "SELECT idx,identity,version,active,payload FROM sources WHERE kind='skill' ORDER BY idx").fetchall()
        return [{"index": row[0], "source_id": row[1], "version": row[2],
                 "active": bool(row[3]), "value": json.loads(row[4])} for row in rows]
    finally:
        connection.close()


def unchanged_owner_state(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        return {"other_sources": connection.execute("SELECT * FROM sources WHERE kind!='skill' ORDER BY kind,idx").fetchall(),
                "events": connection.execute("SELECT * FROM events ORDER BY entity,sequence").fetchall(),
                "exceptions": connection.execute("SELECT * FROM exceptions ORDER BY entity").fetchall()}
    finally:
        connection.close()


def snapshot_digest(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        sources = connection.execute("SELECT kind,idx,identity,version,active FROM sources ORDER BY kind,idx").fetchall()
        events = connection.execute("SELECT entity,sequence,identity FROM events ORDER BY entity,sequence").fetchall()
        exceptions = connection.execute("SELECT entity,identity FROM exceptions ORDER BY entity").fetchall()
        return sha(canonical({"sources": sha(canonical(sources)), "events": events, "exceptions": exceptions}))
    finally:
        connection.close()


def execute(program, value, policy, limit=4):
    """Independent interpreter for the public seven-opcode bounded contract."""
    trace = []
    for position, opcode in enumerate(program):
        if position >= limit:
            return {"status": "budget_stop", "value": None, "trace": trace}
        if type(opcode) is not int or opcode not in range(7):
            return {"status": "invalid_program", "value": None, "trace": trace}
        before = value
        if opcode == 1:
            value = max(0, policy[0] - before)
        elif opcode == 2:
            value = before * policy[1]
        elif opcode == 3:
            value = min(before, policy[2])
        elif opcode == 4:
            value = before + policy[0]
        elif opcode == 5:
            value = before // 2
        trace.append({"op": OPCODES[opcode], "before": before, "after": value})
        if opcode == 6:
            return {"status": "completed", "value": value, "trace": trace}
    return {"status": "missing_stop", "value": None, "trace": trace}


def next_program(seed, stage, workflow, previous):
    previous_values = [execute(previous, value, policy)["value"] for value, policy in PROBES]
    start = (37 * stage + 17 * workflow + seed) % 216
    for offset in range(216):
        code = (start + offset) % 216
        candidate = [code // 36, (code // 6) % 6, code % 6, 6]
        if candidate != previous and any(execute(candidate, value, policy)["value"] != old
                                         for (value, policy), old in zip(PROBES, previous_values, strict=True)):
            return candidate
    raise ValueError("No behavioral program change exists within the registered search")


def feature_arrays(path):
    with zipfile.ZipFile(path) as archive:
        if sorted(archive.namelist()) != ["semantic.npy", "skill.npy"] or any(
                entry.file_size > 8 * 384 * 8 + 4096 for entry in archive.infolist()):
            raise ValueError("Unexpected canonical feature archive")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name].astype("<f4", copy=True) for name in ("semantic", "skill")}
    if any(value.shape != (8, 384) or not np.isfinite(value).all() for value in arrays.values()):
        raise ValueError("Invalid canonical feature values")
    return arrays, {**identity(path), "keys_loaded": sorted(arrays),
                    "f32_sha256": {name: sha(value.tobytes()) for name, value in arrays.items()}}


def checkpoint(path, encoder_sha, check, label):
    manifest = load(path / "manifest.json")
    config = manifest["config"]
    check("checkpoint_manifest_fields:" + label, set(manifest) == {
        "schema", "config", "base_encoder_sha", "base_operator", "dtype", "parameter_sha256",
        "head_frozen", "head_trainable", "source_ids", "parents", "training_history", "tensors"}
        and set(config) == {"cell_id", "rank", "input_dim", "outputs", "seed"})
    check("checkpoint_architecture:" + label,
          manifest["schema"] == "memory-adapter.checkpoint.v1" and manifest["dtype"] == "float32"
          and manifest["base_encoder_sha"] == encoder_sha and manifest["base_operator"] == "identity"
          and config["rank"] == 4 and config["input_dim"] == 384
          and config["outputs"] == [{"name": f"op{i}", "kind": "multiclass", "size": 7, "weight": 1.0} for i in range(4)])
    shapes = {"A": [4, 384], "B": [384, 4], "head.weight": [28, 384], "head.bias": [28]}
    if set(manifest["tensors"]) != set(shapes):
        raise ValueError("Unexpected tensor inventory: " + label)
    digest, payload, arrays = hashlib.sha256(), 0, {}
    for name, spec in sorted(manifest["tensors"].items()):
        if spec["shape"] != shapes[name]:
            raise ValueError("Unexpected tensor shape: " + label)
        pieces = []
        for number, part in enumerate(spec["parts"]):
            if part["file"] != f"{name}.{number:04d}.npz":
                raise ValueError("Unexpected tensor part name")
            file = path / part["file"]
            check("tensor_identity:" + label + ":" + part["file"],
                  identity(file) == {key: part[key] for key in ("bytes", "sha256")} and part["bytes"] <= 512000)
            with zipfile.ZipFile(file) as archive:
                if archive.namelist() != ["values.npy"] or archive.infolist()[0].file_size > 404096:
                    raise ValueError("Unexpected tensor ZIP contents")
            with np.load(file, allow_pickle=False) as archive:
                values = archive["values"].copy()
            if values.ndim != 1 or values.dtype != np.dtype("<f4") or not np.isfinite(values).all():
                raise ValueError("Invalid saved float32 parameter values")
            pieces.append(values)
        values = np.concatenate(pieces)
        if values.size != math.prod(shapes[name]):
            raise ValueError("Tensor payload element count mismatch")
        digest.update(canonical([name, shapes[name], "float32"]))
        digest.update(values.tobytes())
        payload += values.nbytes
        arrays[name] = values.reshape(shapes[name])
    check("independent_parameter_digest:" + label, digest.hexdigest() == manifest["parameter_sha256"])
    expected_files = {"manifest.json"} | {part["file"] for spec in manifest["tensors"].values() for part in spec["parts"]}
    check("checkpoint_file_inventory:" + label, {file.name for file in path.iterdir()} == expected_files)
    check("skill_parameter_payload:" + label, payload == 13852 * 4)
    check("checkpoint_parameter_count:" + label,
          sum(value.size for value in arrays.values()) == 13852
          and manifest["head_trainable"] and not manifest["head_frozen"])
    return manifest, arrays


def decoded_programs(arrays, features):
    """Independent float32 replay of the saved affine coefficients, no Torch.

    This is explicitly reported as arithmetic replay, not an assertion that
    the audit performed no prediction. No experiment model or trainer is used.
    """
    programs, margins = [], []
    for row in features:
        value = row[None, :].astype("<f4", copy=False)
        residual = value + (value @ arrays["A"].T) @ arrays["B"].T
        logits = (residual @ arrays["head.weight"].T + arrays["head.bias"]).reshape(4, 7)
        if logits.dtype != np.dtype("<f4") or not np.isfinite(logits).all():
            raise ValueError("Nonfinite or wrong-precision independent affine replay")
        programs.append(logits.argmax(axis=1).tolist())
        top = np.sort(logits, axis=1)[:, -2:]
        margins.append([float(value) for value in top[:, 1] - top[:, 0]])
    return {"programs": programs, "top_two_logit_margins": margins,
            "algorithm": "per-row float32 x + (x @ A.T) @ B.T; affine head; four argmax(7)",
            "minimum_top_two_logit_margin": min(value for row in margins for value in row)}


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "sum": 0}
    return {"count": len(ordered), "min": ordered[0], "median": statistics.median(ordered),
            "p95_nearest_rank": ordered[math.ceil(len(ordered) * 0.95) - 1],
            "max": ordered[-1], "sum": sum(ordered)}


def file_bytes(path):
    return sum(identity(file)["bytes"] for file in path.rglob("*") if file.is_file())


def groups():
    return {name: {"correct": 0, "count": 0} for name in GROUPS}


def score_row(output, source, changed, correct):
    names = ["active" if source["active"] else "revoked"]
    if source["active"]:
        names.append("changed" if source["index"] in changed else "retention")
    for name in names:
        output[name]["count"] += 1
        output[name]["correct"] += int(correct)


class ProcessAudit:
    """Bind each saved response to the actual input bytes and completed process."""

    def __init__(self, run, check):
        self.run, self.check, self.records = run, check, []

    def read(self, stem, script):
        label = str(stem.relative_to(self.run))
        process = load(stem.with_suffix(".process.json"))
        request = load(stem.with_suffix(".request.json"))
        response = load(stem.with_suffix(".stdout"))
        self.check("process_completion:" + label, process["script"] == script and process["exit_code"] == 0
                   and process["passed"] and not process["timed_out"] and "error" not in response)
        self.check("process_timing:" + label, process["wall_ns"] == process["exited_ns"] - process["started_ns"]
                   and process["wall_ns"] > 0 and process["cpu_seconds"] >= 0)
        for name, suffix in (("request", ".request.json"), ("stdout", ".stdout"), ("stderr", ".stderr")):
            self.check("process_stream:" + label + ":" + name, identity(stem.with_suffix(suffix)) == process[name])
        self.check("response_process_binding:" + label,
                   response["pid"] == process["pid"] and response["request_sha256"] == process["request"]["sha256"])
        self.check("body_inside_process_cost:" + label,
                   0 < response["process_body_wall_ns"] <= process["wall_ns"]
                   and 0 <= response["process_body_cpu_ns"] <= process["cpu_seconds"] * 1e9 + 1000000
                   and response["peak_rss_kib"] > 0)
        self.records.append(process)
        return process, request, response


def stop_check(stop, check, label):
    check("owner_stop:" + label, stop["passed"]
          and stop["owner_stop_probe"]["status"] == stop["memory_stop_probe"]["status"] == "owner_stopped"
          and stop["before_reads"] == stop["after_reads"]
          and stop["before_model_reads"] == stop["after_model_reads"])


def preflight_check(probe, expected_status, indexes, state, previous, check, label):
    check("preflight_contract:" + label,
          probe["passed"] and probe["kind"] == "skill" and probe["expected_status"] == expected_status
          and probe["parameter_sha256"] == previous["parameter_sha256"]
          and probe["target_blind_manager_claimed"] is False)
    check("preflight_inventory:" + label, [row["workflow"] for row in probe["rows"]] == indexes)
    check("preflight_no_parameter_or_payload_access:" + label,
          all(value == 0 for value in probe["model_reads"].values())
          and probe["sql_audit"] == {"source_payload_column_authorizations": 0, "denied_source_payload_reads": 0}
          and probe["reads"] == {"source_status": len(indexes), "explicit_values": 0,
                                "events": 0, "exceptions": 0, "model": 0})
    for row in probe["rows"]:
        source = state[row["workflow"]]
        check("preflight_refusal:" + label + ":" + str(row["workflow"]),
              row["result"]["status"] == expected_status and row["result"]["value"] is None
              and row["result"]["sources"] == ([source["source_id"]] if expected_status == "stale_source" else [])
              and row["executions"] == []
              and row["reads"] == {"source_status": 1, "explicit_values": 0, "events": 0, "exceptions": 0, "model": 0}
              and all(value == 0 for value in row["model_reads"].values()))
    stop_check(probe["stop"], check, label)


def read_check(stem, checkpoint_path, manifest, database, state, changed, context):
    paths, check, processes = context["paths"], context["check"], context["processes"]
    label = str(stem.relative_to(paths.run))
    process, request, response = processes.read(stem, "owner_read.py")
    check("reader_request_fields:" + label,
          set(request) == {"checkpoint", "encoder_sha", "database", "canonical_features_path", "protocol_sha256"})
    check("reader_request_identity:" + label,
          paths.resolve(request["checkpoint"]) == checkpoint_path and paths.resolve(request["database"]) == database
          and request["encoder_sha"] == context["encoder_sha"]
          and paths.resolve(request["canonical_features_path"]) == paths.run / "inputs/canonical.npz"
          and request["protocol_sha256"] == response["protocol_sha256"] == context["protocol_sha"])
    check("reader_response_boundary:" + label,
          response["schema"] == "hepta.memory.adapter-skill-longrun-read.v1" and response["kind"] == "skill"
          and response["gradient_steps"] == 0 and not response["training_modules_loaded"]
          and not response["target_module_import_audit"] and not response["native_runtime_executed"]
          and not response["held_inputs_opened"])
    check("reader_checkpoint_identity:" + label,
          response["parameter_sha256"] == manifest["parameter_sha256"]
          and response["manifest"] == identity(checkpoint_path / "manifest.json")
          and response["source_ids"] == manifest["source_ids"]
          and response["canonical_features"] == context["feature_identity"])
    check("reader_arms:" + label, [arm["arm"] for arm in response["arms"]] == list(ARMS))
    cut = snapshot_digest(database)
    metadata = [[r["index"], r["source_id"], r["version"], int(r["active"])] for r in state]
    quality, execution_quality = {}, {}
    for arm in response["arms"]:
        name, rows = arm["arm"], arm["rows"]
        check("reader_source_snapshot:" + label + ":" + name,
              arm["owner_snapshot_sha256"] == cut and arm["source_metadata"] == metadata)
        if [row["workflow"] for row in rows] != list(range(8)):
            raise ValueError("Reader workflow inventory differs from registered addresses")
        quality[name], execution_quality[name] = groups(), groups()
        read_sum = {"source_status": 0, "explicit_values": 0, "events": 0, "exceptions": 0, "model": 0}
        for row, source in zip(rows, state, strict=True):
            row_label = label + ":" + name + ":" + str(source["index"])
            active, actual = source["active"], row["result"]
            expected_reads = {"source_status": 1, "explicit_values": int(active and name == "exact_sql"),
                              "events": 0, "exceptions": 0, "model": int(active and name == "parameter")}
            check("reader_access:" + row_label, row["reads"] == expected_reads
                  and row["model_reads"]["calls"] == row["model_reads"]["forward_rows"] == expected_reads["model"]
                  and actual["sources"] == ([source["source_id"]] if active else []))
            if not expected_reads["model"]:
                check("no_forward_on_sql_or_refusal:" + row_label, all(v == 0 for v in row["model_reads"].values()))
            for key, count in row["reads"].items():
                read_sum[key] += count
            program_okay = actual["status"] == ("read" if active else "revoked")
            program_okay &= actual["value"] == (source["value"] if active else None)
            if actual["status"] == "read":
                program = actual["value"]
                check("constrained_skill_output:" + row_label,
                      isinstance(program, list) and len(program) == 4
                      and all(type(op) is int and 0 <= op < 7 for op in program))
                if name == "parameter":
                    check("independent_float32_decoded_program:" + row_label,
                          program == context["decoded"][str(checkpoint_path)]["programs"][source["index"]])
                predicted = [{"input": value, "policy": list(policy), "max_steps": 4,
                              "result": execute(program, value, policy)} for value, policy in PROBES]
            else:
                predicted = []
            check("predicted_program_execution:" + row_label, row["executions"] == predicted)
            expected = [{"input": value, "policy": list(policy), "max_steps": 4,
                         "result": execute(source["value"], value, policy)} for value, policy in PROBES] if active else []
            execution_okay = actual["status"] == ("read" if active else "revoked") and row["executions"] == expected
            score_row(quality[name], source, changed, program_okay)
            score_row(execution_quality[name], source, changed, execution_okay)
        check("reader_access_totals:" + label + ":" + name, arm["reads"] == read_sum)
        if name == "parameter":
            check("parameter_source_payload_denied:" + label,
                  arm["sql_audit"] == {"source_payload_column_authorizations": 0, "denied_source_payload_reads": 0})
        stop_check(arm["stop"], check, label + ":" + name)
    check("reader_total_model_calls:" + label,
          response["model_reads"]["calls"] == response["model_reads"]["forward_rows"] == sum(r["active"] for r in state))
    return process, response, quality, execution_quality
