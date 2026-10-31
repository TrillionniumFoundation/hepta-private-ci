"""Registered portable operational adaptation followed by the original science gate.

The isolated operational function has exactly one substituted dependency:
verify_ack uses newly downloaded immutable ZIPs and treats original inode tuples
as historical evidence. Original module globals, canonical roots and every
scientific gate remain unchanged. No scientific value decoder lives here.
"""

import importlib
import math
from pathlib import Path
import re
import sys
import types

from . import asset_replay, portable_common as c
from .archives import Archive


def download_map(receipt, binding, request_item):
    c.need(
        receipt.get("schema") == "hepta.parameter-field.deployment-provider-receipt.1"
        and receipt.get("status") == "complete"
        and receipt.get("request") == request_item,
        "Actual provider acquisition did not complete",
    )
    run = receipt["run"]
    requested = binding["provider"]
    c.need(
        run["id"] == requested["run_id"]
        and run["run_attempt"] == requested["run_attempt"]
        and run["head_sha"] == requested["head_sha"]
        and run["repository"] == requested["repository"]
        and run["status"] == "completed"
        and run["conclusion"] == "success",
        "Provider receipt is not the fixed completed producer",
    )
    entries = receipt["artifacts"]
    c.need(
        len(entries) == 20
        and {row["request"]["role"] for row in entries}
        == {row["role"] for row in requested["artifacts"]},
        "Incomplete provider acquisition population",
    )
    index = {}
    for ordinal, row in enumerate(entries, 1):
        expected = next(
            item
            for item in requested["artifacts"]
            if item["role"] == row["request"]["role"]
        )
        c.need(row["request"] == expected, "Provider request changed")
        actual = row["metadata"]
        c.need(
            actual["id"] == expected["id"]
            and actual["name"] == expected["name"]
            and actual["size_in_bytes"] == expected["bytes"]
            and actual["digest"] == "sha256:" + expected["sha256"]
            and actual["expired"] is False,
            "Immutable provider identity differs",
        )
        item = {key: row["download"][key] for key in ("path", "bytes", "sha256")}
        c.need(
            item["bytes"] == expected["bytes"] and item["sha256"] == expected["sha256"],
            "Downloaded ZIP identity differs",
        )
        c.need(
            Path(item["path"])
            == Path(request_item["path"]).parent
            / "artifacts"
            / f"{ordinal:02d}-{expected['id']}.zip",
            "Provider receipt points outside its fresh download directory",
        )
        c.checked(item)
        index[expected["role"]] = {"provider": expected, "download": item}
    return index


def sdk_identity():
    root = Path("/work/transport-sdk")
    source = c.SOURCE / "operational/parameter_field_recovery07"
    metadata = {}
    for name in ("package.json", "package-lock.json"):
        expected, actual = c.descriptor(source / name), c.descriptor(root / name)
        c.need(
            all(expected[k] == actual[k] for k in ("bytes", "sha256")),
            "Fresh SDK lock metadata differs",
        )
        metadata[name] = {k: actual[k] for k in ("bytes", "sha256")}
    installed = c.read(
        c.descriptor(root / "node_modules/@actions/artifact/package.json")
    )
    c.need(
        installed["name"] == "@actions/artifact" and installed["version"] == "6.2.0",
        "Fresh reference SDK version differs",
    )
    entry = c.descriptor(root / "node_modules/@actions/artifact/lib/artifact.js")
    return {"root": str(root), "metadata": metadata, "entry_sha256": entry["sha256"]}


