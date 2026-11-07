"""Verify the fixed Windows43 safe checkpoint in memory; never run payload code."""

import ast
from collections import Counter
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from types import SimpleNamespace


BASE = Path("/workspace/scratch/3f6a885bb83c")
HERE = Path("/dev/shm/ndu_windows43_packet_audit_20261107")
OUTPUT = Path("/dev/shm/ndu_windows43_packet_root_review_20261107")
PACKAGE = BASE / "round3_native/windows43_terminal_evidence_20261107"
MANIFEST = (
    BASE / "round3_native/WINDOWS43_TERMINAL_CHECKPOINT_PUBLICATION_MANIFEST.json"
)
MANIFEST_SHA = "8c2aa869983d562e8100ee1cb65d82497248227f7154378ef54d0f254bc3aa6e"
INDEX_SHA = "a82fd3950e0617613d4dabc34000a04add66b379bf734deb929ce01d5b1a0e07"
CANONICAL = BASE / "round3_native/sdk_product_evidence_20261106/restore.py"
CANONICAL_SHA = "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d"
CANONICAL_API = Path(
    "/dev/shm/ndu_root_continuation_20261107/windows43_packet_canonical_api.json"
)
CANONICAL_API_SHA = "aa254ba60b4b56ee147ab0c37a5e56319ec394a4a5653756fa52f6de6ad26667"
CANONICAL_LEAF = "experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/evidence/sdk_product_contract_checkpoint_20261106/restore.py"
REPOSITORY_DIRECTORY = "experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/evidence/windows_native_access_terminal_checkpoint_20261107"
PART = "native-evidence.tar.xz.part000.gz"
PUBLICATION_NAMES = {
    "CODESPELL.json",
    "INDEX.json",
    "READER_CHECK.json",
    "README.md",
    "ROUNDTRIP.json",
    PART,
    "restore.py",
}
EXTERNAL_PREFIX = "round3_native/windows43_safe_checkpoint_inputs/external_originals/"
EXTERNAL_SOURCES = {
    "ndu_root_continuation_20261107/round3_win43_native_api.json",
    "ndu_root_continuation_20261107/round3_win43_native_leaves.json",
    "ndu_root_continuation_20261107/windows43_terminal_api_update.json",
    "ndu_windows43_20261107/HEAD_COMMIT_API.json",
    "ndu_windows43_20261107/INITIAL_API_ORCHESTRATION_FAILURE.json",
    "ndu_windows43_20261107/INITIAL_NATIVE_STATUS.json",
    "ndu_windows43_20261107/JOBS_OBSERVATION1_API.json",
    "ndu_windows43_20261107/PR_API.json",
    "ndu_windows43_20261107/PR_MERGE_CANDIDATE_API.json",
    "ndu_windows43_20261107/RUN_DISCOVERY_API.json",
    "ndu_windows43_20261107/RUN_OBSERVATION1_API.json",
    "ndu_windows43_20261107/SAFE_NATIVE_OBSERVATIONS.json",
    "ndu_windows43_20261107/read_initial_status.py",
}
STATUS = "round3_native/windows43_safe_checkpoint_inputs/RUN_STATUS.json"
SELECTION = "round3_native/windows43_safe_checkpoint_inputs/SELECTED_FILES.json"
ROOT_REVIEW = "round3_local_qualification/windows43_terminal_root/ROOT_REVIEW.json"
SAFE_OBSERVATIONS = (
    EXTERNAL_PREFIX + "ndu_windows43_20261107/SAFE_NATIVE_OBSERVATIONS.json"
)
LATEST_API = (
    EXTERNAL_PREFIX
    + "ndu_root_continuation_20261107/windows43_terminal_api_update.json"
)
EXTRA_SELECTION_FILES = {
    "round3_core_ci/build_windows43_checkpoint.py",
    "round3_core_ci/select_windows43_checkpoint.py",
    "round3_native/windows43_safe_checkpoint_inputs/HISTORY.md",
    STATUS,
    SELECTION,
}
REQUIRED = {
    ROOT_REVIEW: "89e385093775b49208bff9de85b802a5afa564793c6c0567c1187848c6fcec32",
    "round3_local_qualification/windows43/ROOT_REVIEW.json": "6200b1d95c133ef443828efcc195fbd98f660c5df58095566325f5e4a1ecbda4",
    "round3_local_qualification/windows43_source_checks/ROOT_CHECKS.json": "36f613f8a145cd0a7068566106f3b3fb7e3acf60fd8936da2f484974202a9eda",
    "round3_local_qualification/core35_windows43_audit_checks/ROOT_CHECKS.json": "6ccb399833b7b92431c4ac6512396ac560a5909febca269976223264be96a5a9",
    "round3_core_ci/independent_reviews/windows43_source_review2/REVIEW.json": "4fa8b51894f0b961c775caf9542eaff9f53bdbd6d54be6e7a3222ef21f30b6e5",
    "round3_core_ci/independent_reviews/windows43_source_review2/REVIEW3_ADDENDUM.json": "e670387b361ae7b320bbab06d095c3e274f54d74d830b70874dc2d00aea1026a",
    "round3_native/windows_native_access_43/review2/PURE_PATH_CASES.json": "51e5d68251fa9602615c04082a03c6500cb62b777a19b321f472c995c520c58b",
    "round3_native/windows_native_access_43/review3/manifest.json": "eadbaffba25c61221148e2c4a76d7b27f93f432fab5d2a77fdeabed3c2b150c7",
    "round3_native/windows_native_access_43/observer_v1/FINAL_MODEL_CHECKS.json": "56f34c47fd6d827d7dc5d0e54dc2c9a4c63acbd7893dc6911cf0e5cc9bff8c04",
    "round3_native/windows_native_access_43/observer_v2/INITIAL_OBSERVER_FAILURE.json": "8ee1a276c0e4379136746e9511e65dd21a5e6d15efb0ac603cf6dec4038c8cbe",
    "round3_native/windows_native_access_43/observer_v2/from_v1.patch": "edeaa671b15c9ce75cd9d975535eedf934dca755fbb240f7e7293beea210a523",
    "round3_native/windows_native_access_43/observer_v2/SERIALIZATION_COMPONENT_CHECKS.json": "9d573d5d368e64894e233e58e41de92fad18be0b25a87525ad4b13e42dd3ba0c",
    SELECTION: "d98328939406dd4495a5fa17e2b7c16f9ed34f3691c092c7609d97c2f1e6889f",
    STATUS: "35ad46b7c68393a9a71aa2aad61a2ba2d03ee80fcf5d69aa3ac2577659fd4710",
    SAFE_OBSERVATIONS: "be68efe3f242a0c9c8b8fb696a356aa3f1bbc32ae21e50b6e677cde1e17d9fb3",
    LATEST_API: "e5369965f568bb7e83a28202d3cb7da0c7beb6be687d48b6863bc6d270328aea",
}
PRIVATE_SHA = "8d56216ef73eef5744a7fed47304a81db8e4209888204417c33027e2d9f3074b"
PRIVATE_PATH = "/dev/shm/ndu_windows43_20261107/job_128326978690.log"
HEAD = "47723bb04013bf2d98647e9470561194f438a786"
TREE = "8191299036f3c77860547f3245c6b80278a27b0b"
CHECKOUT = "dee516018c4cc5cc88ee530a786179be6a1b7d39"
RUN = 42346914963
JOB = 128326978690
CASES = {
    "token::tests::read_authority_probe::full_restriction_preserves_prepared_read_and_mutation_boundaries",
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots",
}
STAT_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_uid",
    "st_gid",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)
