"""Strict label-free fresh-process inference and observed Python file reads."""

import builtins
from contextlib import contextmanager
import io
import json
from pathlib import Path, PurePosixPath
import time

from .contracts import canonical, file_identity, sha256
from .graph_assets import DOMAINS
from .graph_runtime import GraphRuntime, PARAMETER_ARMS, address_for
from .joint_binding import immutable_path, verify_freeze
from .router import Router, parameter_digest


PROJECT = Path(__file__).resolve().parents[1]
INFERENCE_SOURCES = (
    "graph_reader.py",
    "v5/__init__.py",
    "v5/contracts.py",
    "v5/config.py",
    "v5/artifacts.py",
    "v5/features.py",
    "v5/router.py",
    "v5/graph_assets.py",
    "v5/graph_runtime.py",
    "v5/graph_process.py",
    "v5/joint_io.py",
    "v5/joint_binding.py",
    *(
        "legacy_v3/" + name
        for name in (
            "__init__.py",
            "factor_cell.py",
            "numeric_graph.py",
            "learned_graph.py",
            "semantic_router.py",
            "codec.py",
            "codec_reader.py",
        )
    ),
)


def source_binding(freeze_file, expected_sha256, *, smoke_only):
    actual = {name: file_identity(PROJECT / name) for name in INFERENCE_SOURCES}
    if smoke_only:
        if freeze_file is not None or expected_sha256 is not None:
            raise ValueError("smoke mode must not claim a formal freeze")
        return {"frozen": False, "source_files": actual}
    path = immutable_path(freeze_file)
    if path != PROJECT / "FREEZE.json" or sha256(path.read_bytes()) != expected_sha256:
        raise ValueError("fresh reader freeze binding differs")
    frozen, identity = verify_freeze(path)
    if identity["sha256"] != expected_sha256:
        raise ValueError("fresh reader source freeze changed during validation")
    for name, value in actual.items():
        if frozen["source_files"].get(name) != value:
            raise ValueError("fresh executed source differs from freeze: " + name)
    return {
        "frozen": True,
        "source_commit": frozen["source_commit"],
        "freeze_sha256": expected_sha256,
        "source_files": actual,
        "complete_source_inventory_validated": True,
        "source_hash_validation_reads_source_bytes": True,
    }


@contextmanager
def observed_opens(allowed):
    allowed = {Path(path).resolve() for path in allowed}
    seen = {}
    original_builtin, original_io = builtins.open, io.open

    def wrap(original):
        def checked(file, mode="r", *args, **kwargs):
            if isinstance(file, int):
                return original(file, mode, *args, **kwargs)
            path = Path(file).resolve()
            if any(flag in mode for flag in "wax+") or path not in allowed:
                raise PermissionError(
                    "inference Python open outside declared immutable state: "
                    + str(path)
                )
            seen[str(path)] = seen.get(str(path), 0) + 1
            return original(file, mode, *args, **kwargs)

        return checked

    builtins.open, io.open = wrap(original_builtin), wrap(original_io)
    try:
        yield seen
    finally:
        builtins.open, io.open = original_builtin, original_io


def allowed_state_files(request):
    domain, mode = request["domain"], request["mode"]
    assets = immutable_path(request["assets_directory"])
    router = immutable_path(request["router_directory"])
    manifest_raw = (router / "manifest.json").read_bytes()
    if sha256(manifest_raw) != request["router_manifest_sha256"]:
        raise ValueError("router manifest differs before opening payload parts")
    manifest = json.loads(manifest_raw)
    names = list(manifest["files"])
    if not names or any(
        PurePosixPath(name).name != name or name in {".", ".."} for name in names
    ):
        raise ValueError("router payload parts escape the selected state")
    paths = [
        assets / "ASSETS.json",
        *(router / name for name in ("manifest.json", *names)),
    ]
    if mode == "parameter":
        paths += [
            assets / f"numeric-memories/{domain}/primary" / name
            for name in ("addresses.json", "memory.factor")
        ]
        paths += [
            assets / "layout/model" / name for name in ("manifest.json", "weights.bin")
        ]
    else:
        paths += [
            assets / f"numeric-memories/{domain}/codecs" / name
            for name in ("addresses.json", "strong-exact.archive")
        ]
    for path in paths:
        cursor = path
        while cursor != cursor.parent:
            if cursor.is_symlink():
                raise ValueError("linked serving state")
            cursor = cursor.parent
    return paths