class PortableArchives:
    def __init__(self, downloads, sdk, original):
        self.downloads, self.sdk, self.original = downloads, sdk, original
        self.verified = []

    def verify_ack(
        self, metadata, row, binding, expected_identity=None, *, terminal=False
    ):
        original = self.original
        ack_path = metadata.check(row["ack"])
        ack = metadata.read(row["ack"])
        expected_schema = (
            "hepta.github-actions-terminal-ack.v1"
            if terminal
            else "hepta.github-actions-archive-ack.v1"
        )
        c.need(
            ack.get("schema") == expected_schema
            and ack.get("binding") == row.get("binding") == binding
            and set(binding)
            == {
                "execution_episode",
                "sequence",
                "label",
                "pipeline_config",
                "completed_jobs",
                "previous_ack",
            },
            "ACK episode, sequence or exact binding differs",
        )
        identity = ack["identity"]
        c.need(
            identity == expected_identity
            and set(identity)
            == {"repository", "run_id", "run_attempt", "head_sha", "job"},
            "ACK producer identity differs",
        )
        for key in ("manifest", "logical_files", "items_verified", "cost", "artifact"):
            c.need(ack.get(key) == row.get(key), "ACK return differs: " + key)
        role = "terminal_metadata" if terminal else "barrier:" + binding["label"]
        entry = self.downloads[role]
        artifact = ack["artifact"]
        c.need(
            {k: artifact[k] for k in ("id", "name", "bytes", "sha256")}
            == {k: entry["provider"][k] for k in ("id", "name", "bytes", "sha256")},
            "ACK differs from actually downloaded immutable provider artifact",
        )
        expected_name = f"hepta-r07-{identity['run_id']}-{identity['run_attempt']}-{binding['label']}"
        c.need(
            artifact["name"] == expected_name
            and artifact["sdk"] == "@actions/artifact@6.2.0"
            and artifact["sdk_source"] == self.sdk
            and artifact["requested_retention_days"] == 90
            and re.fullmatch(r"v24\.[0-9]+\.[0-9]+", artifact["node"]),
            "Historical SDK provenance differs",
        )
        returned = ack["readback"]
        client = returned["client"]
        c.need(
            returned["all_sha256_and_bytes_match"] is True
            and all(
                returned["raw_archive"][k] == artifact[k] for k in ("bytes", "sha256")
            )
            and client["id"] == artifact["id"]
            and client["expected_sha256"] == artifact["sha256"]
            and client["digest_mismatch"] is False
            and client["raw_archive"] is True
            and client["sdk"] == artifact["sdk"]
            and client["sdk_source"] == self.sdk,
            "Historical finalized readback identity differs",
        )
        manifest = metadata.read(ack["manifest"])
        files = ack["logical_files"]
        c.need(
            manifest["schema"] == "hepta.github-actions-archive-manifest.v1"
            and manifest["binding"] == binding
            and manifest["identity"] == identity
            and manifest["files"] == files
            and manifest["file_count"] == ack["items_verified"] == len(files)
            and 0 < len(files) <= 20000
            and len({v["path"] for v in files}) == len(files)
            and manifest["payload_bytes"] == sum(v["bytes"] for v in files),
            "Archive manifest population differs",
        )
        proofs = returned["independent_device_inodes"]
        c.need(
            len(proofs) == len(files)
            and len({p["path"] for p in proofs}) == len(proofs)
            and {p["path"] for p in proofs} == {f["path"] for f in files},
            "Historical independence proof population differs",
        )
        for proof in proofs:
            tuples = [
                proof[k]
                for k in (
                    "source_device_inode",
                    "staged_device_inode",
                    "readback_device_inode",
                )
            ]
            c.need(
                all(
                    type(value) is list
                    and len(value) == 2
                    and all(type(n) is int and n >= 0 for n in value)
                    for value in tuples
                )
                and len({tuple(value) for value in tuples}) == 3,
                "Historical copies were not three independent inodes",
            )
        archive = Archive(
            entry["download"],
            maximum_bytes=2 * c.GIB + 2 * 1024**2,
            maximum_files=60001,
        )
        try:
            expected = {"MANIFEST.json"} | {"payload/" + item["path"] for item in files}
            c.need(
                set(archive.files) == expected,
                "Downloaded ZIP has extra or missing payloads",
            )
            for member in archive.zip.infolist():
                c.need(
                    not member.is_dir()
                    or any(name.startswith(member.filename) for name in expected),
                    "Downloaded ZIP has an unrelated directory",
                )
            c.need(
                archive.json("MANIFEST.json", ack["manifest"]) == manifest,
                "Downloaded archive manifest differs",
            )
            for item in files:
                c.relative(item["path"])
                c.need(
                    type(item["bytes"]) is int
                    and item["bytes"] >= 0
                    and re.fullmatch("[0-9a-f]{64}", item["sha256"] or ""),
                    "Malformed archived file identity",
                )
                archive.member("payload/" + item["path"], item)
            previous = binding["previous_ack"]
            if previous is not None:
                logical = (
                    "ops/"
                    + Path(previous["path"]).relative_to(c.RUN / "ops").as_posix()
                )
                c.need(
                    any(
                        item["path"] == logical
                        and all(item[k] == previous[k] for k in ("bytes", "sha256"))
                        for item in files
                    ),
                    "Actual archive omitted its previous ACK bytes",
                )
        finally:
            archive.close()
        directory = ack_path.parent
        c.need(not (directory / "FAILED.json").exists(), "Historical archive failed")
        waits = ack["cost"]["wait4"]
        c.need(
            len(waits) == 2
            and [v["operation"] for v in waits] == ["upload", "download"],
            "Historical transport wait4 population differs",
        )
        for value in waits:
            operation = value["operation"]
            result = metadata.file(directory / (operation + ".result.json"))
            c.need(
                value == metadata.file(directory / (operation + ".wait4.json"))
                and value["measurement"] == "os.wait4 direct owned child"
                and value["exit_code"] == 0
                and value["timed_out"] is False
                and value["interruption_type"] is None
                and value["pid"] == value["waited_pid"]
                and type(value["pid"]) is int
                and value["pid"] > 0
                and all(
                    original.nonnegative(value[k])
                    for k in (
                        "wall_seconds",
                        "user_cpu_seconds",
                        "system_cpu_seconds",
                        "peak_rss_bytes",
                    )
                )
                and result.get("ok") is True
                and result.get("operation") == operation
                and result.get("result")
                == (artifact if operation == "upload" else client),
                "Historical transport child did not close successfully",
            )
        cost = ack["cost"]
        child_cpu = sum(v["user_cpu_seconds"] + v["system_cpu_seconds"] for v in waits)
        c.need(
            all(
                original.nonnegative(cost[k])
                for k in (
                    "wall_seconds",
                    "cpu_seconds",
                    "transport_child_cpu_seconds",
                    "parent_self_cpu_delta_seconds",
                )
            )
            and math.isclose(
                cost["transport_child_cpu_seconds"], child_cpu, abs_tol=1e-9
            )
            and math.isclose(
                cost["cpu_seconds"],
                child_cpu + cost["parent_self_cpu_delta_seconds"],
                abs_tol=1e-9,
            ),
            "Historical transport CPU attribution differs",
        )
        self.verified.append(
            {
                "role": role,
                "provider": entry["provider"],
                "new_download": entry["download"],
                "original_ack": row["ack"],
                "literal_members_verified": len(files),
                "original_inode_tuples_are_historical_only": True,
                "current_zip_device_inode": list(
                    c.fingerprint(Path(entry["download"]["path"]))[:2]
                ),
            }
        )
        return ack


