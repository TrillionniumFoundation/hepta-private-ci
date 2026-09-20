#!/usr/bin/env python3
"""Exercise separate issuer + consumer binaries against the real TLS service.

Requires Python cryptography and openssl. All credentials are synthetic. The
service checkout provides qa/single-node/smoke.py's Instance lifecycle helper.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def run(args):
    args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        "heptabao_smoke", args.service_checkout / "qa/single-node/smoke.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    instance = module.Instance(args.server, args.work_dir / "service")
    passed = []

    def check(name, condition):
        if not condition:
            raise RuntimeError("failed scenario: " + name)
        if name not in passed:
            passed.append(name)

    def execute(binary, arguments, stdin):
        return subprocess.run(
            [str(binary), *arguments], input=stdin, capture_output=True, timeout=20
        )

    try:
        instance.start()
        status, initialized = instance.call(
            "POST", "sys/init", {"secret_shares": 1, "secret_threshold": 1}
        )
        check("initialize", status == 200)
        instance.token = initialized["root_token"]
        key = initialized["keys_base64"][0]
        check("unseal", instance.call("POST", "sys/unseal", {"key": key})[0] == 200)
        secret = "synthetic-consumer-" + secrets.token_hex(32)
        check(
            "write_version",
            instance.call("POST", "secret/data/provider", {"data": {"value": secret}})[
                0
            ]
            == 200,
        )
        seed = secrets.token_bytes(32)
        issuer = Ed25519PrivateKey.from_private_bytes(seed)
        seed_path = args.work_dir / "issuer.seed"
        with os.fdopen(
            os.open(seed_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(seed)
        config = {
            "endpoint": instance.address,
            "ca_pem_file": str(instance.root / "ca.crt"),
            "signer_id": "smoke-owner",
            "verifying_key": list(issuer.public_key().public_bytes_raw()),
            "authority_state_dir": str(args.work_dir / "authority"),
            "authority_epoch": 1,
            "revocation_revision": 1,
            "revoked_grant_ids": [],
            "request": {
                "subject_id": "smoke-agent",
                "consumer_id": "local-validator",
                "namespace": "",
                "mount": "secret",
                "path": "provider",
                "field": "value",
                "version": 1,
                "expected_secret_sha256": list(
                    hashlib.sha256(secret.encode()).digest()
                ),
            },
            "grant": None,
        }
        config_path = args.work_dir / "host.json"

        def save(value):
            config_path.write_text(json.dumps(value))
            config_path.chmod(0o600)

        def signed(value, name):
            save(value)
            bound = execute(args.consumer, ["binding", str(config_path)], b"")
            check(name + "_binding", bound.returncode == 0)
            now = time.time_ns() // 1_000_000
            proposal = {
                "schema_version": 1,
                "signer_id": "smoke-owner",
                "authority_epoch": 1,
                "grant_id": name,
                "nonce": list(secrets.token_bytes(32)),
                "binding": json.loads(bound.stdout),
                "not_before_unix_ms": now - 1000,
                "expires_at_unix_ms": now + 120_000,
            }
            issued = execute(
                args.signer,
                ["sign", "--key", str(seed_path)],
                json.dumps(proposal).encode(),
            )
            check(name + "_issuer", issued.returncode == 0)
            value["grant"] = json.loads(issued.stdout)
            save(value)

        def consume(value, token):
            save(value)
            result = execute(
                args.consumer, ["consume", str(config_path)], token.encode()
            )
            check(
                "redacted_process_output",
                all(
                    item not in result.stdout + result.stderr
                    for item in (secret.encode(), instance.token.encode(), seed)
                ),
            )
            return result

        signed(config, "first-read")
        result = consume(config, instance.token)
        check("real_tls_consumer", result.returncode == 0)
        receipt = json.loads(result.stdout)
        check(
            "version_and_digest",
            receipt["version"] == 1
            and receipt["secret_sha256"] == config["request"]["expected_secret_sha256"],
        )
        replay = consume(config, instance.token)
        check(
            "replay_denied_across_process_restart",
            replay.returncode != 0 and b"AlreadyClaimed" in replay.stderr,
        )
        forged = copy.deepcopy(config)
        signed(forged, "forged-read")
        forged["grant"]["signature"][0] ^= 1
        denied = consume(forged, instance.token)
        check(
            "forged_signature_denied",
            denied.returncode != 0 and b"InvalidSignature" in denied.stderr,
        )
        denied_config = copy.deepcopy(config)
        signed(denied_config, "provider-denial")
        denied = consume(denied_config, "invalid-synthetic-token")
        check(
            "provider_denied",
            denied.returncode != 0 and b"ProviderDenied" in denied.stderr,
        )
        instance.stop()
        instance.start()
        check(
            "unseal_after_sigkill",
            instance.call("POST", "sys/unseal", {"key": key})[0] == 200,
        )
        restarted = copy.deepcopy(config)
        signed(restarted, "after-server-restart")
        result = consume(restarted, instance.token)
        check("read_after_server_sigkill", result.returncode == 0)
        check(
            "audit_contains_no_secret",
            secret.encode() not in (instance.root / "audit.jsonl").read_bytes(),
        )
        evidence = {
            "schema": "hepta.bao.real-consumer-smoke.v1",
            "passed": passed,
            "count": len(passed),
            "version": receipt["version"],
            "secret_sha256": bytes(receipt["secret_sha256"]).hex(),
        }
        (args.work_dir / "result.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        print(json.dumps(evidence))
    finally:
        instance.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("service-checkout", "server", "consumer", "signer", "work-dir"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    if not all(value.is_absolute() for value in vars(args).values()):
        parser.error("all paths must be absolute")
    try:
        run(args)
    except Exception as error:
        # No HTTP payloads, bearer credentials, or key bytes in failure output.
        print(
            "real consumer smoke failed: " + str(error)
            if isinstance(error, RuntimeError)
            else "real consumer smoke failed: " + type(error).__name__
        )
        raise SystemExit(1) from None
