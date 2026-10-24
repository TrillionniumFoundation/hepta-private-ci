"""Bounded signed relay envelopes and independently recorded runner identities.

Trust bootstrap is the exact authenticated GitHub Actions run/artifact, not a
self-signed key. Artifact delivery is asynchronous and is not an mTLS network.
"""

import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import socket
import subprocess
import time

from authority_contract import decode, encode, fields, verify_signature

SCOPE = "memory-multihost-20261024"
MAX_FILE_BYTES = 64 * 1024 * 1024
PROTOCOL = dict(
    schema="hepta.memory.multihost-relay-registration.v1",
    train_updates=256,
    rank=8,
    learning_rate=0.001,
    seed=2718,
    synthetic_facts=3,
    source_decoder_queries=9,
    target_decoder_queries=35,
    load_requests=32,
    load_arrivals="serial closed loop; fresh decoder process per request",
    source_values="fresh random assignment after frozen source checkout",
    fresh_process_reads=True,
    transport="authenticated same-run Actions artifact relay",
    handoff="source durably fenced before offer upload; target stage follows",
    continuous_availability_claim=False,
    immediate_revocation_before_delivery_claim=False,
    direct_cross_host_mtls=False,
    physical_hardware_attested=False,
    future_task_claim=False,
    production_accepted=False,
    gates=dict(
        distinct_runner_boots=True,
        checkpoint_bytes_preserved=True,
        exact_raw_outputs_preserved=True,
        revocation_and_restart_callbacks_zero=True,
    ),
    accuracy_reported_separately=True,
)


def retain(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())


def identity():
    repo = Path(__file__).resolve().parents[2]
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    if head != os.environ.get("SOURCE_SHA") or len(head) != 40:
        raise ValueError("runner checkout differs from the registered workflow source")
    boot = Path("/proc/sys/kernel/random/boot_id").read_bytes()
    return dict(
        source_sha=head,
        run_id=os.environ["GITHUB_RUN_ID"],
        run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
        job=os.environ["GITHUB_JOB"],
        hostname=socket.gethostname(),
        boot_id_sha256=hashlib.sha256(boot).hexdigest(),
        runner_name=os.environ.get("RUNNER_NAME"),
        pid=os.getpid(),
        machine=platform.machine(),
        utc_unix_seconds=time.time(),
        physical_hardware_attested=False,
    )


def runtime():
    return dict(
        python=platform.python_version(),
        packages={
            item.metadata["Name"]: item.version
            for item in importlib.metadata.distributions()
        },
    )


def seal(payload, key):
    return dict(payload=payload, signature=key.sign(encode(payload)).hex())


def verify(envelope, public_key, kind):
    fields(envelope, ("payload", "signature"))
    verify_signature(public_key, envelope["signature"], encode(envelope["payload"]))
    value = envelope["payload"]
    if (
        value["kind"] != kind
        or value["scope"] != SCOPE
        or value["source_sha"] != os.environ["SOURCE_SHA"]
        or value["run_id"] != os.environ["GITHUB_RUN_ID"]
        or value["run_attempt"] != os.environ["GITHUB_RUN_ATTEMPT"]
    ):
        raise ValueError("relay envelope belongs to another phase, run or source")
    return value


def provenance(kind):
    return dict(
        kind=kind,
        scope=SCOPE,
        source_sha=os.environ["SOURCE_SHA"],
        run_id=os.environ["GITHUB_RUN_ID"],
        run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
    )


def read(path):
    path = Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("bounded real relay file required")
    return decode(path.read_bytes())


def artifact_name(stage):
    if stage not in ("offer", "ready", "withdrawal", "finished"):
        raise ValueError("unknown relay stage")
    return f"memory-multihost-{stage}-{os.environ['SOURCE_SHA']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