def adapted_operational_gate(original, archive_verifier, *args):
    function = original.operational_gate
    before = dict(function.__globals__)
    private = dict(before)
    private["verify_ack"] = archive_verifier
    c.need(
        {key for key in private if private[key] is not before[key]} == {"verify_ack"},
        "Portable adaptation changed an undeclared dependency",
    )
    wrapper = types.FunctionType(
        function.__code__,
        private,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )
    wrapper.__kwdefaults__ = function.__kwdefaults__
    try:
        return wrapper(*args)
    finally:
        c.need(
            function.__code__ is wrapper.__code__
            and set(function.__globals__) == set(before)
            and all(function.__globals__[key] is value for key, value in before.items())
            and set(private) == set(before)
            and private["verify_ack"] is archive_verifier
            and all(
                private[key] is value
                for key, value in before.items()
                if key != "verify_ack"
            ),
            "Original operational globals or code identity changed",
        )


def final_review_closure(
    original, metadata, binding, config, config_item, terminal_item, science_gate
):
    post_item, life_item = (
        binding["pins"][key] for key in ("postseal_complete", "lifecycle_complete")
    )
    post = metadata.read(post_item)
    c.need(
        post["schema"] == "hepta.execution07.postseal-review.1"
        and post["complete"] is True
        and post["execution_episode"] == c.SOURCE_EPISODE
        and post["pipeline_config"] == config_item
        and post["terminal_closure"] == terminal_item
        and post["original_scientific_analysis_changed"] is False
        and post["new_bootstrap_training_scoring_refitting"] is False
        and post["certificate"] is False,
        "Original postseal completion did not seal the same complete run",
    )
    historical_gate = post["primary_scientific_gate"]
    c.need(
        all(
            historical_gate[key] == science_gate[key]
            for key in (
                "status",
                "execution_episode",
                "controller_jobs",
                "completion_seals",
                "original_source_files_verified",
                "pipeline",
                "verified",
                "manifest",
                "finalizer_freeze",
            )
        ),
        "Postseal original gate bindings differ",
    )
    outputs = post["outputs"]
    c.need(
        type(outputs) is dict
        and {"UNIFIED_REVIEW.json", "INPUTS.json"} <= set(outputs),
        "Postseal output closure is incomplete",
    )
    for name, item in outputs.items():
        c.need(
            Path(item["path"]) == c.RUN / "postseal" / name and Path(name).name == name,
            "Postseal output path changed",
        )
        metadata.check(item)
    argv = [
        config["python"],
        "-B",
        str(c.SOURCE / "operational/parameter_field_recovery07/postseal/review.py"),
        "--config",
        config_item["path"],
        "--expected-config-sha256",
        config_item["sha256"],
        "--terminal-closure",
        terminal_item["path"],
        "--expected-terminal-closure-sha256",
        terminal_item["sha256"],
        "--output",
        str(c.RUN / "postseal"),
        "--execute-post-seal",
    ]
    review_cost = original.wait4(
        metadata, c.RUN / "postseal_measurement", config_item=config_item, argv=argv
    )
    lifecycle = metadata.read(life_item)
    c.need(
        Path(lifecycle["child_completion"]["path"])
        == c.RUN / "pipeline_measurement/CHILD_COMPLETE.json",
        "Lifecycle child receipt moved outside its registered measurement",
    )
    child = metadata.read(lifecycle["child_completion"])
    c.need(
        lifecycle["schema"] == "hepta.execution07.lifecycle-completion.1"
        and lifecycle["complete"] is True
        and lifecycle["execution_episode"]
        == child["execution_episode"]
        == c.SOURCE_EPISODE
        and child["schema"] == "hepta.execution07.lifecycle-child.1"
        and child["complete"] is True
        and lifecycle["source_commit"] == config["source_commit"]
        and lifecycle["engineering_status"]
        == "ALL_REGISTERED_STAGES_AND_REVIEW_CLOSED",
        "Full original lifecycle did not close",
    )
    for value in (lifecycle, child):
        c.need(
            value["pipeline_config"] == config_item
            and value["primary_completion"] == binding["pins"]["primary_complete"]
            and value["terminal_closure"] == terminal_item
            and value["postseal_completion"] == post_item
            and value["scientific_review_disposition"] == post["status"]
            and value["postseal_measurement"]
            == {k: review_cost[k] for k in ("wait4", "closure")},
            "Lifecycle chooses different review, measurement or primary bytes",
        )
    argv = [
        config["python"],
        "-B",
        str(c.SOURCE / "operational/parameter_field_recovery07/bootstrap.py"),
        "--source-commit",
        config["source_commit"],
        "--child",
    ]
    outer = original.wait4(metadata, c.RUN / "pipeline_measurement/children", argv=argv)
    c.need(
        lifecycle["pipeline_measurement"]
        == {k: outer[k] for k in ("wait4", "closure")},
        "Original inclusive lifecycle wait4 differs",
    )
    c.need(
        all(
            math.isclose(
                lifecycle["inclusive_pipeline_" + kind + "_seconds"],
                outer[kind + "_seconds"],
                abs_tol=1e-9,
            )
            for kind in ("cpu", "wall")
        )
        and lifecycle["pipeline_peak_rss_bytes"] == outer["peak_rss_bytes"],
        "Original lifecycle timing attribution differs",
    )
    return {
        "postseal_completion": post_item,
        "lifecycle_completion": life_item,
        "original_postseal_disposition": post["status"],
        "original_integrity_issues": post["integrity_issues"],
        "historical_integrity": post["historical_integrity"],
        "postseal_wait4": review_cost,
        "inclusive_pipeline_wait4": outer,
        "output_files_byte_verified": len(outputs),
    }