MAX_FILE_BYTES = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def safe_relative(name):
    require(type(name) is str and bool(name), "PATH_TYPE")
    path = PurePosixPath(name)
    require(
        not path.is_absolute()
        and path.as_posix() == name
        and not any(p in ("", ".", "..") for p in name.split("/"))
        and not any(c in name for c in ("\\", ":", "\0"))
        and not any(ord(c) < 32 or ord(c) == 127 for c in name),
        "CANONICAL_PATH",
    )
    return path


def stamp(value):
    return {key: getattr(value, key) for key in STAT_FIELDS}


@contextlib.contextmanager
def parent_descriptor(path):
    require(
        path.is_absolute() and str(path) == os.path.normpath(str(path)),
        "ABSOLUTE_CANONICAL_PATH",
    )
    descriptors, chain = [], []
    try:
        current = os.open(
            "/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        descriptors.append(current)
        for name in path.parts[1:-1]:
            before = os.stat(name, dir_fd=current, follow_symlinks=False)
            require(stat.S_ISDIR(before.st_mode), "NO_SYMLINK_ANCESTRY")
            child = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            descriptors.append(child)
            opened = os.fstat(child)
            require(
                (before.st_dev, before.st_ino, before.st_mode)
                == (opened.st_dev, opened.st_ino, opened.st_mode),
                "ANCESTOR_CHANGED",
            )
            chain.append((current, name, child))
            current = child
        yield current
        for parent, name, child in chain:
            current_entry, opened = (
                os.stat(name, dir_fd=parent, follow_symlinks=False),
                os.fstat(child),
            )
            require(
                (current_entry.st_dev, current_entry.st_ino, current_entry.st_mode)
                == (opened.st_dev, opened.st_ino, opened.st_mode),
                "ANCESTOR_CHANGED_AFTER_READ",
            )
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_regular(path):
    require(str(path) != PRIVATE_PATH, "PRIVATE_CONSOLE_MUST_NOT_BE_READ")
    with parent_descriptor(path) as parent:
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) == 0o644
            and 0 <= before.st_size <= MAX_FILE_BYTES,
            "REGULAR_0644_BOUNDED_SOURCE",
        )
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=parent,
        )
        try:
            require(stamp(os.fstat(descriptor)) == stamp(before), "SOURCE_OPEN_CHANGED")
            pieces, count = [], 0
            while count <= before.st_size:
                piece = os.read(
                    descriptor, min(1024 * 1024, before.st_size + 1 - count)
                )
                if not piece:
                    break
                pieces.append(piece)
                count += len(piece)
            require(stamp(os.fstat(descriptor)) == stamp(before), "SOURCE_READ_CHANGED")
        finally:
            os.close(descriptor)
        require(
            stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
            == stamp(before),
            "SOURCE_ENTRY_CHANGED",
        )
    raw = b"".join(pieces)
    require(len(raw) == before.st_size, "EXACT_SOURCE_SIZE")
    return raw, {"identity": identity(raw), "stat": stamp(before)}


