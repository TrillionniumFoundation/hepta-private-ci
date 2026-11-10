"""Ordinary CLI entry for operator-pinned image acquisition and cold readback.

File acquisition reads a declared snapshot after its owner reserves one attempt.
It is not a desktop/camera capture backend. The source manifest and grant are
operator configuration, never an actor-supplied authority token.
"""

import json
import os
import re
import stat
import time
from pathlib import Path

from .capture_entry import OwnedProducer, model_sha256
from .owner import Owner
from .schema import Invalid, digest, exact, identifier, integer, require, sha

CAPTURE_BACKEND_SHA256 = sha(Path(__file__).read_bytes())


def capture_backend_sha256():
    """Return the loaded file-acquisition implementation pin, refusing live drift."""
    require(
        sha(Path(__file__).read_bytes()) == CAPTURE_BACKEND_SHA256,
        "loaded capture backend source changed; restart with an explicit new grant",
    )
    return CAPTURE_BACKEND_SHA256


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        raise Invalid("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _read_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "source is not a regular file")
        require(0 < before.st_size <= limit, "source byte limit exceeded")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        "source changed during acquisition",
    )
    require(0 < len(raw) <= limit, "source byte limit exceeded")
    return raw


def read_pinned(path, expected, limit):
    """Read one bounded regular snapshot and verify its operator-provided pin."""
    digest(expected)
    raw = _read_regular(path, limit)
    require(sha(raw) == expected, "source digest mismatch")
    return raw


def load_request(path):
    """Read at most 64 KiB of strict object JSON before capture admission."""
    request = _json(_read_regular(path, 65536))
    require(type(request) is dict, "capture request must be an object")
    return request


def operator_config(path):
    """Load exact source/model identities without opening image or weight files."""
    config = _json(_read_regular(path, 65536))
    exact(
        config,
        "schema state_dir owner_id generation budget_units capture_backend_sha256 grant model sources",
    )
    require(config["schema"] == "perc1.operator-config.v1", "unknown operator config")
    backend = capture_backend_sha256()
    require(
        digest(config["capture_backend_sha256"]) == backend,
        "capture backend source pin mismatch",
    )
    identifier(config["owner_id"])
    integer(config["generation"], 1)
    integer(config["budget_units"], 1)
    require(
        type(config["state_dir"]) is str and Path(config["state_dir"]).is_absolute(),
        "absolute owner store required",
    )
    sources = config["sources"]
    require(type(sources) is dict and 0 < len(sources) <= 128, "source catalog bound")
    for source_id, source in sources.items():
        identifier(source_id)
        require(
            re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", source_id),
            "invalid source identity",
        )
        exact(source, "image_path image_sha256 exact_text")
        digest(source["image_sha256"])
        require(
            type(source["image_path"]) is str
            and Path(source["image_path"]).is_absolute(),
            "absolute source path required",
        )
        if source["exact_text"] is not None:
            text = exact(source["exact_text"], "kind path sha256 engine")
            require(
                text["kind"] in ("source_text", "dom", "ocr"), "invalid exact channel"
            )
            require(
                type(text["path"]) is str and Path(text["path"]).is_absolute(),
                "absolute text path required",
            )
            digest(text["sha256"])
            identifier(text["engine"])
    grant = exact(
        config["grant"],
        "schema owner_id generation source_frontier source_ids scope_digest",
    )
    identifier(grant["owner_id"])
    integer(grant["generation"], 1)
    require(digest(grant["scope_digest"]) != "0" * 64, "empty capture scope")
    require(
        type(grant["source_ids"]) is list
        and all(type(source_id) is str for source_id in grant["source_ids"]),
        "invalid allowed source identities",
    )
    require(
        grant["schema"] == "perc1.capture-grant.v1"
        and grant["owner_id"] == config["owner_id"]
        and grant["generation"] == config["generation"]
        and grant["source_frontier"]
        == sha(
            {
                "sources": sources,
                "capture_backend_sha256": backend,
            }
        )
        and type(grant["source_ids"]) is list
        and sorted(grant["source_ids"]) == sorted(sources),
        "source grant does not match operator catalog",
    )
    model = exact(
        config["model"], "weights weights_sha256 projection projection_sha256 device"
    )
    require(model["device"] in ("cpu", "cuda"), "invalid model device")
    require(
        all(
            type(model[key]) is str and Path(model[key]).is_absolute()
            for key in ("weights", "projection")
        ),
        "absolute model paths required",
    )
    digest(model["weights_sha256"])
    projection = _json(
        read_pinned(model["projection"], model["projection_sha256"], 8 * 1024 * 1024)
    )
    binding = {
        "owner_id": config["owner_id"],
        "generation": config["generation"],
        "source_frontier": grant["source_frontier"],
        "encoder_sha256": model_sha256(model["weights_sha256"], projection),
        "grant_sha256": sha(grant),
    }
    return config, projection, binding


def run_capture(config_path, operation_id, request=None):
    """Execute once, or read a previous task receipt without re-acquiring sources."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    config, projection, binding = operator_config(config_path)
    this_entry = {
        "source_callback_invocations": 0,
        "encoder_loaded": False,
        "encoder_completed_calls": 0,
    }
    with Owner(config["state_dir"], binding, config["budget_units"]) as owner:
        if request is None:
            receipt = owner.receipt(operation_id)
            mode = "retained_readback"
        else:
            model = config["model"]
            adapter = OwnedProducer(
                owner,
                config["grant"],
                model["weights"],
                model["weights_sha256"],
                projection,
                device=model["device"],
            )

            def capture(admitted):
                this_entry["source_callback_invocations"] += 1
                require(
                    capture_backend_sha256() == config["capture_backend_sha256"],
                    "capture backend changed after admission",
                )
                source = config["sources"][admitted["source_id"]]
                image = read_pinned(
                    source["image_path"], source["image_sha256"], 4 * 1024 * 1024
                )
                text = source["exact_text"]
                exact_text = (
                    None
                    if text is None
                    else {
                        "kind": text["kind"],
                        "bytes": read_pinned(text["path"], text["sha256"], 8192),
                        "engine": text["engine"],
                    }
                )
                return {"image_bytes": image, "exact_text": exact_text}

            receipt = adapter.observe(operation_id, request, capture)
            this_entry["encoder_loaded"] = adapter.worker is not None
            # The worker counts completed feature calls; failed attempts may also occur.
            # Replayed receipt fields describe the original call, never this entry.
            this_entry["encoder_completed_calls"] = (
                0 if adapter.worker is None else adapter.worker.calls
            )
            mode = "acquire_or_replay"
        state = owner.status()
    return {
        "schema": "perc1.capture-entry-result.v1",
        "mode": mode,
        "status": receipt["status"],
        "receipt": receipt,
        "owner_status": state,
        "this_entry": this_entry,
        "entry_measurements": {
            "wall_ns": time.perf_counter_ns() - started,
            "process_cpu_ns": time.process_time_ns() - cpu,
            "scope": "config, owner open/recovery, acquisition-or-replay, journal close; interpreter imports and output serialization excluded",
            "energy_joules": None,
            "provider_billing": None,
        },
        "scientific_status": "HOLD",
        "production_daemon_integrated": False,
    }
