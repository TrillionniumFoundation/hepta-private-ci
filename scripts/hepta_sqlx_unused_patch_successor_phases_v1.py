"""The remaining tool, successor-lock and graph phases; no standalone activation."""

import io
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tomllib
import zipfile


ORIGINAL_IDENTITY_MEMBER = "prepare-finish.RESULT.json"
ORIGINAL_IDENTITY_PIN = {
    "bytes": 22883,
    "sha256": "d47a64cacb884c0d99301db51e6b1d41cbdabaabd9f9f0088efa92bd6d32a5a1",
}


def _retained_original_inputs(data):
    return (*data.RETAINED.items(), (ORIGINAL_IDENTITY_MEMBER, ORIGINAL_IDENTITY_PIN))


def _verify_original_failure(prior_result, prior_prepared, data):
    data.require(
        isinstance(prior_result, dict)
        and prior_result.get("status") == "FAIL"
        and prior_result.get("mode") == "complete"
        and prior_result.get("original_checkout_unchanged") is True
        and prior_result.get("error")
        == "ValueError: actual command failed: default-locked-filtered-graph-offline-once",
        "failed origin was reclassified",
    )
    source = prior_prepared.get("source") if isinstance(prior_prepared, dict) else None
    data.require(
        isinstance(prior_prepared, dict)
        and prior_prepared.get("status") == "TOOLS_PREPARED_ONLY"
        and prior_prepared.get("mode") == "prepare-finish"
        and prior_prepared.get("error") is None
        and isinstance(source, dict)
        and source.get("head") == data.PARENT
        and source.get("tree") == data.PARENT_TREE,
        "original preparation identity differs",
    )


