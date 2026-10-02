"""Linux Root-owned, fixed-input SciFact encoder; no credential or signing role.

Run with the protected system Python using -I -S. The physical probe makes no
grant/admission claim. Serving requires an actual Root-frozen peer/run tuple.
"""

import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys
import time

# -I -S excludes cwd, PYTHONPATH and user/site packages. Only this protected
# installed directory and the subsequently verified NumPy snapshot are added.
program_dir = Path(__file__).parent
for ancestor in (program_dir, *program_dir.parents):
    metadata = ancestor.lstat()
    if ancestor.resolve() != ancestor or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError("unprotected encoder program directory")
sys.path.insert(0, str(program_dir))
sys.dont_write_bytecode = True
helper = program_dir / "fixed_encoder_sources.py"
metadata = helper.lstat()
if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022 or metadata.st_nlink != 1:
    raise ValueError("unprotected encoder source module")
from fixed_encoder_sources import (
    decode_json,
    protected_path,
    root_role,
    source_bytes,
    tokenizer_digest,
    verify_inventory,
    verify_large_source,
)


def now_ms():
    return time.time_ns() // 1_000_000


def load_config(path, pin):
    root_role()
    payload = protected_path(path).read_bytes()
    if not 0 < len(payload) <= 2 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != pin:
        raise ValueError("encoder configuration pin/budget")
    config = decode_json(payload)
    required = {
        "schema",
        "socket_path",
        "backend_pid",
        "backend_uid",
        "backend_cgroup",
        "backend_start_time",
        "backend_unit_source",
        "model_directory",
        "model_sources",
        "gguf_source",
        "preprocessor_source",
        "numpy_directory",
        "numpy_sources",
        "program_sources",
        "runtime_sources",
        "pairs_source",
        "expires_at_ms",
        "timeout_ms",
        "max_requests",
        "principals",
    }
    if config["schema"] in ("hepta.fixed-nomic-encoder.v2", "hepta.fixed-nomic-encoder.v3"):
        required.add("resource_observer")
        if config["schema"] == "hepta.fixed-nomic-encoder.v3":
            required.add("public_development")
    elif config["schema"] != "hepta.fixed-nomic-encoder.v1":
        raise ValueError("encoder configuration schema")
    if set(config) != required:
        raise ValueError("encoder configuration fields")
    if not now_ms() < config["expires_at_ms"] <= now_ms() + 24 * 60 * 60 * 1000:
        raise ValueError("encoder configuration expired")
    if not 1 <= config["timeout_ms"] <= 120_000 or not 1 <= config["max_requests"] <= 4096:
        raise ValueError("encoder request budget")
    if config["backend_uid"] <= 0 or config["backend_pid"] <= 1:
        raise ValueError("backend physical identity")
    for item in config["runtime_sources"] + config["program_sources"]:
        verify_large_source(item, 128 * 1024 * 1024)
    program_paths = {item["path"] for item in config["program_sources"]}
    if str(Path(__file__)) not in program_paths or str(program_dir / "fixed_encoder_sources.py") not in program_paths:
        raise ValueError("encoder source closure")
    if config["schema"] in ("hepta.fixed-nomic-encoder.v2", "hepta.fixed-nomic-encoder.v3"):
        if str(program_dir / "fixed_encoder_resources.py") not in program_paths:
            raise ValueError("original resource reader outside protected source closure")
        if (
            config["schema"] == "hepta.fixed-nomic-encoder.v3"
            and str(program_dir / "fixed_encoder_development.py") not in program_paths
        ):
            raise ValueError("closed public measurement outside protected source closure")
    protected_path(config["model_directory"], directory=True)
    paths = sorted(str(item) for item in Path(config["model_directory"]).rglob("*") if not item.is_dir())
    if paths != sorted(item["path"] for item in config["model_sources"]) or len(paths) != 5:
        raise ValueError("fixed model closure")
    for item in config["model_sources"]:
        verify_large_source(item, 300 * 1024 * 1024)
    if config["gguf_source"] not in config["model_sources"]:
        raise ValueError("GGUF outside model closure")
    preprocessor = decode_json(source_bytes(config["preprocessor_source"], 16 * 1024))
    if config["preprocessor_source"]["sha256"] != "fa0d37d65471c4c08c9c4cd5d458660e46599ec7acdd42063dc52fddd0f7bc27":
        raise ValueError("original text normalization pin")
    with open(protected_path(config["gguf_source"]["path"]), "rb") as stream:
        if tokenizer_digest(stream) != preprocessor["tokenizer_sha256"]:
            raise ValueError("original tokenizer pin")
    if (
        preprocessor["version"],
        preprocessor["model"],
        preprocessor["source_dimensions"],
        preprocessor["num_gpu"],
        preprocessor["num_thread"],
        preprocessor["num_ctx"],
        preprocessor["truncate"],
        preprocessor["abstract_character_cap"],
        preprocessor["claim_prefix"],
        preprocessor["document_prefix"],
    ) != (
        1,
        "nomic-embed-text:latest",
        768,
        0,
        4,
        2048,
        True,
        6000,
        "search_query: ",
        "search_document: ",
    ):
        raise ValueError("unsupported original preprocessor")
    if preprocessor["weights_sha256"] != config["gguf_source"]["sha256"]:
        raise ValueError("preprocessor weights pin")
    runtime = next(item for item in config["runtime_sources"] if item["path"] == "/usr/local/bin/ollama")
    if runtime["sha256"] != preprocessor["runtime_binary_sha256"]:
        raise ValueError("original physical embedding runtime pin")
    verify_inventory(config["numpy_directory"], config["numpy_sources"])
    sys.path.insert(0, str(Path(config["numpy_directory"]).parent))
    import numpy

    if (
        numpy.__version__ != "1.26.4"
        or Path(numpy.__file__).resolve() != Path(config["numpy_directory"]) / "__init__.py"
    ):
        raise ValueError("fixed NumPy implementation")
    pairs = decode_json(source_bytes(config["pairs_source"], 4 * 1024 * 1024))
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 1024:
        raise ValueError("masked pair budget")
    by_id = {}
    for pair in pairs:
        if set(pair) != {
            "pair_id",
            "source_row_sha256",
            "claim_text",
            "title",
            "abstract_sentences",
        }:
            raise ValueError("masked pair fields")
        if pair["pair_id"] in by_id or not isinstance(pair["abstract_sentences"], list):
            raise ValueError("duplicate or invalid pair")
        if not all(isinstance(text, str) for text in [pair["claim_text"], pair["title"], *pair["abstract_sentences"]]):
            raise ValueError("masked pair text")
        if sum(len(text) for text in [pair["claim_text"], pair["title"], *pair["abstract_sentences"]]) > 100_000:
            raise ValueError("masked pair size")
        if len(bytes.fromhex(pair["source_row_sha256"])) != 32:
            raise ValueError("original pair identity")
        by_id[pair["pair_id"]] = pair
    backend_identity(config)
    return config, preprocessor, numpy, by_id


