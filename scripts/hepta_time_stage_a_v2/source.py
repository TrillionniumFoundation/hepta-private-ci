"""Freeze exact publication inputs and complete physical source before engineering."""

import os
from pathlib import Path
import re
import time

from . import contract as c
from .runtime import (
    json_value,
    leaf_pin,
    put,
    put_raw,
    read_json,
    relative,
    require,
    sha256,
    stable_read,
)


def validate_event(ctx, spec):
    require(
        os.environ.get("GITHUB_REPOSITORY") == c.REPOSITORY
        and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
        "only one original same-repository pull_request attempt is allowed",
    )
    event_raw, _ = stable_read(Path(os.environ["GITHUB_EVENT_PATH"]), 4 * 1024 * 1024)
    event = json_value(event_raw)
    pr = event["pull_request"]
    require(
        event["action"] == "opened"
        and pr["draft"] is True
        and pr["user"]["login"] == "ProfHepta"
        and pr["head"]["repo"]["full_name"] == c.REPOSITORY
        and pr["head"]["ref"] == spec["branch"]
        and pr["head"]["sha"] == os.environ["STAGE_A_GENERATION_HEAD"],
        "event is not the frozen first-open draft candidate",
    )
    return {
        "github_sha": os.environ["GITHUB_SHA"],
        "github_ref": os.environ["GITHUB_REF"],
        "github_event_name": os.environ["GITHUB_EVENT_NAME"],
        "github_run_id": os.environ["GITHUB_RUN_ID"],
        "github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "github_job": os.environ["GITHUB_JOB"],
        "event_bytes": len(event_raw),
        "event_sha256": sha256(event_raw),
        "generation_head": pr["head"]["sha"],
        "head_branch": pr["head"]["ref"],
        "pull_request_number": event["number"],
        "action": "opened",
    }, event_raw


