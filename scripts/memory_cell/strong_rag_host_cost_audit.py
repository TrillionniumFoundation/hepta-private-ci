"""Read-only native-BF16 host cost audit of three completed Qwen shard runs.

The original model outputs, immutable source IDs, prompts, and scores remain
unchanged. These were repeated authored tasks on heterogeneous GitHub hosts,
NOT randomized hardware trials or independent production cost observations.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import statistics
import zipfile

SCHEMA = "hepta.memory-strong-rag.native-bf16-host-cost.v1"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
MODEL_DIGEST = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
PINS = {
    "A": (
        "8250698244417eb14994518af05fa6f79e783066",
        "7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f",
    ),
    "B": (
        "eba9af092cca1c2875552ffaea2219678143a73c",
        "b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138",
    ),
    "D": (
        "e0e413d670be8982b9986a119696c6ca164ca518",
        "d59560882e217d8772e4044ec33b8cdb10f5297f19b0a6e03e53266407c839a0",
    ),
}
CAL = ("k1", "k2", "k3", "k4", "k6")
EVAL = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
SCORE_FIELDS = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)
BF16_FLAGS = frozenset(("avx512_bf16", "amx_bf16", "bf16"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, val in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = val
        return result

    def reject(value):
        raise ValueError("nonfinite JSON constant " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def verified_zip(path: Path, pin: str):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        raise ValueError("bounded regular source ZIP required")
    if sha(path.read_bytes()) != pin:
        raise ValueError("original outer ZIP hash differs")
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if not 1 <= len(infos) <= 400 or sum(x.file_size for x in infos) > 12_000_000:
            raise ValueError("archive size or file census bound")
        seen = set()
        for item in infos:
            name = item.filename
            p = PurePosixPath(name)
            if (
                name in seen
                or p.is_absolute()
                or ".." in p.parts
                or "\\" in name
                or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise ValueError("unsafe, duplicate or extra ZIP path")
            seen.add(name)
        if "SHA256SUMS" not in seen:
            raise ValueError("missing complete manifest")
        manifest = {}
        for line in z.read("SHA256SUMS").decode("utf-8", "strict").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if match is None or match[2] in manifest:
                raise ValueError("invalid or duplicate manifest entry")
            manifest[match[2]] = match[1]
        if set(manifest) != seen - {"SHA256SUMS"}:
            raise ValueError("missing/extra archive member")
        for name, digest in manifest.items():
            if sha(z.read(name)) != digest:
                raise ValueError("changed sealed archive member: " + name)
        content = {name: z.read(name) for name in seen if name != "SHA256SUMS"}
    return content, len(manifest)


def flags_from_preflight(preflight):
    if preflight.get("schema") != "hepta.memory.runtime-preflight.v1":
        raise ValueError("unknown hardware observation profile")
    cpurec = preflight.get("commands", {}).get("lscpu", {})
    if cpurec.get("returncode") != 0 or not isinstance(cpurec.get("stdout"), str):
        raise ValueError("missing host CPU observation")
    raw = cpurec["stdout"]
    flagline = re.search(
        r"^(?:Flags|Features):\s*(.*)$", raw, flags=re.MULTILINE | re.IGNORECASE
    )
    if flagline is None:
        raise ValueError("missing advertised CPU instruction set")
    features = frozenset(flagline[1].lower().split())
    cpu = re.search(r"^Model name:\s*(.*)$", raw, flags=re.MULTILINE | re.IGNORECASE)
    model = cpu[1].strip() if cpu else "unspecified"
    threads = preflight.get("torch", {}).get("intra_op_threads")
    if type(threads) is not int or threads != 2:
        raise ValueError("host changed frozen two-thread reader")
    return bool(features & BF16_FLAGS), model


def rounded(value):
    return round(float(value), 4)


def summarize_group(rows):
    times = sorted(r["seconds"] for r in rows)
    gen_seconds = sorted(r["seconds"] / r["generated_tokens"] for r in rows)
    if not rows:
        raise ValueError("no host evidence")
    return {
        "calls": len(rows),
        "model_hosts": dict(sorted(Counter(r["model"] for r in rows).items())),
        "reader_seconds_sum": rounded(sum(times)),
        "median_call_seconds": rounded(statistics.median(times)),
        "median_seconds_per_generated_token": rounded(statistics.median(gen_seconds)),
        "q90_call_seconds_rank": rounded(
            times[min(len(times) - 1, int(0.9 * len(times)))]
        ),
        "calls_over_180_seconds": sum(t > 180 for t in times),
        "generated_tokens": sum(r["generated_tokens"] for r in rows),
    }


def audit(directory: Path):
    observations = []
    per_run = {}
    identities = defaultdict(list)
    for name, (source_commit, archive_pin) in PINS.items():
        content, members = verified_zip(directory / f"{name}-full.zip", archive_pin)
        if content["tested-commit.txt"].decode().strip() != source_commit:
            raise ValueError("generating commit differs from original")
        policy = strict_json(content["calibration/frozen-policy.json"])
        if (
            policy.get("source_commit") != source_commit
            or policy.get("selected_k") != 1
            or policy.get("reader_identity") != MODEL_DIGEST
            or policy.get("original_test_plan_sha256") != PLAN_SHA
        ):
            raise ValueError("model, plan or frozen calibration policy drift")
        groups = {}
        raw_by_phase = {}
        for phase, expected_arms in (("calibration", CAL), ("evaluation", EVAL)):
            raw = [
                strict_json(x)
                for x in content[f"{phase}/raw-answers.jsonl"].splitlines()
            ]
            scored = strict_json(content[f"{phase}/scored-answers.json"])
            report = strict_json(content[f"{phase}/report.json"])
            expected_size = 8 * len(expected_arms)
            if len(raw) != expected_size or len(scored) != expected_size:
                raise ValueError("original answer census incomplete")
            keys = [(r["question_id"], r["arm"]) for r in raw]
            if (
                len(set(keys)) != expected_size
                or len({q for q, _ in keys}) != 8
                or {arm for _, arm in keys} != set(expected_arms)
            ):
                raise ValueError("wrong original question/arm grid")
            if [(r["question_id"], r["arm"]) for r in scored] != keys:
                raise ValueError("raw and scored order differs")
            for a, b in zip(raw, scored, strict=True):
                if {k: v for k, v in b.items() if k not in SCORE_FIELDS} != a:
                    raise ValueError("scorer modified saved model answer or evidence")
                if (
                    a["status"] != "succeeded"
                    or type(b.get("strict_task_success")) is not bool
                ):
                    raise ValueError("failed or unscored real model attempt")
                identities[(phase, a["question_id"], a["arm"])].append(
                    (name, a["receipt"]["input_ids_digest"])
                )
            if report["raw_answers_sha256"] != sha(
                content[f"{phase}/raw-answers.jsonl"]
            ):
                raise ValueError("original raw journal SHA mismatch")
            raw_by_phase[phase] = {(r["question_id"], r["arm"]): r for r in raw}
            groups[phase] = report
        shard_count = 0
        replayed = set()
        for file in content:
            if not file.startswith("shards/") or not file.endswith(
                "/runtime-preflight.json"
            ):
                continue
            shard_dir = file.rsplit("/", 1)[0]
            phase = shard_dir.split("/")[1]
            if phase not in ("calibration", "evaluation"):
                raise ValueError("unknown original shard phase")
            pins = strict_json(content[f"{shard_dir}/sha-pins.json"])
            for member, pinned in pins.items():
                if sha(content[f"{shard_dir}/{member}"]) != pinned:
                    raise ValueError("shard manifest changed")
            run = strict_json(content[f"{shard_dir}/run.json"])
            preflight = strict_json(content[file])
            native, model = flags_from_preflight(preflight)
            if (
                run["source_commit"] != source_commit
                or run["phase"] != phase
                or run["runtime_preflight_sha256"] != sha(content[file])
            ):
                raise ValueError("shard CPU observation detached from generation")
            shard_rows = [
                strict_json(x)
                for x in content[f"{shard_dir}/raw-answers.jsonl"].splitlines()
            ]
            if len(shard_rows) != run["generated"] or len(shard_rows) != len(
                run["arms"]
            ):
                raise ValueError("missing/extra source-shard answer")
            for row in shard_rows:
                key = (row["question_id"], row["arm"])
                if key in replayed or row != raw_by_phase[phase].get(key):
                    raise ValueError("shard answer disagrees with merged journal")
                replayed.add(key)
                receipt = row["receipt"]
                seconds, g = receipt["seconds"], receipt["generated_tokens"]
                if (
                    type(seconds) not in (int, float)
                    or not math.isfinite(seconds)
                    or seconds <= 0
                    or type(g) is not int
                    or g <= 0
                ):
                    raise ValueError("invalid actual reader execution clock/token")
                observations.append(
                    {
                        "run": name,
                        "phase": phase,
                        "question_id": row["question_id"],
                        "arm": row["arm"],
                        "native_bf16": native,
                        "model": model,
                        "seconds": float(seconds),
                        "generated_tokens": g,
                    }
                )
            shard_count += 1
        if shard_count != 32 or len(replayed) != 112:
            raise ValueError("missing sharded CPU or original model evidence")
        by_arm = groups["evaluation"]["success_by_arm"]
        if any(by_arm[a]["planned"] != 8 or by_arm[a]["succeeded"] != 8 for a in EVAL):
            raise ValueError("not a complete eight-case frozen-reader result")
        arm_host_census = {}
        for arm in ("entity_time", "organized"):
            arm_rows = [
                row
                for row in observations
                if row["run"] == name
                and row["phase"] == "evaluation"
                and row["arm"] == arm
            ]
            if len(arm_rows) != 8:
                raise ValueError("missing matched original reader arm")
            arm_host_census[arm] = {
                "reported_native_bf16": sum(r["native_bf16"] for r in arm_rows),
                "no_reported_native_bf16": sum(not r["native_bf16"] for r in arm_rows),
            }
        per_run[name] = {
            "source_commit": source_commit,
            "arm_cpu_instruction_census": arm_host_census,
            "outer_zip_sha256": archive_pin,
            "verified_archive_members": members,
            "calibration_answers": 40,
            "evaluation_answers": 72,
            "sharded_host_observations": shard_count,
            "chosen_k": policy["selected_k"],
            "entity_time_correct": by_arm["entity_time"]["strict_success"],
            "organized_correct": by_arm["organized"]["strict_success"],
            "entity_time_input_tokens": by_arm["entity_time"]["input_tokens"],
            "organized_input_tokens": by_arm["organized"]["input_tokens"],
            "entity_time_reader_seconds": rounded(
                by_arm["entity_time"]["inference_seconds"]
            ),
            "organized_reader_seconds": rounded(
                by_arm["organized"]["inference_seconds"]
            ),
            "organized_minus_entity_time_reader_seconds": rounded(
                by_arm["organized"]["inference_seconds"]
                - by_arm["entity_time"]["inference_seconds"]
            ),
        }
    if len(observations) != 336:
        raise ValueError("three full 112-call shard runs required")
    if len(identities) != 112 or any(
        len(group) != 3 or len({digest for _, digest in group}) != 1
        for group in identities.values()
    ):
        raise ValueError("not identical prompted evidence across three runs")
    native = [x for x in observations if x["native_bf16"]]
    other = [x for x in observations if not x["native_bf16"]]
    matching = defaultdict(list)
    for row in observations:
        matching[(row["phase"], row["question_id"], row["arm"])].append(row)
    ratios = []
    for group in matching.values():
        fast = [r["seconds"] / r["generated_tokens"] for r in group if r["native_bf16"]]
        slow = [
            r["seconds"] / r["generated_tokens"] for r in group if not r["native_bf16"]
        ]
        if fast and slow:
            ratios.append(statistics.median(slow) / statistics.median(fast))
    if not ratios:
        raise ValueError("no matched host-capability comparison")
    return {
        "schema": SCHEMA,
        "source_pins": {
            name: {"source_commit": source, "outer_zip_sha256": pin}
            for name, (source, pin) in PINS.items()
        },
        "frozen_plan_sha256": PLAN_SHA,
        "frozen_reader_inventory": MODEL_DIGEST,
        "original_model_calls": len(observations),
        "distinct_original_prompts": len(identities),
        "three_repetitions_are_independent_tasks": False,
        "reported_native_bf16_cpu_flags": sorted(BF16_FLAGS),
        "host_groups": {
            "reported_native_bf16": summarize_group(native),
            "no_reported_native_bf16": summarize_group(other),
        },
        "same_prompt_cross_host": {
            "matched_prompt_positions": len(ratios),
            "median_non_native_to_native_seconds_per_generated_token_ratio": rounded(
                statistics.median(ratios)
            ),
            "ratio_is_causal_estimate": False,
        },
        "per_run": per_run,
        "no_randomized_hardware_allocation": True,
        "reader_seconds_exclude_model_staging_and_host_billing": True,
        "input_tokens_are_not_total_lifecycle_cost": True,
        "no_incremental_organized_task_success": True,
        "new_independent_source_families": 0,
        "statistical_superiority": False,
        "production_accepted": False,
        "disposition": (
            "NO-GO for treating fewer prompt tokens as a measured faster reader "
            "or for starting parametric learning on these repeated authored tasks"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")
    print(
        json.dumps(
            {
                "original_model_calls": result["original_model_calls"],
                "median_speed_ratio": result["same_prompt_cross_host"][
                    "median_non_native_to_native_seconds_per_generated_token_ratio"
                ],
                "production_accepted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