def seal(raw):
    tree = ast.parse(raw)
    values = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EXPECTED_INDEX_SHA256"
            for target in node.targets
        )
    ]
    require(
        len(values) == 1
        and type(values[0]) is str
        and re.fullmatch("[a-f0-9]{64}", values[0]),
        "ONE_FIXED_INDEX_SEAL",
    )
    require(
        not any(isinstance(node, ast.Assert) for node in ast.walk(tree)),
        "OPTIMIZED_CHECKS_REMAIN_ACTIVE",
    )
    return values[0]


class FrozenFile:
    def __init__(self, raw):
        self.raw = raw

    def read_bytes(self):
        return self.raw

    def is_symlink(self):
        return False

    def is_file(self):
        return True

    def stat(self):
        return SimpleNamespace(st_size=len(self.raw))


class FrozenPackage:
    def __init__(self, files):
        self.files = files

    def __truediv__(self, name):
        require(name in {"INDEX.json", PART}, "CANONICAL_READER_FILE_SCOPE")
        return FrozenFile(self.files[name])


def check_scope(members):
    status, original, safe, latest = [
        decode(members[name])
        for name in (STATUS, ROOT_REVIEW, SAFE_OBSERVATIONS, LATEST_API)
    ]
    require(
        status["source"] == original["head"] == safe["source"]["head"] == HEAD
        and status["tree"] == original["tree"] == safe["source"]["tree"] == TREE
        and status["checkout"]
        == original["checkout"]
        == safe["source"]["actual_checkout"]
        == CHECKOUT,
        "EXACT_NATIVE_SOURCE_AND_CHECKOUT",
    )
    for row in (status, original, safe):
        require(
            row["run"] == RUN
            and row["attempt"] == 1
            and row["job"] == JOB
            and row["job_conclusion"] == "failure"
            and row["production_P0_closed"] is False,
            "ORIGINAL_FAILED_JOB_SCOPE",
        )
    require(
        set(status["original_cases"]) == CASES
        and status["original_cases"]
        == original["original_cases"]
        == safe["fixed_case_results"]
        and all(
            [row["result"] for row in rows] == ["FAILED"]
            for rows in status["original_cases"].values()
        ),
        "THREE_ORIGINAL_FAILURES",
    )
    target = status["owning_target"]
    require(
        target == original["owning_target"] == safe["target_rows"]
        and len(target) == 1
        and target[0]["status"] == "FAILED"
        and target[0]["cached_marker"] is False
        and target[0]["seconds"] == 110.0,
        "ORIGINAL_NONCACHED_TARGET_FAILURE",
    )
    require(
        status["fixed_records"]
        == original["observed_fixed_rows_reverse_exact"]
        == safe["fixed_rows_reverse_exact"]
        == 358
        and status["new_native_records"]
        == original["observed_new_native_rows"]
        == len(safe["records"]["native_records"])
        == 40
        and status["identical_suffix_records"]
        == original["identical_printed_suffix_rows"]
        == 168
        and status["suffix_is_independent_execution"]
        is original["suffix_is_independent_execution"]
        is False,
        "FINITE_OBSERVATIONS_AND_DUPLICATE_SUFFIX",
    )
    require(
        status["original_root_whole_run_state"]
        == original["whole_run_status_at_fresh_API"]
        == safe["whole_run_status_at_api_snapshot"]
        == "in_progress",
        "OLD_SNAPSHOT_UNCHANGED",
    )
    run = latest["run"]
    require(
        run == status["additive_latest_whole_run_state"]
        and run["id"] == RUN
        and run["head_sha"] == HEAD
        and run["run_attempt"] == 1
        and run["status"] == "completed"
        and run["conclusion"] == "failure"
        and run["updated_at"] == "2026-11-07T07:08:03Z",
        "ADDITIVE_WHOLE_RUN_FAILURE",
    )
    jobs = latest["jobs"]
    require(
        latest["total_count"]
        == status["additive_complete_jobs"]
        == len(jobs)
        == len({row["id"] for row in jobs})
        == 38
        and all(
            row["run_attempt"] == 1 and row["status"] == "completed" for row in jobs
        )
        and Counter(row["conclusion"] for row in jobs)
        == {"success": 23, "failure": 10, "skipped": 5},
        "COMPLETE_ATTEMPT1_API",
    )
    owning = [row for row in jobs if row["id"] == JOB]
    require(
        len(owning) == 1 and owning[0]["conclusion"] == "failure", "SAME_OWNING_JOB"
    )
    require(
        status["windows44_included"] is False
        and status["root_review_reexecuted"] is False
        and status["observer_or_native_executed"] is False
        and original["native_execution_or_retry"] is False
        and original["private_console_or_unknown_text_exported"] is False
        and original["all_original_assertions_retained"] is True
        and safe["native_execution_or_retry"] is False
        and safe["production_factory_changed"] is False
        and safe["unknown_text_retained"] is False
        and safe["unique_filesystem_cause"] == "NOT_INFERRED",
        "UNCHANGED_QUALIFICATION_LIMITS",
    )
    require(
        status["private_console_identity_only"]
        == original["original_private_console_identity_only"]
        and status["private_console_identity_only"]["sha256"] == PRIVATE_SHA
        and status["private_console_identity_only"]["bytes"] == 501087,
        "PRIVATE_IDENTITY_ONLY",
    )
    model = decode(
        members[
            "round3_native/windows_native_access_43/observer_v1/FINAL_MODEL_CHECKS.json"
        ]
    )
    require(
        model["count"] == len(model["checks"]) == 34
        and model["all_passed"] is True
        and model["native_console_read"] is False
        and model["windows_execution"] is False
        and model["rust_tests"] is False
        and model["qualification"] is False,
        "ORIGINAL_PURE_MODEL_SCOPE",
    )
    return {
        "source": HEAD,
        "tree": TREE,
        "checkout": CHECKOUT,
        "run": RUN,
        "attempt": 1,
        "job": JOB,
        "job_conclusion": "failure",
        "original_cases": 3,
        "original_case_results": "ALL_FAILED",
        "owning_target_seconds": 110.0,
        "original_observed_records": 358,
        "original_native_records": 40,
        "identical_suffix_rows": 168,
        "suffix_independent_trial": False,
        "old_whole_run_snapshot": "in_progress",
        "additive_whole_run_status": "completed",
        "additive_whole_run_conclusion": "failure",
        "additive_jobs": 38,
        "individual_success_rows_are_not_case_qualification": True,
    }