def prepare(scope, old, data, helper, identity):
    steps = old.strict_json(os.environ["LOCK_ALL_STEPS"])
    old.require(steps["rust"]["outcome"] == "success", "original compiler setup failed")
    tools = {
        name: helper.tool_file(Path(shutil.which(name) or ""))
        for name in ("git", "rustup", "gh", "curl")
    }
    tools["python"] = helper.tool_file(Path(sys.executable))
    for name in ("cargo", "rustc"):
        out, _ = scope.run(
            "locate-original-" + name,
            [tools["rustup"]["path"], "which", "--toolchain", "1.96.0", name],
            scope.source,
            5,
        )
        lines = out.read_text().splitlines()
        old.require(
            len(lines) == 1 and Path(lines[0]).is_absolute(),
            "ambiguous original compiler",
        )
        tools[name] = helper.tool_file(Path(lines[0]))
        old.require(
            {k: tools[name][k] for k in ("bytes", "sha256")} == old.FROZEN_RUST[name],
            "original tool bytes differ",
        )
    out, _ = scope.run(
        "original-cargo-version", [tools["cargo"]["path"], "--version"], scope.source, 5
    )
    old.require(
        out.read_text().startswith("cargo 1.96.0 "), "original Cargo version differs"
    )
    out, _ = scope.run(
        "original-rustc-version",
        [tools["rustc"]["path"], "--version", "--verbose"],
        scope.source,
        5,
    )
    text = out.read_text()
    old.require(
        text.startswith("rustc 1.96.0 ")
        and "\nhost: x86_64-unknown-linux-gnu\n" in text,
        "original compiler or host differs",
    )
    archive, _ = scope.run(
        "original-failed-artifact-once",
        [
            tools["gh"]["path"],
            "api",
            "--hostname",
            "github.com",
            f"repos/{data.REPO}/actions/artifacts/{data.ORIGIN['artifact_id']}/zip",
        ],
        scope.source,
        30,
    )
    old.require(
        data.pin(old.read_regular(archive, 16 * 1024 * 1024)) == data.ARCHIVE,
        "original artifact differs",
    )
    originals = scope.evidence / "original-failed-inputs"
    originals.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        old.require(
            len(names) == len(set(names)) == 148, "original ZIP member roster differs"
        )
        for index, (name, expected) in enumerate(_retained_original_inputs(data)):
            member = bundle.getinfo(name)
            old.require(
                member.file_size == expected["bytes"],
                "retained original member size differs",
            )
            raw = bundle.read(member)
            old.require(
                data.pin(raw) == expected, "retained original member hash differs"
            )
            with (originals / str(index)).open("xb") as output:
                output.write(raw)
    payload, _ = scope.run(
        "official-cargo-payload-once",
        [
            tools["curl"]["path"],
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-time",
            "30",
            "--retry",
            "0",
            "--max-filesize",
            "67108864",
            data.CARGO_URL,
        ],
        scope.source,
        35,
    )
    raw = old.read_regular(payload, 64 * 1024 * 1024)
    old.require(
        old.digest(raw) == data.CARGO_ARCHIVE_SHA, "official Cargo payload differs"
    )
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as bundle:
        entries = bundle.getmembers()
        old.require(
            len(entries) <= 10000
            and len({e.name for e in entries}) == len(entries)
            and sum(e.size for e in entries) <= 256 * 1024 * 1024,
            "Cargo archive bound differs",
        )
        member = bundle.getmember(
            "cargo-nightly-x86_64-unknown-linux-gnu/cargo/bin/cargo"
        )
        old.require(
            member.isfile() and 0 < member.size <= 64 * 1024 * 1024,
            "Cargo binary archive entry differs",
        )
        binary = bundle.extractfile(member).read(64 * 1024 * 1024 + 1)
        old.require(len(binary) == member.size, "Cargo binary extraction differs")
    target = scope.stage / "official-cargo"
    with target.open("xb") as output:
        output.write(binary)
    target.chmod(0o700)
    tools["fixture_cargo"] = helper.tool_file(target)
    out, _ = scope.run(
        "official-cargo-version",
        [str(target), "--version", "--verbose"],
        scope.source,
        5,
    )
    version = out.read_text()
    old.require(
        version.startswith("cargo " + data.CARGO_RELEASE + " ")
        and "\ncommit-hash: " + data.CARGO_COMMIT + "\n" in version
        and "\nhost: x86_64-unknown-linux-gnu\n" in version,
        "official Cargo identity differs",
    )
    caps = {
        "locate-original-cargo": 5,
        "locate-original-rustc": 5,
        "original-cargo-version": 5,
        "original-rustc-version": 5,
        "original-failed-artifact-once": 30,
        "official-cargo-payload-once": 35,
        "official-cargo-version": 5,
    }
    observed = [row for row in scope.commands if row["label"] in caps]
    old.require(
        len(observed) == len(caps)
        and {r["label"] for r in observed} == set(caps)
        and all(0 <= row["elapsed_seconds"] <= caps[row["label"]] for row in observed),
        "tool command count or original cap differs",
    )
    return {
        "status": "TOOLS_AND_ORIGINALS_PREPARED",
        "source": identity,
        "tools": tools,
        "path_environment": os.environ["PATH"],
        "original_archive": {"file": archive.name, **data.ARCHIVE},
        "official_payload": {"file": payload.name, **data.pin(raw)},
        "actual_tool_compatibility_not_yet_qualified": True,
    }


