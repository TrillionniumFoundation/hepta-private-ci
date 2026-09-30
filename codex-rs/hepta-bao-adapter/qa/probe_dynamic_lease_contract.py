#!/usr/bin/env python3
"""Probe a fixed HeptaBao binary in a fresh synthetic TLS service, never production.

Exit 2 is a real provider capability blocker, not a passed dynamic-lease E2E.
This probe cannot enable dispatch or change the integration pin.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-checkout", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    if len(args.source_commit) != 40 or any(c not in "0123456789abcdef" for c in args.source_commit):
        parser.error("source commit must be a full hexadecimal commit ID")
    args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(args.work_dir, 0o700)
    fixture = args.service_checkout / "qa/single-node/smoke.py"
    spec = importlib.util.spec_from_file_location("heptabao_pinned_smoke", fixture)
    if spec is None or spec.loader is None:
        raise RuntimeError("fixed service fixture unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    instance = module.Instance(args.server.resolve(), args.work_dir / "service")
    evidence = {
        "schema": "hepta.bao.dynamic-contract-probe.v1",
        "providerCommit": args.source_commit,
        "serverSha256": hashlib.sha256(args.server.read_bytes()).hexdigest(),
        "providerFixtureSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "checks": [],
        "dynamicLeaseExecutionProved": False,
        "productionAuthority": False,
    }
    try:
        instance.start()
        status, initialized = instance.call("POST", "sys/init", {"secret_shares": 1, "secret_threshold": 1})
        if status != 200:
            raise RuntimeError(f"synthetic initialization failed: HTTP {status}")
        instance.token = initialized["root_token"]
        status, _ = instance.call("POST", "sys/unseal", {"key": initialized["keys_base64"][0]})
        if status != 200:
            raise RuntimeError(f"synthetic unseal failed: HTTP {status}")
        status, _ = instance.call("POST", "secret/data/contract-probe", {"data": {"value": "synthetic-contract-only"}})
        evidence["checks"].append({"name": "kv_control_write", "status": status})
        status, body = instance.call("GET", "secret/data/contract-probe?version=1")
        if status != 200 or body.get("data", {}).get("data", {}).get("value") != "synthetic-contract-only":
            raise RuntimeError("healthy KV control profile failed")
        evidence["checks"].append({"name": "kv_control_read", "status": status})
        for method, path, payload in [
            ("POST", "sys/mounts/probe-db", {"type": "database"}),
            ("GET", "probe-db/creds/synthetic-readonly", None),
            ("POST", "sys/leases/lookup", {"lease_id": "synthetic/nonexistent"}),
            ("POST", "sys/leases/renew", {"lease_id": "synthetic/nonexistent", "increment": 60}),
            ("POST", "sys/leases/revoke", {"lease_id": "synthetic/nonexistent", "sync": True}),
        ]:
            status, response = instance.call(method, path, payload)
            # Never retain token, lease payload, response text or secret material.
            evidence["checks"].append({"name": path, "method": method, "status": status,
                "responseSha256": hashlib.sha256(json.dumps(response, sort_keys=True).encode()).hexdigest()})
        evidence["status"] = "blocked_provider_contract" if any(row["status"] == 501 for row in evidence["checks"]) else "requires_engine_configuration_and_full_e2e"
        evidence["explanation"] = "Endpoint probes and healthy KV control are not dynamic issue/renew/revoke acceptance."
        return 2
    finally:
        instance.stop()
        path = args.work_dir / "result.json"
        with path.open("x") as stream:
            json.dump(evidence, stream, indent=2)
            stream.write("\n")
        os.chmod(path, 0o600)
        print(json.dumps(evidence, indent=2))

if __name__ == "__main__":
    raise SystemExit(main())
