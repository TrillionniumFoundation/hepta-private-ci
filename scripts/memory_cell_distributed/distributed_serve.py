"""Explicit mTLS deployment entry for fixed replicas, source owners and workers."""

# Standalone entry resolves sibling research modules.
# ruff: noqa: E402
import argparse
import hashlib
import os
from pathlib import Path
import socket
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
for module in ("memory_cell", "memory_cell_service", "memory_cell_network"):
    sys.path.insert(0, str(SCRIPTS / module))

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from authority_contract import Membership, decode, encode, fields
from authority_client import QuorumClient
from authority_replica import Replica
from rpc_costs import MeteredRPC
from source_bound_authority import SourceBoundAuthority
from source_evidence import SourceEvidence
from source_store import SourceStore
from tls_wire import Credentials, Grant, server


def private_key(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 8192:
        raise ValueError("private signing key must be a bounded owner-only file")
    return load_pem_private_key(path.read_bytes(), password=None)


def launch(config, ready_file):
    role = config.get("role")
    common = ("role", "root", "credentials", "grants", "host", "port")
    extra = {
        "replica": ("member_id", "membership", "private_key_file", "creation"),
        "source": ("source_database", "scope", "cell_id", "cell_role"),
        "worker": (
            "node_id",
            "membership",
            "replicas",
            "source_endpoint",
            "model",
            "outbound_credentials",
        ),
    }
    if role not in extra:
        raise ValueError("registered distributed role required")
    fields(config, common + extra[role])
    root = Path(config["root"])
    if root.is_symlink():
        raise ValueError("real deployment root required")
    root.mkdir(parents=True, exist_ok=True)
    credentials = Credentials(**config["credentials"])
    grants = [Grant(**grant) for grant in config["grants"]]
    if role == "replica":
        application = Replica(
            root,
            config["member_id"],
            Membership(**config["membership"]),
            private_key(config["private_key_file"]),
            creation=config["creation"],
        )
    elif role == "source":
        application = SourceEvidence(
            SourceStore(
                config["source_database"],
                config["scope"],
                config["cell_id"],
                config["cell_role"],
            )
        )
    else:
        from network_worker import Worker

        outbound = Credentials(**config["outbound_credentials"])
        rpc = MeteredRPC(root / "rpc-costs.jsonl")
        quorum = QuorumClient(
            Membership(**config["membership"]), config["replicas"], outbound, rpc=rpc
        )
        bound = SourceBoundAuthority(
            quorum, config["source_endpoint"], outbound, rpc=rpc
        )
        application = Worker(
            root,
            config["node_id"],
            next(iter(config["replicas"].values())),
            outbound,
            config["model"],
            transport=rpc,
            authority_snapshot=bound.snapshot,
        )
    instance = server(
        application, credentials, grants, host=config["host"], port=config["port"]
    )
    boot = Path("/proc/sys/kernel/random/boot_id")
    receipt = dict(
        role=role,
        pid=os.getpid(),
        hostname=socket.gethostname(),
        boot_id_sha256=hashlib.sha256(boot.read_bytes()).hexdigest()
        if boot.exists()
        else None,
        bind_host=config["host"],
        port=instance.server_port,
        tls_required=True,
        protocol="fixed-membership-single-writer-crash-fault",
        physical_host_attestation=False,
    )
    ready = Path(ready_file)
    temporary = ready.with_suffix(".tmp")
    with temporary.open("xb") as stream:
        stream.write(encode(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(ready)
    try:
        instance.serve_forever(poll_interval=0.1)
    finally:
        instance.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    if args.config.stat().st_size > 1024 * 1024:
        parser.error("bounded deployment configuration required")
    launch(decode(args.config.read_bytes()), args.ready)