def generate(scope, old, data, helper, runtime, prior, identity, state):
    prepared = old.strict_json(old.read_regular(scope.evidence / "prepare.RESULT.json"))
    old.require(
        prepared["status"] == "TOOLS_AND_ORIGINALS_PREPARED"
        and prepared["source"] == identity
        and prepared["elapsed_seconds"] <= data.BUDGET["tool_preparation_seconds"]
        and prepared["path_environment"] == os.environ["PATH"],
        "original tool preparation did not pass",
    )
    tools = prepared["tools"]
    for row in tools.values():
        old.require(helper.tool_file(Path(row["path"])) == row, "prepared tool changed")
    before = runtime.source_snapshot(scope, scope.source, identity["tree"])
    runtime.require_tree(before, "source")
    state.update(before=before, identity=identity)
    old.put(scope.evidence / "source-before.json", before)
    work, routing = helper.create_work_copy(scope, runtime, identity, tools)
    state["work"] = work
    old.require(
        runtime.source_snapshot(scope, work, identity["tree"]) == before,
        "copied source differs",
    )
    contract = old.module(
        work / old.CONTRACT_PATH, old.CONTRACT_SHA, "sqlx_order_graph"
    )
    contract.check_fixture_declarations()
    retained = _retained_original_inputs(data)
    originals = [
        old.read_regular(scope.evidence / "original-failed-inputs" / str(i))
        for i in range(len(retained))
    ]
    old.require(
        all(
            data.pin(raw) == expected
            for raw, (_, expected) in zip(originals, retained, strict=True)
        ),
        "retained original input changed",
    )
    prior_result = old.strict_json(originals[2])
    prior_prepared = old.strict_json(originals[3])
    _verify_original_failure(prior_result, prior_prepared, data)
    baseline, seed = (
        tomllib.loads(originals[1].decode()),
        old.read_regular(work / "codex-rs/Cargo.lock"),
    )
    main = {p: data.pin(old.read_regular(work / p)) for p in prior.MAIN_LOCKS}
    old.require(main == prior.MAIN_LOCKS, "accepted main lock bytes differ")
    cache = scope.stage / "cargo-home-successor"
    cache.mkdir()
    env = {
        "CARGO_HOME": str(cache),
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "RUSTC": tools["rustc"]["path"],
        "RUSTC_WRAPPER": "",
        "RUSTC_WORKSPACE_WRAPPER": "",
        "CARGO_NET_RETRY": "0",
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    plan = data.command_plan(
        tools["fixture_cargo"]["path"], tools["cargo"]["path"], work
    )
    old.put(
        scope.evidence / "exact-command-plan.json",
        {"commands": plan, "compiler": tools["rustc"]},
    )

    def run(index, label):
        name, argv, cap = plan[index]
        extra = {
            "CARGO_TARGET_DIR": str(scope.stage / ("target-" + label)),
            "CARGO_NET_OFFLINE": "false" if index == 0 else "true",
        }
        out, _ = scope.run(name, argv, work / "codex-rs", cap, {**env, **extra})
        old.require(
            scope.commands[-1]["elapsed_seconds"] <= cap, "command cap exceeded"
        )
        return out

    run(0, "cache")
    old.require(
        {p: data.pin(old.read_regular(work / p)) for p in main} == main,
        "cache recovery changed a main lock",
    )
    fixtures = {}
    for label, relative, name, compatibility in contract.FIXTURES:
        lock = work / relative / "Cargo.lock"
        original = seed if compatibility else originals[0]
        prior.copy_seed(original, lock, data.pin(original))
        if not compatibility:
            emitted = old.strict_json(old.read_regular(run(1, label), 64 * 1024 * 1024))
            successor = old.read_regular(lock)
            delta = data.order_only(original, successor)
            old.require(
                delta["records_including_duplicates"] == 10,
                "original unused-record count differs",
            )
            old.put(scope.evidence / "default-successor-only-order.json", delta)
        else:
            run(3, label)
        candidate = old.read_regular(lock)
        relation = contract.lock_relation(
            baseline, tomllib.loads(candidate.decode()), name
        )
        old.put(scope.evidence / (label + "-lock-relation.json"), relation)
        out = run(4 if compatibility else 2, label)
        old.require(
            old.read_regular(lock) == candidate,
            "strict --locked metadata changed the fixture lock",
        )
        observed = old.strict_json(old.read_regular(out, 64 * 1024 * 1024))
        if not compatibility:
            data.same_graph(emitted, observed)
        normalized, observation = contract.fixture_observation(
            observed, tomllib.loads(candidate.decode()), name, compatibility
        )
        observation.update(
            lock=data.pin(candidate),
            original_metadata={"file": out.name, **data.pin(out.read_bytes())},
            normalized_graph_file=old.put(
                scope.evidence / (label + "-normalized-graph.json"), normalized
            ),
        )
        fixtures[label] = observation
    old.require(
        runtime.source_snapshot(scope, work, identity["tree"]) == before
        and {p: data.pin(old.read_regular(work / p)) for p in main} == main,
        "generated work changed tracked source or main locks",
    )
    old.require(
        scope.read_git(work, "rev-parse", "HEAD").decode().strip() == identity["head"]
        and all(
            old.read_regular(work / (".git/" + p)) == routing[k]
            for p, k in (
                ("shallow", "shallow"),
                ("objects/info/alternates", "alternates"),
                ("config", "config"),
            )
        )
        and not scope.read_git(work, "diff", "--cached", "--name-only")
        and all(
            row.startswith(b"H ")
            for row in scope.read_git(work, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "isolated Git identity changed",
    )
    old.require(
        helper.check_untracked_outputs(scope, work)["bazel_links"] == [],
        "unexpected Bazel outputs",
    )
    locks = helper.retain_lock_set(
        scope, work, scope.evidence / "candidate-locks", helper.LOCKS
    )
    for label, relative in prior.FIXTURES:
        old.require(
            locks[relative + "/Cargo.lock"] == fixtures[label]["lock"],
            "retained lock and graph differ",
        )
    old.require(
        all(
            data.pin(
                old.read_regular(scope.evidence / "original-failed-inputs" / str(i))
            )
            == pin
            for i, (_, pin) in enumerate(retained)
        ),
        "original failed inputs changed",
    )
    for key in ("original_archive", "official_payload"):
        row = prepared[key]
        old.require(
            Path(row["file"]).name == row["file"]
            and data.pin(
                old.read_regular(scope.evidence / row["file"], 64 * 1024 * 1024)
            )
            == {k: row[k] for k in ("bytes", "sha256")},
            "original archive or official payload changed",
        )
    for row in tools.values():
        old.require(
            helper.tool_file(Path(row["path"])) == row, "tool changed during generation"
        )
    return {
        "status": "SUCCESSOR_CANDIDATES_REQUIRES_ROOT_REVIEW",
        "source": identity,
        "lock_postimages": locks,
        "fixture_graphs": fixtures,
        "actual_cargo_commands": data.completed_commands(scope.commands, plan),
        "original_default_lock_stays_failed": True,
        "successor_is_not_original_17e4": True,
        "new_runner_cache_recoveries": 1,
        "original_default_update_replays": 0,
        "main_update_metadata_or_bazel_executions": 0,
        "old_12_or_21_controls_executions": 0,
        "native_executions": 0,
        "native_qualification": False,
        "root_four_lock_acceptance": None,
    }


def readback(scope, old, data, identity):
    steps = old.strict_json(os.environ["LOCK_ALL_STEPS"])
    old.require(
        all(
            steps[name]["outcome"] == "success"
            for name in (
                "job_scope",
                "checkout",
                "begin",
                "rust",
                "prepare",
                "generation",
            )
        ),
        "an original successor workflow step failed",
    )
    result = old.strict_json(
        old.read_regular(scope.evidence / "generation.RESULT.json")
    )
    old.require(
        result["status"] == "SUCCESSOR_CANDIDATES_REQUIRES_ROOT_REVIEW"
        and result["source"] == identity
        and result["original_checkout_unchanged"] is True
        and result["elapsed_seconds"] <= 756,
        "generation did not qualify for readback",
    )
    for path, expected in result["lock_postimages"].items():
        old.require(
            data.pin(old.read_regular(scope.evidence / "candidate-locks" / path))
            == expected,
            "retained lock changed",
        )
    for graph in result["fixture_graphs"].values():
        for key in ("original_metadata", "normalized_graph_file"):
            row = graph[key]
            old.require(
                Path(row["file"]).name == row["file"]
                and data.pin(
                    old.read_regular(scope.evidence / row["file"], 64 * 1024 * 1024)
                )
                == {k: row[k] for k in ("bytes", "sha256")},
                "retained graph changed",
            )
    old.require(
        set(result["lock_postimages"])
        == {
            "codex-rs/Cargo.lock",
            "MODULE.bazel.lock",
            "qualification/sqlx_temporal_default_v1/Cargo.lock",
            "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.lock",
        }
        and set(result["fixture_graphs"]) == {"default", "compatibility"},
        "four locks or two graphs are absent",
    )
    return {
        "status": "SUCCESSOR_CANDIDATES_REQUIRES_ROOT_REVIEW",
        "native_qualification": False,
        "cumulative_generation_seconds": result["cumulative_generation_seconds"],
        "full_job_and_upload_cost_still_required": True,
    }