def admit(binding, downloads, current_runtime, output, *, replay_identity):
    """All completion/source/archive gates finish before returning an admitted store."""
    c.original_source(binding)
    for item in binding["pins"].values():
        c.checked(item)
    original = importlib.import_module(
        "operational.parameter_field_recovery07.postseal.review"
    )
    c.need(
        Path(original.__file__).resolve()
        == c.SOURCE / "operational/parameter_field_recovery07/postseal/review.py",
        "Imported original review from another checkout",
    )
    source_before = c.descriptor(Path(original.__file__).resolve())
    config_item, terminal_item = (
        binding["pins"][key] for key in ("pipeline_config", "terminal_closure")
    )
    config, unchanged = original.c.load_config(
        config_item["path"], config_item["sha256"]
    )
    c.need(
        unchanged == config_item
        and config["source_commit"] == binding["provider"]["head_sha"],
        "Original config source differs",
    )
    expected_identity = {
        "repository": binding["provider"]["repository"],
        "run_id": str(binding["provider"]["run_id"]),
        "run_attempt": str(binding["provider"]["run_attempt"]),
        "head_sha": binding["provider"]["head_sha"],
        "job": binding["producer_job"],
    }
    c.need(
        config["actions_identity"] == expected_identity,
        "Original producer differs from external binding",
    )
    contract = c.read(
        c.descriptor(
            c.SOURCE / "operational/parameter_field_recovery07/INPUT_CONTRACT.json"
        )
    )
    c.need(
        str(Path(sys.executable).absolute()) == contract["python"]
        and sys.version == contract["runtime_expected"]["descriptor"]["python"],
        "Replay interpreter differs from the fixed public build",
    )
    for item in contract["public_python_files"]:
        path = Path(contract["python_base"]) / Path(item["name"]).relative_to("python")
        c.checked({"path": str(path), "bytes": item["size"], "sha256": item["sha256"]})
    c.need(
        current_runtime["runtime"]["exact_match"] is True
        and current_runtime["runtime"]["runtime_sha256"]
        == contract["runtime_expected"]["runtime_sha256"]
        and current_runtime["three_original_joint_passes"] is True
        and current_runtime["process"]["supported"] is True
        and current_runtime["runtime"]["model_created"] is False
        and current_runtime["runtime"]["scientific_inputs_opened"] is False,
        "Current independent replay runtime was not qualified",
    )
    asset_evidence = asset_replay.restore(
        original, config, config_item, replay_identity, output
    )
    metadata = original.Metadata()
    verifier = PortableArchives(downloads, sdk_identity(), original)
    complete, operations = adapted_operational_gate(
        original, verifier.verify_ack, config, config_item, terminal_item, metadata
    )
    c.need(
        len(verifier.verified) == 18
        and complete["artifacts"]["manifest"] == binding["pins"]["manifest"]
        and complete["artifacts"]["verified"] == binding["pins"]["verified"],
        "External primary/finalizer selection differs",
    )
    supplement = original.original_supplement(config)
    inputs = supplement.Inputs()
    plan, store, protocol, science_gate = supplement.gate(
        original.science_gate_args(config, complete), inputs, output
    )
    closure = final_review_closure(
        original, metadata, binding, config, config_item, terminal_item, science_gate
    )
    metadata.stable()
    c.need(
        c.descriptor(Path(original.__file__).resolve()) == source_before,
        "Original operational source changed",
    )
    return {
        "store": store,
        "inputs": inputs,
        "metadata": metadata,
        "supplement": supplement,
        "protocol": protocol,
        "receipt": {
            "schema": "hepta.parameter-field.portable-admission.1",
            "complete": True,
            "original_scientific_gate": science_gate,
            "original_operational_metadata_checks": operations,
            "portable_archive_adaptation": "Isolated function globals copy substitutes only verify_ack; original module globals/code and canonical source/paths unchanged.",
            "old_inode_numbers_reproduced_on_new_host": False,
            "new_downloads": verifier.verified,
            "fresh_inputs_and_historical_asset_metadata": asset_evidence,
            "full_original_postseal_and_lifecycle": closure,
            "original_review_source": source_before,
            "scientific_trace_or_checkpoint_decoded_before_all_gates": False,
        },
    }