def main():
    require(
        sys.flags.optimize == 1 and sys.dont_write_bytecode and len(sys.argv) == 1,
        "RUN_ONLY_PYTHON_B_O_WITHOUT_ARGUMENTS",
    )
    require(
        Path(__file__).absolute() == HERE / "review_windows43_packet.py",
        "FIXED_REVIEWER_PATH",
    )
    protected = {}

    def get(path, sha=None):
        raw, value = read_regular(path)
        if sha is not None:
            require(value["identity"]["sha256"] == sha, "FIXED_SOURCE_HASH")
        name = str(path)
        require(
            name not in protected or protected[name] == value, "REPEATED_SOURCE_CHANGED"
        )
        protected[name] = value
        return raw

    get(Path(__file__))
    manifest = decode(get(MANIFEST, MANIFEST_SHA))
    require(
        manifest["repository"] == "TrillionniumFoundation/hepta-private-ci"
        and manifest["repo_directory"] == REPOSITORY_DIRECTORY
        and manifest["index_sha256"] == INDEX_SHA
        and manifest["remote_mutations_performed"] is False
        and manifest["source_packet"] == "windows43"
        and manifest["original_files"] == 202
        and manifest["original_bytes"] == 1978941
        and manifest["nonmechanical_publication_lines"] == 196,
        "FIXED_PUBLICATION_SCOPE",
    )
    rows = manifest["files"]
    require(
        len(rows)
        == len({row["path"] for row in rows})
        == len({row["local_path"] for row in rows})
        == 7,
        "SEVEN_DISTINCT_PUBLICATION_FILES",
    )
    published = {}
    for row in rows:
        path = Path(row["local_path"])
        require(
            path.parent == PACKAGE
            and path.name in PUBLICATION_NAMES
            and row["path"] == REPOSITORY_DIRECTORY + "/" + path.name
            and row["mode"] == "100644"
            and row["encoding"] == ("base64" if path.name == PART else "utf-8"),
            "PUBLICATION_PATH_MODE_ENCODING",
        )
        raw = get(path, row["sha256"])
        require(
            identity(raw)
            == {
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "git_blob": row["git_blob_sha"],
            },
            "PUBLICATION_FULL_BYTE_IDENTITY",
        )
        published[path.name] = raw
    require(
        set(published) == PUBLICATION_NAMES
        and set(os.listdir(PACKAGE)) == PUBLICATION_NAMES,
        "COMPLETE_PUBLICATION_DIRECTORY",
    )
    require(
        len(published[PART]) == 136843
        and identity(published[PART])["sha256"]
        == "a52b3b3cf826939d2e61ad56fba160fcfd18836822238a9b7df84fe348e58b29",
        "ONE_FIXED_BINARY_PART",
    )
    require(
        sum(len(published[name].splitlines()) for name in ["README.md", "restore.py"])
        == 196,
        "NONMECHANICAL_LINE_COUNT",
    )
    template = get(CANONICAL, CANONICAL_SHA)
    api = decode(get(CANONICAL_API, CANONICAL_API_SHA))
    require(
        api["head"] == "a24bb9a6b3d251c54f5973325998a4c21289fe09"
        and api["tree"] == "ab7a5108639f89bb474ecbd5660850836b9bdf0a"
        and set(api["leaves"]) == {CANONICAL_LEAF},
        "CANONICAL_MAIN5268_API",
    )
    leaf = api["leaves"][CANONICAL_LEAF]
    require(
        leaf["sha"]
        == identity(template)["git_blob"]
        == "04729fbf463b340fcb6fc0a925f4c9e0da61f6a1"
        and leaf["mode"] == "100644"
        and leaf["type"] == "blob"
        and leaf["size"] == len(template) == 6899,
        "CANONICAL_GIT_LEAF",
    )
    reader = published["restore.py"]
    old_seal, new_seal = seal(template), seal(reader)
    require(
        new_seal == INDEX_SHA
        and template.count(old_seal.encode()) == 1
        and template.replace(old_seal.encode(), new_seal.encode(), 1) == reader,
        "READER_ONLY_LITERAL_SEAL_CHANGED",
    )
    module = {
        "__name__": "fixed_canonical_in_memory_reader",
        "__file__": str(PACKAGE / "restore.py"),
    }
    exec(compile(reader, "<verified canonical reader>", "exec"), module)
    index, members = module["read_package"](FrozenPackage(published))
    require(
        index == decode(published["INDEX.json"])
        and identity(published["INDEX.json"])["sha256"] == INDEX_SHA,
        "EXACT_INDEX_BUFFER",
    )
    inventory = {row["path"]: row for row in index["files"]}
    require(
        len(inventory) == len(index["files"]) == len(members) == 202
        and set(inventory) == set(members)
        and sum(map(len, members.values())) == 1978941,
        "COMPLETE_202_MEMBER_ROSTER",
    )
    selection = decode(members[SELECTION])
    selected = {row["path"]: row for row in selection["files"]}
    require(
        selection["kind"] == "windows43"
        and selection["schema"] == "approved-source-and-finite-evidence-selection-v1"
        and selection["file_count"] == len(selected) == len(selection["files"]) == 197
        and selection["file_bytes"]
        == sum(row["bytes"] for row in selected.values())
        == 1836876
        and selection["new_native_execution"] is False
        and selection["remote_mutations_performed"] is False
        and set(inventory) - set(selected) == EXTRA_SELECTION_FILES
        and set(selected) <= set(inventory),
        "PRIOR_SELECTION_AND_FIVE_EXPLICIT_ADDITIONS",
    )
    excluded = {row["source_path"]: row for row in index["excluded"]}
    require(
        len(excluded) == len(index["excluded"]) == 7
        and index["excluded"] == selection["exclusions"]
        and excluded[PRIVATE_PATH]["sha256"] == PRIVATE_SHA,
        "PRIVATE_EXCLUSION_RECORDS",
    )
    external, source_paths, inode_paths, member_proofs = set(), set(), {}, []
    keys = {
        "path",
        "source_path",
        "bytes",
        "sha256",
        "source_permission_bits",
        "source_stat_mode",
    }
    for name, row in sorted(inventory.items()):
        safe_relative(name)
        require(set(row) == keys, "INDEX_ROW_FIELDS")
        require(
            not any(str(parent) in inventory for parent in PurePosixPath(name).parents),
            "FILE_DIRECTORY_CONFLICT",
        )
        source = Path(row["source_path"])
        require(
            source.is_absolute()
            and str(source) == os.path.normpath(str(source))
            and str(source) not in excluded
            and str(source) not in source_paths,
            "DISTINCT_NONEXCLUDED_SOURCE_PATH",
        )
        source_paths.add(str(source))
        if BASE in source.parents:
            require(
                name == source.relative_to(BASE).as_posix(), "LOCAL_SOURCE_PATH_MAPPING"
            )
        else:
            require(Path("/dev/shm") in source.parents, "EXTERNAL_SOURCE_ROOT")
            relative = source.relative_to("/dev/shm").as_posix()
            require(
                relative in EXTERNAL_SOURCES and name == EXTERNAL_PREFIX + relative,
                "EXACT_EXTERNAL_ALIAS",
            )
            external.add(relative)
        require(
            "windows_mutation_deny_44" not in name
            and "ndu_windows44" not in str(source)
            and "windows44" not in name.lower()
            and row["sha256"] != PRIVATE_SHA
            and not re.match(r"job[-_][0-9]+", source.name)
            and source.suffix.lower()
            not in {
                ".zip",
                ".rmeta",
                ".rlib",
                ".exe",
                ".dll",
                ".so",
                ".o",
                ".a",
                ".gz",
                ".xz",
            },
            "PRIVATE_BINARY_OR_WINDOWS44_EXCLUDED",
        )
        raw = get(source, row["sha256"])
        data = members[name]
        require(
            raw == data
            and len(raw) == row["bytes"]
            and row["source_permission_bits"] == "0644"
            and row["source_stat_mode"] == "100644",
            "EVERY_MEMBER_ORIGINAL_BYTES_AND_MODES",
        )
        require(b"\0" not in data, "INERT_TEXT_MEMBER_NO_NUL")
        data.decode("utf-8")
        current = protected[str(source)]
        require(
            format(current["stat"]["st_mode"], "06o") == row["source_stat_mode"],
            "EXACT_SOURCE_STAT_MODE",
        )
        inode = (current["stat"]["st_dev"], current["stat"]["st_ino"])
        require(inode not in inode_paths, "NO_SOURCE_INODE_ALIAS")
        inode_paths[inode] = str(source)
        if name in selected:
            require(
                {key: selected[name][key] for key in keys} == row,
                "SELECTION_INDEX_SOURCE_THREE_WAY_IDENTITY",
            )
        member_proofs.append({"path": name, "source_path": str(source), **current})
    require(
        external == EXTERNAL_SOURCES and len(external) == 13,
        "ALL_THIRTEEN_EXTERNAL_ORIGINALS",
    )
    for name, expected in REQUIRED.items():
        require(
            name in members and identity(members[name])["sha256"] == expected,
            "MANDATORY_HISTORY_OR_ROOT_RECEIPT",
        )
    native_scope = check_scope(members)
    roundtrip = decode(published["ROUNDTRIP.json"])
    require(
        roundtrip["ordinary_memory_roundtrip_exact"] is True
        and roundtrip["optimized"]["exit_code"] == 0
        and roundtrip["optimized"]["stdout"]["files"] == roundtrip["files"] == 202
        and roundtrip["optimized"]["stdout"]["bytes"] == roundtrip["bytes"] == 1978941
        and roundtrip["index_sha256"] == INDEX_SHA
        and roundtrip["bundle_inputs_unchanged"] is True
        and roundtrip["source_path_and_modes_compared"] is True
        and roundtrip["on_disk_extraction"] is False
        and roundtrip["restored_on_disk_modes_tested"] is False
        and roundtrip["archived_source_or_native_executed"] is False,
        "OWNER_MEMORY_ROUNDTRIP_SCOPE",
    )
    for path, previous in sorted(protected.items()):
        require(
            read_regular(Path(path))[1] == previous,
            "ALL_ORIGINAL_INPUTS_UNCHANGED_AFTER_REVIEW",
        )
    require(
        set(os.listdir(PACKAGE)) == PUBLICATION_NAMES, "PUBLICATION_DIRECTORY_UNCHANGED"
    )
    receipt = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Exact canonical in-memory reader, all selected source bytes and modes, and preserved finite qualification boundaries",
        "reviewer": protected[str(Path(__file__))]["identity"],
        "publication": protected[str(MANIFEST)]["identity"],
        "canonical_source_API": protected[str(CANONICAL_API)]["identity"],
        "canonical_template": protected[str(CANONICAL)]["identity"],
        "reader": identity(reader),
        "reader_only_literal_seal_changed": True,
        "index": identity(published["INDEX.json"]),
        "part": identity(published[PART]),
        "publication_files": 7,
        "original_files": 202,
        "original_bytes": 1978941,
        "external_originals": 13,
        "selection_rows": 197,
        "explicit_packaging_additions": 5,
        "nonmechanical_publication_lines": 196,
        "every_member_archive_index_original_bytes_equal": True,
        "all_197_selection_rows_match_index_and_original": True,
        "five_explicit_packaging_sources_match_index_and_original": True,
        "every_original_regular_0644_stat100644_and_unchanged": True,
        "external_originals_read_at_actual_source_path_without_copy_or_fallback": True,
        "archived_payload_source_executed": False,
        "canonical_container_reader_executed": True,
        "expanded_restore_written": False,
        "on_disk_restored_modes_tested": False,
        "private_console_and_execution_ZIP_contents_excluded": True,
        "private_console_or_execution_ZIP_read": False,
        "rmeta_and_binaries_excluded": True,
        "windows44_source_or_outcome_included": False,
        "old_observer_or_native_review_reexecuted": False,
        "new_native_execution": False,
        "remote_writes": False,
        "private_originals_reconstructable_from_this_packet": False,
        "production_P0_closed": False,
        "native_scope_preserved": native_scope,
        "prior_source_and_observer_failures_preserved": True,
        "original_direct_rustc_path_tests_are_not_original_just_qualification": True,
        "required_history": REQUIRED,
        "limits": [
            "Archive completeness covers only the 202 selected safe originals.",
            "This reviewer preserves and cross-checks prior finite receipts; it does not read the excluded console or independently repeat the native inverse parser.",
            "A successful DELETE handle is not an observed delete operation; endpoint token equality does not prove intermediate call identity.",
            "Original case failures and production P0 remain open; completed workflow status does not upgrade any individual success to qualification.",
        ],
    }
    OUTPUT.mkdir(mode=0o755, exist_ok=False)
    for name, value in [
        ("MEMBER_IDENTITIES.json", member_proofs),
        ("ROOT_REVIEW.json", receipt),
    ]:
        raw = (json.dumps(value, indent=2) + "\n").encode()
        descriptor = os.open(
            OUTPUT / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o644,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
    print(
        json.dumps(
            {
                "result": "EXACT_SAFE_CHECKPOINT_VERIFIED",
                "files": 202,
                "bytes": 1978941,
                "external_originals": 13,
                "output": str(OUTPUT),
                "new_native_execution": False,
                "production_P0_closed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
