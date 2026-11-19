"""Independent stdlib review of archived warm-1 bytes; no propagation/imports."""

import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent.policy import POLICY, RUNTIME, RUNTIME_SHA256
from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire
from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent.adapter import load_authentic_input


ROOT = Path(__file__).parents[2]
EVIDENCE = Path(__file__).parent / "evidence/attempt001-20261119"
ZIP_SHA = "8f6a75afafeedaa5cfe6ad2b8b80af6b7d2b54f102f75d406ac1d92eb4b36629"
DENSE_SHA = "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18"


def doubles(raw):
    return [item[0] for item in struct.iter_unpack("<d", raw)]


def review():
    archive = EVIDENCE / "artifact-14501927547.zip"
    if archive.stat().st_size != 35819 or hashlib.sha256(archive.read_bytes()).hexdigest() != ZIP_SHA:
        raise ValueError("original GitHub artifact identity")
    with zipfile.ZipFile(archive) as source:
        files = {name: source.read(name) for name in source.namelist()}
    for name, raw in files.items():
        if name != "N256_WARM1_SPARSE.bin" and (EVIDENCE / "originals" / name).read_bytes() != raw:
            raise ValueError("archived text original changed")
    manifest = json.loads(files["MANIFEST.json"])
    if set(files) != set(manifest) | {"MANIFEST.json"}:
        raise ValueError("manifest member denominator")
    for name, expected in manifest.items():
        observed = {"bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}
        if observed != expected:
            raise ValueError(f"original member hash mismatch: {name}")
    records = {name: json.loads(raw) for name, raw in files.items() if name.endswith(".json")}
    payload = files["N256_WARM1_SPARSE.bin"]
    if hashlib.sha256(payload).hexdigest() != records["RESULT.json"]["payload_sha256"]:
        raise ValueError("producer capsule hash")
    dense = (ROOT / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/evidence/attempt001-20261119/originals/N256_WARM1.bin").read_bytes()
    if hashlib.sha256(dense).hexdigest() != DENSE_SHA:
        raise ValueError("archived dense oracle identity")
    sparse_state, dense_state = (wire.decode(raw, 8 * 1024**2) for raw in (payload, dense))
    if sparse_state.metadata != dense_state.metadata:
        raise ValueError("complete state metadata")
    pairs = [("state/" + a.name, a.tensor, b.tensor) for a, b in zip(sparse_state.blocks, dense_state.blocks, strict=True)]
    if [x.name for x in sparse_state.blocks] != [x.name for x in dense_state.blocks]:
        raise ValueError("state names")
    for a, b in zip(sparse_state.packets, dense_state.packets, strict=True):
        keys = ("identity", "generation", "origin", "target", "start", "end")
        if [getattr(a, k) for k in keys] != [getattr(b, k) for k in keys]:
            raise ValueError("packet metadata")
        pairs.extend(("packet/" + field, getattr(a, field), getattr(b, field))
                     for field in ("alpha", "generator", "output"))
    families = {}
    for name, actual, expected in pairs:
        if actual.shape != expected.shape or actual.dtype != expected.dtype:
            raise ValueError("tensor layout")
        stats = families.setdefault(name, {"coordinates": 0, "bitwise_mismatches": 0,
                                          "max_abs_error": 0.0, "max_symmetric_rel_error": 0.0,
                                          "outside_1e_13_plus_1e_11_abs_oracle": 0})
        for index, (a, b) in enumerate(zip(doubles(actual.payload), doubles(expected.payload), strict=True)):
            if not math.isfinite(a) or not math.isfinite(b):
                raise ValueError("nonfinite coordinate")
            error = abs(a - b)
            stats["coordinates"] += 1
            stats["bitwise_mismatches"] += actual.payload[8*index:8*index+8] != expected.payload[8*index:8*index+8]
            stats["max_abs_error"] = max(stats["max_abs_error"], error)
            stats["max_symmetric_rel_error"] = max(stats["max_symmetric_rel_error"], error / max(abs(a), abs(b), 1e-300))
            stats["outside_1e_13_plus_1e_11_abs_oracle"] += error > 1e-13 + 1e-11 * abs(b)
    if families != records["COMPARISON.json"]["families"] or sum(x["coordinates"] for x in families.values()) != 69728:
        raise ValueError("recorded full-coordinate comparison does not reproduce")
    preflight, admission = records["PREFLIGHT.json"], records["ADMISSION.json"]
    if admission["preflight"] != preflight or admission["policy"] != POLICY:
        raise ValueError("resource record binding")
    if preflight["runtime"] != RUNTIME or preflight["runtime_sha256"] != RUNTIME_SHA256:
        raise ValueError("recorded exact runtime")
    if admission["session"]["GITHUB_RUN_ID"] != "44466138035" or admission["session"]["GITHUB_RUN_ATTEMPT"] != "1":
        raise ValueError("recorded unique GitHub run")
    if admission["freeze_sha256"] != hashlib.sha256((Path(__file__).parent / "FREEZE.json").read_bytes()).hexdigest():
        raise ValueError("source freeze binding")
    frozen = json.loads((Path(__file__).parent / "FREEZE.json").read_text())
    if records["TERMINAL.json"]["identity"] != frozen["identity"] or admission["scope"] != frozen["scope"]:
        raise ValueError("new independent warm-1 scope")
    for relative, expected in frozen["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("executed frozen source identity")
    if preflight["meminfo_kib"]["MemAvailable"] < POLICY["minimum_mem_available_kib"] or preflight["meminfo_kib"]["SwapFree"] < POLICY["minimum_swap_free_kib"]:
        raise ValueError("recorded memory resources")
    pressures = [float(dict(x.split("=") for x in line.split()[1:])["avg10"]) for line in preflight["memory_pressure"]]
    if max(pressures) > POLICY["maximum_memory_pressure_avg10"]:
        raise ValueError("recorded memory pressure")
    readable, cpus = 0, 0
    for collection in (preflight["ancestor_cgroup_chain"], records["END_CGROUP.json"]["ancestor_cgroup_chain"]):
        for entry in collection:
            fields = entry["fields"]
            events = dict((name, int(value)) for name, value in (line.split() for line in fields.get("memory.events", "").splitlines()))
            if any(events.get(name, 0) for name in ("oom", "oom_kill", "oom_group_kill")):
                raise ValueError("historical or new OOM event")
            if collection is preflight["ancestor_cgroup_chain"]:
                if "cpuset.cpus.effective" in fields:
                    spans = [item.split("-") for item in fields["cpuset.cpus.effective"].split(",")]
                    cpus = max(cpus, sum(int(x[-1])-int(x[0])+1 for x in spans))
                if "memory.max" in fields and "memory.current" in fields:
                    readable += 1
                    if fields["memory.max"] != "max" and int(fields["memory.max"])-int(fields["memory.current"]) < POLICY["minimum_finite_cgroup_headroom_bytes"]:
                        raise ValueError("recorded finite ancestor headroom")
    if readable == 0 or cpus < POLICY["minimum_effective_cpus"]:
        raise ValueError("recorded ancestor memory/CPU availability")
    authentic = load_authentic_input(ROOT)
    probability, content = doubles(authentic.active_payload), doubles(authentic.signed_content_payload)
    state = {block.name: doubles(block.tensor.payload) for block in sparse_state.blocks}
    first = next(packet for packet in authentic.phase_packets if packet[1] == 0)
    balances = []
    for channel in range(5):
        initial = math.fsum(probability[1:]) if channel == 0 else math.fsum(content[4*j+channel-1] for j in range(1, 257))
        active = math.fsum(state["active"][channel*510:(channel+1)*510])
        upper = math.fsum(state["upper"][channel*3:channel*3+3])
        hit = math.fsum(state["mass"][channel*2:channel*2+2])
        released = float(first[3][channel]) / 1000
        balances.append({"channel": channel, "initial_active_upper": initial, "released": released,
                         "final_active": active, "final_upper": upper, "lower_hit": hit,
                         "residual": math.fsum((active, upper, hit, -initial, -released))})
    return {"archive_sha256": ZIP_SHA, "manifest_members_verified": len(manifest),
            "sparse_capsule_sha256": hashlib.sha256(payload).hexdigest(), "capsule_bytes": len(payload),
            "coordinate_counts": wire.coordinate_counts(sparse_state), "families": families,
            "bitwise_mismatches": sum(x["bitwise_mismatches"] for x in families.values()),
            "channel_balances": balances, "recorded_static_resource_thresholds_satisfied": True,
            "recorded_runtime_identity_satisfied": True, "source_freeze_sha256": admission["freeze_sha256"],
            "capture_age_independently_reconstructible_from_artifact": False,
            "capture_age_note": "Runner and child enforce <=30s; artifact does not retain the exact child-check timestamp.",
            "execution_counts_independently_instrumented": False,
            "producer_execution_result": records["RESULT.json"], "child_cost": records["COST.json"],
            "original_bitwise_gate": records["TERMINAL.json"]["original_bitwise_gate"],
            "review_authentic_input_reads": 1, "review_dynamic_steps": 0, "review_numerical_imports": 0,
            "full_roster_qualification": False, "largegrid_qualification": False, "all_closed": False}


if __name__ == "__main__":
    result = review()
    result["review_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