def process_identity(pid):
    root = Path("/proc") / str(pid)
    raw = (root / "stat").read_text()
    start = raw[raw.rfind(")") + 2 :].split()[19]
    fields = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines() if ":" in line)
    uids = [int(value) for value in fields["Uid"].split()]
    gids = [int(value) for value in fields["Gid"].split()]
    cgroups = (root / "cgroup").read_text().splitlines()
    if len(cgroups) != 1 or not cgroups[0].startswith("0::"):
        raise ValueError("unified cgroup required")
    return start, uids, gids, cgroups[0][3:]


def backend_identity(config):
    identity = process_identity(config["backend_pid"])
    if (
        identity[0] != config["backend_start_time"]
        or identity[1] != [config["backend_uid"]] * 4
        or identity[3] != config["backend_cgroup"]
    ):
        raise ValueError("backend UID/cgroup changed")
    # Capability-free Root cannot inspect another UID's /proc/PID/exe. Bind
    # the actual service manager's protected unit plus kernel lifetime/UID/
    # cgroup, rather than adding process-inspection capability to this role.
    unit = source_bytes(config["backend_unit_source"], 64 * 1024)
    if b'ExecStart="/usr/local/bin/ollama" "serve"\n' not in unit:
        raise ValueError("fixed service executable declaration")
    return identity