def execute_request(request):
    expected = {
        "schema",
        "domain",
        "mode",
        "seed",
        "requests",
        "router_directory",
        "router_manifest_sha256",
        "assets_directory",
        "assets_binding_sha256",
        "freeze_file",
        "freeze_sha256",
        "smoke_only",
    }
    if (
        not isinstance(request, dict)
        or set(request) != expected
        or request["schema"] != "hepta.memory.v5.graph-read-request.v1"
    ):
        raise ValueError("fresh process request schema forbids grader fields")
    if (
        request["domain"] not in DOMAINS
        or request["mode"] not in {"parameter", "strong"}
        or type(request["smoke_only"]) is not bool
    ):
        raise ValueError("fresh process mode/domain differs")
    if (
        not isinstance(request["requests"], list)
        or not 1 <= len(request["requests"]) <= 4096
    ):
        raise ValueError("invalid bounded request batch")
    for row in request["requests"]:
        address_for(row, request["domain"])
    sources = source_binding(
        request["freeze_file"],
        request["freeze_sha256"],
        smoke_only=request["smoke_only"],
    )
    paths = allowed_state_files(request)
    started = time.perf_counter()
    with observed_opens(paths) as opens:
        before_files = {str(path): file_identity(path) for path in paths}
        router = Router.load(
            request["router_directory"],
            expected_manifest_sha256=request["router_manifest_sha256"],
        )
        router_before = parameter_digest(router)
        runtime = GraphRuntime(
            request["assets_directory"],
            request["domain"],
            request["seed"],
            mode=request["mode"],
            expected_assets_sha256=request["assets_binding_sha256"],
        )
        decisions = router.decisions(request["requests"])
        arms = PARAMETER_ARMS if request["mode"] == "parameter" else ("strong_planner",)
        outputs = []
        for index, (row, decision) in enumerate(
            zip(request["requests"], decisions, strict=True)
        ):
            outputs.append(
                {
                    "index": index,
                    "request_sha256": sha256(canonical(row)),
                    "decision": decision,
                    "arms": {
                        arm: runtime.execute(row, decision["accepted_intent"], arm)
                        for arm in arms
                    },
                }
            )
        state = runtime.receipt()
        router_after = parameter_digest(router)
        after_files = {str(path): file_identity(path) for path in paths}
        if before_files != after_files or router_before != router_after:
            raise ValueError("inference mutated serving state")
    if set(opens) != {str(path) for path in paths}:
        raise ValueError(
            "observed Python file reads differ from loaded state inventory"
        )
    return {
        "schema": "hepta.memory.v5.graph-read-output.v1",
        "request_sha256": sha256(canonical(request)),
        "domain": request["domain"],
        "mode": request["mode"],
        "seed": request["seed"],
        "rows": outputs,
        "source_binding": sources,
        "state": state,
        "router_parameter_before": router_before,
        "router_parameter_after": router_after,
        "serving_file_identities": before_files,
        "observed_python_read_opens": opens,
        "serving_state_bytes": sum(info["bytes"] for info in before_files.values()),
        "router_numeric_parameter_bytes": router.numeric_parameter_bytes(),
        "router_decision_count": len(decisions),
        "actual_hop_calls": sum(
            value["execution"]["calls"]
            for row in outputs
            for value in row["arms"].values()
        ),
        "wall_seconds": time.perf_counter() - started,
        "smoke_only": request["smoke_only"],
        "gold_or_target_fields_in_serving_requests": False,
        "training_examples_supplied_to_router": False,
        "training_corpus_or_feature_cache_loaded_as_inference_state": False,
        "python_open_whitelist_enforced": True,
        "filesystem_isolation_claimed": False,
        "full_operating_system_io_trace_claimed": False,
    }
