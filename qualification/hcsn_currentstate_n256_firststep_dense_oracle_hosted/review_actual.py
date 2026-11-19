"""Verify actual warm-1 artifact bytes and conservation without re-running it."""

import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent import policy
from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
    coordinate_counts, decode,
)
from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent.adapter import (
    load_authentic_input,
)


HERE = Path(__file__).parent
ROOT = HERE.parents[1]
EVIDENCE = HERE / "evidence" / "attempt001-20261119"
ARCHIVE_SHA256 = "00ea3582663bcb40303202a944d8f0a7643d64b7272c74a1f4f04f2e4012eb69"
CAPSULE_SHA256 = "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def doubles(raw):
    return tuple(value[0] for value in struct.iter_unpack("<d", raw))


def review():
    archive_path = EVIDENCE / "artifact-14501310345.zip"
    require(sha(archive_path.read_bytes()) == ARCHIVE_SHA256, "GitHub ZIP digest")
    artifact = json.loads((EVIDENCE / "ARTIFACT_METADATA.json").read_text())["artifacts"][0]
    require(artifact["id"] == 14501310345 and artifact["digest"] == "sha256:" + ARCHIVE_SHA256,
            "live GitHub artifact metadata")
    with zipfile.ZipFile(archive_path) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())), "duplicate member")
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["MANIFEST.json"])["files"]
    require(set(manifest) == set(members) - {"MANIFEST.json"}, "manifest coverage")
    for name, expected in manifest.items():
        raw = members[name]
        require(len(raw) == expected["bytes"] and sha(raw) == expected["sha256"],
                f"manifest binding: {name}")
        require((EVIDENCE / "originals" / name).read_bytes() == raw,
                f"extracted original: {name}")
    require((EVIDENCE / "originals" / "MANIFEST.json").read_bytes()
            == members["MANIFEST.json"], "extracted manifest")
    documents = {
        name: json.loads(raw) for name, raw in members.items() if name.endswith(".json")
    }
    result = documents["RESULT.json"]
    terminal = documents["TERMINAL.json"]
    cost = documents["COST.json"]
    admission = documents["ADMISSION.json"]
    request = json.loads((HERE / "REQUEST.json").read_text())
    require(terminal["status"] == "SUCCESS", "numerical terminal")
    require(terminal["result"] == result and terminal["cost"] == cost, "terminal binding")
    require(admission["request_sha256"] == sha((HERE / "REQUEST.json").read_bytes()),
            "original request binding")
    for key, name in (
        ("host_snapshot_sha256", "HOST_SNAPSHOT.json"),
        ("ancestor_cgroup_snapshot_sha256", "ANCESTOR_CGROUP.json"),
        ("allocation_sha256", "ALLOCATION.json"),
        ("calendar_sha256", "CALENDAR.json"),
    ):
        require(admission[key] == sha(members[name]), f"admission binding: {name}")
    require(admission["unique_execution_key"] == request["unique_execution_key"],
            "original one-shot identity")
    require(sha(members["N256_WARM1.bin"]) == CAPSULE_SHA256
            == terminal["capsule_sha256"] == result["payload_sha256"], "capsule binding")
    expected_counts = {"dynamic_steps": 1, "dense_expm_actions": 2,
                       "n256_serializer_calls": 1, "optimizer_steps": 0, "torch_calls": 0}
    require(all(result[key] == value for key, value in expected_counts.items()),
            "producer execution counts")
    require(result["qualification"] is False and terminal["all_closed"] is False,
            "original qualification scope")
    require(cost["returncode"] == 0 and cost["timed_out"] is False, "child exit")
    assessment = policy.assess_preflight(documents["PREFLIGHT.json"], documents["LAUNCH.json"])
    require(assessment["preflight_contract_satisfied"], "unchanged resource policy")
    runtime = documents["RUNTIME_OBSERVATION.json"]
    runtime_raw = json.dumps(runtime["runtime"], sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
    require(sha(runtime_raw) == runtime["runtime_sha256"] == request["runtime_sha256"],
            "frozen runtime observation digest")
    start_chain = documents["ANCESTOR_CGROUP.json"]["ancestor_cgroup_chain"]
    end_chain = {item["path"]: item for item in documents["END_CGROUP.json"][
        "ancestor_cgroup_chain"
    ]}
    for item in start_chain:
        if "memory.events" not in item["fields"]:
            continue
        before = dict(line.split() for line in item["fields"]["memory.events"].splitlines())
        after = dict(line.split() for line in end_chain[item["path"]]["fields"][
            "memory.events"
        ].splitlines())
        require(all(before.get(key, "0") == after.get(key, "0") == "0"
                    for key in ("oom", "oom_kill", "oom_group_kill")), "OOM events")
    envelope = decode(members["N256_WARM1.bin"], max_envelope_bytes=1_000_000)
    counts = coordinate_counts(envelope)
    require(counts == {"state": 2600, "packet_alpha": 1320,
                       "packet_generator": 65544, "packet_output": 264,
                       "packet": 67128, "total": 69728}, "coordinate denominator")
    require(envelope.metadata["time"] == "1/1000" and len(envelope.packets) == 9,
            "warm-1 time and packet denominator")
    blocks = {block.name: doubles(block.tensor.payload) for block in envelope.blocks}
    tensors = [block.tensor for block in envelope.blocks]
    tensors.extend(getattr(packet, name) for packet in envelope.packets
                   for name in ("alpha", "generator", "output"))
    require(all(math.isfinite(value) for tensor in tensors for value in doubles(tensor.payload)),
            "finite decoded coordinates")
    authentic = load_authentic_input(ROOT)
    active = doubles(authentic.active_payload)
    content = doubles(authentic.signed_content_payload)
    parents = [packet for packet in authentic.phase_packets if packet[1] == 0]
    require(len(parents) == 1, "original release packet")
    balance = []
    for channel in range(5):
        initial = (math.fsum(active[1:]) if channel == 0 else
                   math.fsum(content[index * 4 + channel - 1] for index in range(1, 257)))
        released = float(parents[0][3][channel]) * 0.001
        final_active = math.fsum(blocks["active"][channel * 510:(channel + 1) * 510])
        final_upper = math.fsum(blocks["upper"][channel * 3:(channel + 1) * 3])
        lower_hit = math.fsum(blocks["mass"][channel * 2:(channel + 1) * 2])
        residual = final_active + final_upper + lower_hit - initial - released
        balance.append({"channel": channel, "initial_active_and_upper": initial,
                        "released_from_original_delay_packet": released,
                        "final_active": final_active, "final_upper": final_upper,
                        "lower_hit": lower_hit, "balance_residual": residual})
    return {
        "schema": "hcsn-n256-actual-warm1-artifact-review-v1",
        "run_id": 44462874515, "job_id": 135353619601, "artifact_id": 14501310345,
        "head_sha": "c8e36e8579153761adee4ed84d44b40ec6d36000",
        "review_source_sha256": sha(Path(__file__).read_bytes()),
        "archive_sha256": ARCHIVE_SHA256, "archive_bytes": archive_path.stat().st_size,
        "capsule_sha256": CAPSULE_SHA256, "capsule_bytes": len(members["N256_WARM1.bin"]),
        "manifest_members_verified": len(manifest), "terminal": terminal["status"],
        "producer_execution_counts": expected_counts,
        "execution_counts_independently_instrumented": False,
        "child_input_read_count": None,
        "child_input_read_count_reason": "original RESULT has no input-read counter",
        "review_authentic_input_loads": 1, "review_numerical_propagations": 0,
        "decoded_coordinates": counts, "decoded_packets": len(envelope.packets),
        "candidate_compared_coordinates": 0,
        "comparison_scope": "artifact bytes, recorded preflight, and channel balance only",
        "original_preflight_policy_satisfied": True,
        "readable_ancestor_oom_counters_zero_before_and_after": True,
        "runtime_sha256": documents["RUNTIME_OBSERVATION.json"]["runtime_sha256"],
        "child_cost": cost,
        "child_peak_rss_bytes": cost["child_maxrss_kib"] * 1024,
        "channel_balance": balance,
        "maximum_absolute_channel_balance_residual": max(
            abs(row["balance_residual"]) for row in balance
        ),
        "probability_active_minimum": min(blocks["active"][:510]),
        "probability_discounted_hit": blocks["discounted_hit"][0],
        "probability_hit": blocks["mass"][0],
        "largegrid_qualification": False, "training_gradient_verified": False,
        "equal_budget_benefit_verified": False, "all_closed": False,
    }


if __name__ == "__main__":
    result = review()
    (EVIDENCE / "INDEPENDENT_REVIEW.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