def encode(config, preprocessor, numpy, pair, pin):
    if now_ms() >= config["expires_at_ms"]:
        raise ValueError("encoder configuration expired")
    before = backend_identity(config)
    texts = [
        preprocessor["claim_prefix"] + pair["claim_text"],
        preprocessor["document_prefix"] + (pair["title"] + "\n" + " ".join(pair["abstract_sentences"]))[:6000],
    ]
    body = json.dumps(
        {
            "model": preprocessor["model"],
            "input": texts,
            "truncate": True,
            "options": {"num_gpu": 0, "num_thread": 4, "num_ctx": 2048},
            "keep_alive": "10m",
        },
        separators=(",", ":"),
    ).encode()
    started = time.monotonic_ns()
    # No proxy environment, redirects, caller URL, model, pull or HTTP methods.
    connection = http.client.HTTPConnection("127.0.0.1", 11435, timeout=config["timeout_ms"] / 1000)
    try:
        connection.request("POST", "/api/embed", body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = response.read(128 * 1024 + 1)
        if response.status != 200 or len(payload) > 128 * 1024:
            raise ValueError("bounded physical embedding failed")
        vectors = decode_json(payload)["embeddings"]
    finally:
        connection.close()
    if not isinstance(vectors, list) or len(vectors) != 2:
        raise ValueError("embedding batch shape")
    features = []
    for vector in vectors:
        array = numpy.asarray(vector, dtype=numpy.float64)
        if array.shape != (768,) or not numpy.isfinite(array).all():
            raise ValueError("physical embedding shape/finiteness")
        centered = (array - array.mean())[:256]
        norm = numpy.linalg.norm(centered)
        if not numpy.isfinite(norm) or norm <= 0:
            raise ValueError("zero/nonfinite physical embedding")
        features.extend(numpy.rint((centered / norm) * (1 << 24)).astype(numpy.int64).tolist())
    if backend_identity(config) != before or now_ms() >= config["expires_at_ms"]:
        raise ValueError("physical backend or expiry changed")
    return {
        "schema": "hepta.fixed-nomic-encoded-pair.v1",
        "encoder_config_sha256": pin,
        "normalization_sha256": config["preprocessor_source"]["sha256"],
        "weights_sha256": config["gguf_source"]["sha256"],
        "tokenizer_sha256": preprocessor["tokenizer_sha256"],
        "pair_id": pair["pair_id"],
        "source_row_sha256": pair["source_row_sha256"],
        "physical_elapsed_micros": (time.monotonic_ns() - started) // 1000,
        "features_q24": features,
    }


def authorize(connection, config, request):
    if config["schema"] in ("hepta.fixed-nomic-encoder.v2", "hepta.fixed-nomic-encoder.v3"):
        return authorize_current(connection, config, request)
    fields = {
        "pair_id",
        "source_row_sha256",
        "body_digest",
        "objective_digest",
        "generation",
        "run_id",
        "grant_id",
        "grant_epoch",
        "grant_generation",
        "grant_expires_at_ms",
    }
    if set(request) != fields:
        raise ValueError("fixed request fields")
    pid, uid, gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    identity = process_identity(pid)
    for principal in config["principals"]:
        if set(principal) != fields - {"pair_id", "source_row_sha256"} | {
            "agent_id",
            "uid",
            "gid",
            "cgroup",
        }:
            raise ValueError("actual principal fields")
        if (
            principal["uid"] == uid
            and principal["gid"] == gid
            and identity[1] == [uid] * 4
            and identity[2] == [gid] * 4
        ):
            if identity[3] == principal["cgroup"] and all(
                request[key] == principal[key] for key in fields - {"pair_id", "source_row_sha256"}
            ):
                if now_ms() < request["grant_expires_at_ms"]:
                    return pid, identity
    raise ValueError("kernel peer/current grant/run tuple denied")


def authorize_current(connection, config, request):
    from fixed_encoder_resources import observe

    fields = {
        "pair_id",
        "source_row_sha256",
        "body_digest",
        "objective_digest",
        "model_generation",
        "run_id",
        "ndu_digest",
    }
    if set(request) != fields or len(bytes.fromhex(request["ndu_digest"])) != 32 or request["ndu_digest"] == "0" * 64:
        raise ValueError("actual canonical neural stage fields")
    pid, uid, gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    identity = process_identity(pid)
    for principal in config["principals"]:
        expected = fields - {"ndu_digest"} | {
            "agent_id",
            "uid",
            "gid",
            "cgroup",
            "fleet_manifest_digest",
            "program_source",
            "body_sources",
        }
        goal_mode = (
            config["schema"] == "hepta.fixed-nomic-encoder.v3"
            and principal.get("goal_scope_mode") == "ActualCompiledGoalScopeV3"
        )
        if goal_mode:
            expected = expected - {"objective_digest", "run_id"} | {"goal_scope_mode"}
        if set(principal) != expected:
            raise ValueError("current principal configuration fields")
        if (
            principal["uid"] != uid
            or principal["gid"] != gid
            or identity[1] != [uid] * 4
            or identity[2] != [gid] * 4
            or identity[3] != principal["cgroup"]
        ):
            continue
        fixed = fields - {"ndu_digest"}
        if goal_mode:
            fixed -= {"objective_digest", "run_id"}
            if (
                not isinstance(request["objective_digest"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", request["objective_digest"])
                or request["objective_digest"] == "0" * 64
                or not isinstance(request["ndu_digest"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", request["ndu_digest"])
                or not isinstance(request["run_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request["run_id"])
            ):
                raise ValueError("actual compiled Goal/run stage identity")
        if not all(request[key] == principal[key] for key in fixed):
            continue
        verify_large_source(principal["program_source"], 512 * 1024 * 1024)
        body_records = [decode_json(source_bytes(item, 64 * 1024)) for item in principal["body_sources"]]
        compiled = [value for value in body_records if isinstance(value, dict) and "runtime_body_digest" in value]
        if (
            len(compiled) != 1
            or compiled[0]["runtime_body_digest"] != principal["body_digest"]
            or compiled[0]["agent_id"] != principal["agent_id"]
            or compiled[0]["body_generation"] != principal["model_generation"]
        ):
            raise ValueError("Root body closure does not bind this principal/model")
        resource = observe(config, principal, pid, identity)
        if process_identity(pid) != identity:
            raise ValueError("peer changed during original resource observation")
        return pid, (identity, resource)
    raise ValueError("actual peer/body/goal/current allocation denied")


def serve(config, preprocessor, numpy, pairs, pin):
    development = None
    if config["schema"] == "hepta.fixed-nomic-encoder.v3":
        from fixed_encoder_development import DevelopmentMeasurements

        development = DevelopmentMeasurements(config, pairs)
    path = Path(config["socket_path"])
    parent = protected_path(path.parent, directory=True)
    if parent.stat().st_gid != 975 or parent.stat().st_mode & 0o007 or path.exists():
        raise ValueError("exclusive workload transport boundary")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        if path.stat().st_uid != 0 or path.stat().st_gid != 975:
            raise ValueError("transport must inherit the protected workload group")
        os.chmod(path, 0o660)
        listener.listen(4)
        listener.settimeout(1)
        remaining = config["max_requests"]
        while now_ms() < config["expires_at_ms"] and remaining:
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            remaining -= 1
            with connection:
                connection.settimeout(config["timeout_ms"] / 1000)
                try:
                    payload = bytearray()
                    while b"\n" not in payload:
                        block = connection.recv(4096)
                        if not block or len(payload) + len(block) > 16 * 1024:
                            raise ValueError("request frame budget")
                        payload.extend(block)
                    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
                        raise ValueError("single request frame")
                    request = decode_json(payload)
                    if not isinstance(request, dict):
                        raise ValueError("single request object required")
                    if development is not None and request.get("purpose") == "PublicDevelopmentMeasurementOnlyV1":
                        result = development.measure(connection, request, preprocessor, numpy, pin, encode)
                        response = json.dumps(result, separators=(",", ":")).encode() + b"\n"
                        if len(response) > 64 * 1024:
                            raise ValueError("closed public response budget")
                        connection.sendall(response)
                        continue
                    pid, before = authorize(connection, config, request)
                    pair = pairs[request["pair_id"]]
                    if pair["source_row_sha256"] != request["source_row_sha256"]:
                        raise ValueError("original source identity changed")
                    result = encode(config, preprocessor, numpy, pair, pin)
                    if authorize(connection, config, request) != (pid, before):
                        raise ValueError("peer changed during physical encoding")
                    result["run_tuple"] = {
                        key: request[key] for key in request if key not in ("pair_id", "source_row_sha256")
                    }
                    connection.sendall(json.dumps(result, separators=(",", ":")).encode() + b"\n")
                except (ValueError, KeyError, OSError, TypeError):
                    connection.sendall(b'{"error":"fixed physical encoder denied"}\n')
    finally:
        listener.close()
        if path.exists() and stat.S_ISSOCK(path.lstat().st_mode):
            path.unlink()


def main():
    if len(sys.argv) not in (4, 5):
        raise ValueError("purpose configuration pin [public pair ID]")
    purpose, path, pin = sys.argv[1:4]
    config, preprocessor, numpy, pairs = load_config(path, pin)
    if purpose == "probe-physical-encoding" and len(sys.argv) == 5:
        result = encode(config, preprocessor, numpy, pairs[sys.argv[4]], pin)
        result["qualification_scope"] = "physical encoding only; no grant, Neuron execution, selection or activation"
        print(json.dumps(result, separators=(",", ":")))
    elif purpose == "serve-fixed-pairs" and len(sys.argv) == 4:
        serve(config, preprocessor, numpy, pairs, pin)
    else:
        raise ValueError("unsupported encoder purpose")


if __name__ == "__main__":
    main()
