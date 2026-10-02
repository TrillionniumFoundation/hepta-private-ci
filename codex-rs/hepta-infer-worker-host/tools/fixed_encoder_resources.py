"""Use the original Root Fleet owner reader before and after fixed encoding."""

import subprocess
import time

from fixed_encoder_sources import (
    decode_json,
    protected_path,
    source_bytes,
    verify_large_source,
)


def validate_observation(principal, pid, kernel_identity, value, now_ms):
    if set(value) != {
        "observed_at_ms",
        "boot_identity",
        "resource_authority_epoch",
        "observation",
    }:
        raise ValueError("original resource observation shape")
    seen = value["observed_at_ms"]
    epoch = value["resource_authority_epoch"]
    if (
        type(seen) is not int
        or not 0 < seen <= now_ms
        or now_ms - seen > 2000
        or type(epoch) is not int
        or epoch <= 0
        or not isinstance(value["boot_identity"], str)
        or not value["boot_identity"]
    ):
        raise ValueError("fresh original resource epoch/time")
    observation = value["observation"]
    context = observation["context"]
    grant = observation["allocation"]
    if (
        not isinstance(grant, dict)
        or grant["revoked"] is not False
        or grant["expires_at_ms"] <= now_ms
        or grant["authority_epoch"] != epoch
        or grant["lease_generation"] <= 0
        or observation["process_id"] != pid
        or str(observation["process_start_ticks"]) != kernel_identity[0]
        or context["principal_id"] != principal["agent_id"]
        or context["manifest_digest"] != principal["fleet_manifest_digest"]
    ):
        raise ValueError("actual kernel peer/current allocation binding")
    for field in (
        "allocation_id",
        "principal_id",
        "host_id",
        "host_generation",
        "resources",
    ):
        if grant[field] != context[field]:
            raise ValueError("original resource context differs from current grant")
    if grant["semantic_digest"] != context["manifest_digest"]:
        raise ValueError("original launch/resource semantics")
    resources = grant["resources"]
    if (
        resources["cpu_millis"] <= 0
        or resources["memory_bytes"] <= 0
        or resources["concurrent_turns"] <= 0
    ):
        raise ValueError("original allocation has no physical dispatch budget")
    # Renewal may advance the lease, while this physical operation must retain
    # the same original process/context/resource epoch and resource limits.
    return (value["boot_identity"], epoch, context, grant["allocation_id"], resources)


def observe(config, principal, pid, kernel_identity):
    reader = config["resource_observer"]
    if set(reader) != {"program", "local_host_policy", "fleet_root"}:
        raise ValueError("fixed original resource reader configuration")
    verify_large_source(reader["program"], 128 * 1024 * 1024)
    source_bytes(reader["local_host_policy"], 64 * 1024)
    protected_path(reader["fleet_root"], directory=True)
    result = subprocess.run(
        [
            reader["program"]["path"],
            "--fleet-root",
            reader["fleet_root"],
            "resource-observe",
            "--local-host-policy",
            reader["local_host_policy"]["path"],
            principal["agent_id"],
            str(pid),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        check=False,
    )
    # This pinned reader owns its original total two-second deadline. No
    # second database owner, caller clock, epoch choice or fallback is supplied.
    if result.returncode != 0 or not 0 < len(result.stdout) <= 64 * 1024:
        raise ValueError("original Root resource observation failed")
    return validate_observation(
        principal,
        pid,
        kernel_identity,
        decode_json(result.stdout),
        time.time_ns() // 1_000_000,
    )