def load_inputs(ctx):
    raw, _ = stable_read(ctx.root / c.INPUTS, 1024 * 1024)
    spec = json_value(raw)
    require(
        spec["schema"] == "hepta.time-utc-stage-a-generation-inputs.v2"
        and spec["activated"] is True
        and spec["activation_blockers"] == []
        and spec["root_admission"]["authorizer"] == "root"
        and spec["root_admission"]["engineering_execution_authorized"] is True
        and spec["root_admission"]["source_preparation_only"] is False
        and spec["root_admission"]["local_candidate_only"] is True
        and spec["root_admission"]["github_write_authorized"] is False,
        "Stage A engineering registration is inactive",
    )
    require(
        spec["publication_roster_complete_for_future_combined_candidate"] is True
        and type(spec["root_admission"]["receipt_path"]) is str
        and bool(spec["root_admission"]["receipt_path"])
        and type(spec["root_admission"]["receipt_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", spec["root_admission"]["receipt_sha256"])
        is not None,
        "final Root admission receipt or combined publication roster absent",
    )
    require(
        spec["repository"] == c.REPOSITORY
        and spec["parent"] == c.BASE
        and spec["parent_tree"] == c.BASE_TREE
        and spec["budgets"] == c.BUDGETS
        and spec["phase_caps_seconds"] == c.PHASE_CAPS
        and spec["tooling"] == c.EXPECTED_TOOLS
        and spec["qualifications"] == c.FALSE_QUALIFICATION,
        "frozen identity, budget, tool, or qualification scope changed",
    )
    require(
        spec["stage_paths"] == list(c.STAGE_PATHS)
        and spec["generated_lock_paths"] == list(c.LOCK_PATHS)
        and spec["controls"]
        == [{"binary_id": a, "name": b} for a, b in c.EXPECTED_PAIRS]
        and spec["native_command"] == c.native_command()
        and spec["native_list_command"] == c.native_list_command(),
        "utility controls, paths, or exact commands changed",
    )
    publication = spec["publication_paths"]
    mandatory = {c.OWNER, c.INPUTS, c.WORKFLOW, *c.MODULE_PATHS} | {
        c.PROPOSAL + path.replace("/", "__") + ".source" for path in c.STAGE_PATHS
    }
    require(
        type(publication) is list
        and publication == sorted(set(publication))
        and mandatory <= set(publication)
        and all(relative(p) for p in publication),
        "final publication roster is not concrete and exact",
    )
    pins = spec["reviewed_sources"]
    require(
        type(pins) is list
        and len(pins) == len({row["path"] for row in pins})
        and c.INPUTS not in {row["path"] for row in pins},
        "repeated/circular reviewed source pin",
    )
    required = (
        mandatory - {c.INPUTS}
        | set(c.ORIGINAL_HELPERS)
        | {
            "justfile",
            "scripts/just-shell.py",
            "scripts/format.py",
            "scripts/run-nextest.py",
            "tools/buildifier",
            ".bazelversion",
            ".bazelrc",
            "MODULE.bazel",
            "defs.bzl",
            "codex-rs/Cargo.toml",
            "codex-rs/Cargo.lock",
            "MODULE.bazel.lock",
            "codex-rs/.config/nextest.toml",
            "codex-rs/.cargo/config.toml",
            "codex-rs/rust-toolchain.toml",
        }
    )
    require(
        required <= {row["path"] for row in pins},
        "an original execution or proposal input is not pinned",
    )
    for row in pins:
        name = relative(row["path"])
        data, info = stable_read(ctx.root / name)
        require(
            leaf_pin(data, row["mode"])
            == {k: row[k] for k in ("bytes", "sha256", "git_blob", "mode")}
            and row["mode"] in ("100644", "100755")
            and bool(info.st_mode & 0o111) == (row["mode"] == "100755"),
            "reviewed input changed: " + name,
        )
    require(
        spec["proposal_files"]
        and len(spec["proposal_files"]) == 6
        and [row["target"] for row in spec["proposal_files"]] == list(c.STAGE_PATHS),
        "proposal source roster changed",
    )
    for row in spec["proposal_files"]:
        require(
            row["proposal"] == c.PROPOSAL + row["target"].replace("/", "__") + ".source"
            and row["after"]["mode"] == "100644",
            "proposal mapping changed",
        )
        require(
            leaf_pin(proposal_bytes(ctx, row), "100644") == row["after"],
            "proposal postimage differs from reviewed Stage A",
        )
    return spec, raw


def proposal_bytes(ctx, row):
    raw, _ = stable_read(ctx.root / row["proposal"])
    require(
        leaf_pin(raw, "100644") == row["proposal_pin"], "opaque proposal source changed"
    )
    if row["target"] != "codex-rs/Cargo.toml":
        require(
            row["encoding"] == "raw-postimage" and row["before"] is None,
            "unexpected new-source encoding",
        )
        return raw
    require(
        row["encoding"] == "unique-text-edit-v1"
        and json_value(raw) == c.ROOT_MEMBER_EDIT,
        "root manifest edit is not the one reviewed member insertion",
    )
    before, _ = stable_read(ctx.root / row["target"])
    require(
        leaf_pin(before, "100644") == row["before"],
        "root manifest differs from the reviewed exact preimage",
    )
    old = c.ROOT_MEMBER_EDIT["before"].encode()
    new = c.ROOT_MEMBER_EDIT["after"].encode()
    require(before.count(old) == 1, "root member anchor is not unique")
    return before.replace(old, new, 1)


def begin(ctx):
    """Complete the old source-acquisition remainder before starting engineering."""
    start = read_json(ctx.evidence / "job-start.json")
    require(
        ctx.scope.deadline == float(start["source_started_monotonic"]) + c.SOURCE_CAP,
        "source deadline differs from the original job claim",
    )
    spec, spec_raw = load_inputs(ctx)
    event, event_raw = validate_event(ctx, spec)
    head = event["generation_head"]
    require(
        ctx.git("rev-parse", "HEAD").decode().strip() == head,
        "checkout differs from the actual pull-request head",
    )
    identity, commit_raw = ctx.commit_identity(head)
    require(
        identity["parents"] == [c.BASE], "generation head has a different sole parent"
    )
    base, base_raw = ctx.commit_identity(c.BASE)
    require(
        base["tree"] == c.BASE_TREE, "actual parent tree differs from reviewed baseline"
    )
    ctx.assert_clean()
    publication = [
        item.decode("utf-8")
        for item in ctx.git(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            c.BASE,
            head,
        ).split(b"\0")
        if item
    ]
    require(
        sorted(publication) == spec["publication_paths"],
        "actual publication changed a different path set",
    )
    snapshot = ctx.snapshot(identity["tree"])
    ctx.assert_clean()
    require(
        ctx.git("rev-parse", "HEAD").decode().strip() == head,
        "source head changed during acquisition",
    )
    put_raw(ctx.evidence / "github-event.original.json", event_raw)
    put_raw(ctx.evidence / "generation-head.commit.raw", commit_raw)
    put_raw(ctx.evidence / "generation-parent.commit.raw", base_raw)
    put_raw(ctx.evidence / "inputs.original.json", spec_raw)
    map_pin = put(ctx.evidence / "generation-source-before.json", snapshot)
    ctx.check_time()
    completed = time.monotonic()
    engineering_started = completed
    state = {
        "status": "SOURCE_ACQUIRED_ENGINEERING_ADMITTED",
        "source": identity,
        "github_event": event,
        "source_snapshot": map_pin,
        "source_started_monotonic": start["source_started_monotonic"],
        "source_completed_monotonic": completed,
        "source_elapsed_seconds": completed - start["source_started_monotonic"],
        "source_previous_seconds": c.PRIOR_SOURCE_SECONDS,
        "source_cumulative_seconds": c.PRIOR_SOURCE_SECONDS
        + completed
        - start["source_started_monotonic"],
        "source_original_cap_seconds": 300,
        "engineering_started_monotonic": engineering_started,
        "engineering_deadline_monotonic": engineering_started + c.ENGINEERING_CAP,
        "commands_deadline_monotonic": engineering_started
        + c.ENGINEERING_CAP
        - c.FINAL_RESERVE,
        "engineering_budget_seconds": c.ENGINEERING_CAP,
        "final_retention_reserve_seconds": c.FINAL_RESERVE,
        "source_end_boundary": "After complete physical tree and immutable inputs retained; subsequent state/environment IO is charged to engineering.",
        "job_setup_queue_and_post_job_costs_require_original_GitHub_readback": True,
        "source_leaf_count": len(snapshot),
        "source_total_bytes": sum(row["bytes"] for row in snapshot.values()),
        "inputs_sha256": sha256(spec_raw),
        "local_tested_identity": None,
        **c.FALSE_QUALIFICATION,
    }
    require(
        state["source_elapsed_seconds"] <= c.SOURCE_CAP
        and state["source_cumulative_seconds"] <= 300,
        "source acquisition exhausted the original remaining budget",
    )
    put(ctx.evidence / "source-admission.json", state)
    return state
