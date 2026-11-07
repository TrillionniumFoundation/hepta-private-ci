"""Bind Windows44 and reuse the frozen Windows43 v2 finite observer only."""

import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys

ROOT = Path("/workspace/scratch/3f6a885bb83c")
HERE = Path(__file__).resolve().parent
UNIT = HERE.parent / "review2"
FROZEN = ROOT / "round3_native/windows_mutation_deny_44"
PREFIX = "codex-rs/windows-sandbox-rs/src/"
HEAD = "883b85f2c0198e9373022e8082d866c080178c0a"
PARENT = "47723bb04013bf2d98647e9470561194f438a786"
TREE = "6634442bb8fb0bc8b1f86278ff4fffefdaafd23e"
CHECKOUT = "194e8fa6ba96e0b717e4ca25612b1f02720cb1cf"
RUN = 42352197933
JOB = 128343024490
MANIFEST_SHA = "0a23e41f6801511c80426eabfbcc836bb7d4101237e3fab90235f6c83ae7f079"
RAW_SHA = "afc8e0e074eb2243ad53db45a0832f93d9c496c3cb38bfece3f094522c4297cb"
EXTRA_CASES = (
    "complete_denies_compare_mapped_masks_and_require_every_right",
    "normalized_deny_pair_requires_every_right_in_effective_and_recursive_scopes",
    "fresh_write_deny_preserves_generic_read_and_denies_data_mutation",
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def read(path):
    return json.loads(path.read_bytes())


def load(name, path, sha):
    raw = path.read_bytes()
    require(identity(raw)["sha256"] == sha, "FROZEN_OBSERVER_CHANGED")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observed_source(old):
    manifest_path = UNIT / "manifest.json"
    raw = manifest_path.read_bytes()
    require(identity(raw)["sha256"] == MANIFEST_SHA, "MANIFEST_CHANGED")
    manifest = json.loads(raw)
    head = read(HERE / "HEAD_OBSERVATION1_API.json")
    checkout = read(HERE / "CHECKOUT_COMMIT_API.json")
    require(head["sha"] == HEAD and head["tree"]["sha"] == TREE, "HEAD_TREE")
    require([x["sha"] for x in head["parents"]] == [PARENT], "HEAD_PARENT")
    require(
        checkout["sha"] == CHECKOUT
        and checkout["tree"]["sha"] == TREE
        and [x["sha"] for x in checkout["parents"]] == [PARENT, HEAD],
        "CHECKOUT_SOURCE",
    )
    paths = {
        "root": "root_api.json",
        "codex": "codex_tree_api.json",
        "crate": "crate_tree_api.json",
        "src": "src_tree_api.json",
    }
    trees = {k: read(FROZEN / "source-api" / v) for k, v in paths.items()}
    for tree in trees.values():
        require(
            tree["truncated"] is False and old.tree_sha(tree["tree"]) == tree["sha"],
            "BASE_TREE_HASH",
        )
    require(
        trees["root"]["sha"] == manifest["parent"]["tree"]
        and manifest["parent"]["head"] == PARENT,
        "BASE_TREE",
    )
    edges = (
        ("root", "codex", "codex-rs"),
        ("codex", "crate", "windows-sandbox-rs"),
        ("crate", "src", "src"),
    )
    for parent, child, name in edges:
        require(
            next(x["sha"] for x in trees[parent]["tree"] if x["path"] == name)
            == trees[child]["sha"],
            "BASE_CHAIN",
        )
    proposed = {k: copy.deepcopy(v["tree"]) for k, v in trees.items()}
    require(
        {x["path"] for x in manifest["files"]}
        == {PREFIX + "acl.rs", PREFIX + "acl_tests.rs"},
        "TWO_SOURCE_SCOPE",
    )
    for item in manifest["files"]:
        name = Path(item["path"]).name
        new = Path(item["candidate"]).read_bytes()
        before = (FROZEN / "source" / item["path"]).read_bytes()
        require(
            identity(new) == item["after"]
            and identity(before) == item["before"]
            and item["mode"] == "100644",
            "SOURCE_BYTES",
        )
        leaf = next(x for x in proposed["src"] if x["path"] == name)
        require(
            leaf["mode"] == "100644" and leaf["sha"] == item["before"]["git_blob"],
            "SOURCE_PREIMAGE",
        )
        leaf["sha"] = item["after"]["git_blob"]
    derived = {"src": old.tree_sha(proposed["src"])}
    for parent, child, name in reversed(edges):
        next(x for x in proposed[parent] if x["path"] == name)["sha"] = derived[child]
        derived[parent] = old.tree_sha(proposed[parent])
    require(
        derived["root"] == manifest["expected_tree"] == TREE, "ACTUAL_PROPOSAL_TREE"
    )
    unified = read(FROZEN / "source-api/unified_tree_api.json")
    require(
        unified["truncated"] is False
        and old.tree_sha(unified["tree"]) == unified["sha"],
        "UNIFIED_TREE_HASH",
    )
    require(
        next(x["sha"] for x in proposed["src"] if x["path"] == "unified_exec")
        == unified["sha"],
        "UNIFIED_TREE_LINK",
    )
    names = [Path(x["path"]).name for x in manifest["unchanged_required_source"]]
    names += ["acl.rs", "acl_tests.rs", "unified_exec/tests.rs"]
    sources, texts = [], []
    for name in names:
        if name in ("acl.rs", "acl_tests.rs"):
            path = UNIT / "candidate" / PREFIX / name
        elif name == "unified_exec/tests.rs":
            path = (
                ROOT
                / "round3_native/windows_access_requests_40/source_auto_ci/42332553913/source"
                / PREFIX
                / name
            )
        else:
            path = FROZEN / "source" / PREFIX / name
        body = path.read_bytes()
        leaves = unified["tree"] if name == "unified_exec/tests.rs" else proposed["src"]
        leaf = next(x for x in leaves if x["path"] == Path(name).name)
        require(
            leaf["mode"] == "100644" and leaf["sha"] == identity(body)["git_blob"],
            "SOURCE_LEAF",
        )
        sources.append(
            {
                "repository_path": PREFIX + name,
                "local_path": str(path),
                "mode": "100644",
                **identity(body),
            }
        )
        texts.append(body.decode())
    tests = (UNIT / "candidate" / PREFIX / "acl_tests.rs").read_text()
    require(
        all(tests.count("fn " + name + "(") == 1 for name in EXTRA_CASES),
        "FIXED_MASK_CASE_SOURCE",
    )
    return "\n".join(texts), {
        "head": HEAD,
        "tree": TREE,
        "parent": PARENT,
        "actual_checkout": CHECKOUT,
        "exact_tree_reconstruction": True,
        "derived_subtrees": derived,
        "source_leaves": sources,
        "manifest_identity": identity(raw),
    }


def main():
    require(sys.dont_write_bytecode and len(sys.argv) == 1, "READ_ONLY_ENTRY")
    directory = ROOT / "round3_native/windows_native_access_43/observer_v2"
    codec = load(
        "native_block",
        directory / "native_block.py",
        "24e3a30d36caca9dec4547a6cbbdd9b73402c4135fc920cd9aa2f4eec7af2022",
    )
    require("native_block" not in sys.modules, "MODULE_NAME_IN_USE")
    sys.modules["native_block"] = codec
    try:
        old = load(
            "fixed_win43_observer",
            directory / "observe_native43.py",
            "1d8145b0f6630482b6158a7dd14594b2baed85f4c35698dfc5b5e0b0f59eadb5",
        )
    finally:
        sys.modules.pop("native_block", None)
    source, binding = observed_source(old)
    jobs = read(HERE / "JOBS_OBSERVATION1_API.json")
    run = read(HERE / "RUN_OBSERVATION1_API.json")
    require(
        jobs["total_count"] == len(jobs["jobs"])
        and len({x["id"] for x in jobs["jobs"]}) == len(jobs["jobs"]),
        "FULL_JOB_PAGE",
    )
    job = next(x for x in jobs["jobs"] if x["id"] == JOB)
    require(
        job["run_id"] == RUN
        and job["head_sha"] == HEAD
        and job["run_attempt"] == 1
        and job["status"] == "completed",
        "OWNING_JOB",
    )
    require(
        run["id"] == RUN and run["head_sha"] == HEAD and run["run_attempt"] == 1,
        "RUN_SCOPE",
    )
    path = HERE / f"job_{JOB}.log"
    st = path.lstat()
    require(
        stat.S_ISREG(st.st_mode)
        and st.st_nlink == 1
        and stat.S_IMODE(st.st_mode) == 0o600,
        "PRIVATE_ORIGINAL_MODE",
    )
    raw = path.read_bytes()
    require(
        len(raw) == 532020 and identity(raw)["sha256"] == RAW_SHA,
        "PRIVATE_ORIGINAL_IDENTITY",
    )
    lines = [
        re.sub(r"^\d{4}-\d{2}-\d{2}T\S+\s+", "", line)
        for line in raw.decode().splitlines()
    ]
    checkout_rows = [
        {"command_line": i, "result_line": i + 1}
        for i, line in enumerate(lines)
        if i
        and line.strip() == CHECKOUT
        and re.search(r'git(?:\.exe)?"? log -1 --format=%H', lines[i - 1])
    ]
    require(checkout_rows, "ACTUAL_CHECKOUT_LINE")
    output = json.loads(json.dumps(codec.extract(lines, source)))
    previous = codec.load(
        "fixed_reverse42",
        ROOT / "round3_native/windows_access_model_42/qualify_native5249.py",
        "85278e0b7b1d9550c4e4a43c5b000bb4c650823027925e7480a96f8f1d277e2d",
    )
    renderer, renderer_binding = previous.legacy_functions()
    reversed_lines = []
    for kind, rows in output["records"].items():
        if kind == "unparsed_record_lines":
            continue
        for row in rows:
            if kind == "native_records":
                variants = (codec.render(row),)
            elif kind == "fixed_failures":
                variants = old.reverse_failure(row)
            else:
                variants = (previous.descriptor_render(kind, row, renderer),)
            require(lines[row["line"] - 1] in variants, "FIXED_RECORD_REVERSE")
            reversed_lines.append(row["line"])
    require(len(reversed_lines) == len(set(reversed_lines)), "DUPLICATE_ACCEPTED_LINE")
    extra = {"acl::tests::" + name: [] for name in EXTRA_CASES}
    for number, line in enumerate(lines, 1):
        for name, values in extra.items():
            match = re.fullmatch(
                "test " + re.escape(name) + r" \.\.\. (ok|FAILED|ignored)", line
            )
            if match:
                values.append({"line": number, "result": match[1]})
    result = {
        "schema": "windows44-safe-owning-observations-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": binding,
        "run": RUN,
        "job": JOB,
        "attempt": 1,
        "job_conclusion": job["conclusion"],
        "whole_run_status_at_snapshot": run["status"],
        "whole_run_conclusion_at_snapshot": run["conclusion"],
        "complete_job_count_at_snapshot": jobs["total_count"],
        "actual_checkout_rows": checkout_rows,
        "private_original_identity_only": {
            "path": str(path),
            **identity(raw),
            "mode": "0600",
            "included": False,
        },
        "wrapper_identity": identity(Path(__file__).read_bytes()),
        "frozen_native_block_identity": identity(
            (directory / "native_block.py").read_bytes()
        ),
        "frozen_observer_identity": identity(
            (directory / "observe_native43.py").read_bytes()
        ),
        "old_renderer_binding": renderer_binding,
        "fixed_rows_reverse_exact": len(reversed_lines),
        "all_full_prefix_line_positions": [
            i
            for i, line in enumerate(lines, 1)
            if line.startswith(("FULL_", "Error: FULL_"))
        ],
        **output,
        "fixed_mask_case_results": extra,
        "new_native_or_retry": False,
        "unknown_text_retained": False,
        "production_P0_closed": False,
        "legacy_acl_migration_closed": False,
        "limits": [
            "Direct case summaries are separate from numeric observations; a successful captured test may print no FULL records.",
            "No fields are inherited from Windows43 or inferred from expected source values.",
            "Repeated console blocks and tails do not constitute additional executions.",
            "A source-bound target result is not whole-workflow qualification.",
        ],
    }
    dest = HERE / "SAFE_NATIVE_OBSERVATIONS.json"
    with dest.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "path": str(dest),
                **identity(dest.read_bytes()),
                "source_leaves": len(binding["source_leaves"]),
                "fixed_rows": len(reversed_lines),
                "targets": output["target_rows"],
                "cases": output["fixed_case_results"],
                "mask_cases": extra,
                "blocks": [
                    {
                        "block": x["block"],
                        "source_defined_records": x["source_defined_records"],
                        "native": x["new_native_observations"],
                    }
                    for x in output["block_evidence"]["blocks"]
                ],
                "unparsed": output["records"]["unparsed_record_lines"],
            }
        )
    )


if __name__ == "__main__":
    main()
