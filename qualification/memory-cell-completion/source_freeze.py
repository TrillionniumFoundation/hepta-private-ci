"""Separate native tested-source identity from adapter research source proofs."""

from pathlib import Path
import re
import subprocess

from evidence_transport import canonical, file_pin, identity, load, pin, plain_file, require, safe_name


ADAPTER = "qualification/memory-cell-adapters/"
PACKER = "qualification/memory-cell-v9/pack_evidence.py"
FORMAL_FREEZE = ADAPTER + "evidence/formal-01/FREEZE.json"
SOURCE_BINDING = ADAPTER + "evidence/formal-01/SOURCE_BINDING.json"


def git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo, stderr=subprocess.PIPE)


def tracked_adapter(repo):
    require(not git(repo, "status", "--porcelain", "--untracked-files=all", "--", ADAPTER).strip(),
            "adapter tree has tracked changes or untracked nonignored files")
    records = git(repo, "ls-tree", "-r", "-z", "HEAD", "--", ADAPTER).split(b"\0")
    files = {}
    for row in filter(None, records):
        header, raw_name = row.split(b"\t", 1)
        mode, kind, _ = header.decode().split()
        name = safe_name(raw_name.decode())
        require(kind == "blob" and mode in ("100644", "100755"), "nonregular tracked adapter path")
        files[name] = {"mode": mode, **file_pin(repo / name)}
    require(files, "tracked adapter inventory is empty")
    return {"scope": "all HEAD-tracked adapter files; ignored runtime files excluded",
            "files": files, "inventory_sha256": identity(canonical(files))["sha256"]}


def source_name(name, *, formal):
    require(isinstance(name, str), "invalid frozen source label")
    if formal:
        return ADAPTER + safe_name(name)
    if name.startswith("/"):
        marker = "/qualification/"
        require(name.count(marker) == 1, "ambiguous historical source root")
        name = "qualification/" + name.split(marker, 1)[1]
    safe_name(name)
    require(name.startswith(ADAPTER) or name.startswith("qualification/memory-cell-v9/learning/"),
            "frozen source label outside registered research roots")
    return name


def verify_freeze(repo, path, *, formal=False):
    safe_name(path)
    require(path.startswith(ADAPTER), "adapter FREEZE must be retained within adapter evidence")
    raw, value = load(repo / path)
    schemas = {"hepta.memory.adapter-freeze.v1"} if formal else {
        "hepta.memory.adapter-longrun-freeze.v1", "hepta.memory.adapter-longrun-resume-freeze.v1"}
    require(isinstance(value, dict) and value.get("schema") in schemas
            and isinstance(value.get("source_files"), dict) and value["source_files"], "unsupported source FREEZE")
    files = {}
    for original, expected in value["source_files"].items():
        name = source_name(original, formal=formal)
        require(name not in files, "duplicate rebased frozen source")
        pin(expected)
        require(file_pin(repo / name) == expected, "frozen research source changed: " + name)
        files[name] = expected
    return {"path": path, **identity(raw), "schema": value["schema"], "files": files,
            "native_ci_coverage_claimed": False}


def verify_sources(repo, tested, tree, additional_freezes):
    require(re.fullmatch(r"[0-9a-f]{40}", tested) and re.fullmatch(r"[0-9a-f]{40}", tree), "invalid tested Git identity")
    require(git(repo, "rev-parse", "--verify", f"{tested}^{{commit}}").decode().strip() == tested,
            "tested commit object is unavailable")
    require(git(repo, "rev-parse", f"{tested}^{{tree}}").decode().strip() == tree, "tested tree mismatch")
    git(repo, "merge-base", "--is-ancestor", tested, "HEAD")
    packer = file_pin(repo / PACKER)
    require(packer == identity(git(repo, "show", f"{tested}:{PACKER}")), "evidence packer differs from tested source")
    adapter = tracked_adapter(repo)
    require(FORMAL_FREEZE in adapter["files"] and SOURCE_BINDING in adapter["files"],
            "formal adapter source proofs must be tracked")
    formal = verify_freeze(repo, FORMAL_FREEZE, formal=True)
    binding_raw, binding = load(repo / SOURCE_BINDING)
    require(isinstance(binding, dict) and binding.get("files") == formal["files"]
            and binding.get("all_frozen_files_match_committed_blobs") is True,
            "formal adapter SOURCE_BINDING differs from FREEZE")
    origin, origin_tree = binding.get("remote_source_commit"), binding.get("remote_source_tree")
    require(isinstance(origin, str) and re.fullmatch(r"[0-9a-f]{40}", origin)
            and isinstance(origin_tree, str) and re.fullmatch(r"[0-9a-f]{40}", origin_tree),
            "adapter source commit/tree binding is missing")
    require(git(repo, "rev-parse", f"{origin}^{{tree}}").decode().strip() == origin_tree,
            "adapter source origin tree mismatch")
    for name, expected in formal["files"].items():
        require(identity(git(repo, "show", f"{origin}:{name}")) == expected,
                "adapter origin blob differs from source proof")
    require(len(additional_freezes) == len(set(additional_freezes)), "duplicate adapter FREEZE argument")
    if any(name.startswith(ADAPTER + "longrun/") and name.endswith(".py") for name in adapter["files"]):
        require(additional_freezes, "longrun sources require separately retained FREEZE proofs")
    freezes = [formal]
    for path in additional_freezes:
        require(path in adapter["files"], "longrun FREEZE proof is not tracked adapter evidence")
        freezes.append(verify_freeze(repo, path))
    adapter.update(source_freezes=freezes, source_binding={"path": SOURCE_BINDING, **identity(binding_raw)},
                   independently_bound_origin_commit=origin, native_ci_coverage_claimed=False)
    return {"head_commit": git(repo, "rev-parse", "HEAD").decode().strip(),
            "tested_commit": tested, "tested_tree": tree, "pack_evidence": packer, "adapter": adapter}


def verify_after(repo, before):
    require(isinstance(before, dict) and before.get("schema") == "hepta.memory.completion.preflight.v1"
            and before.get("passed") is True, "successful original preflight receipt required")
    sources = before["sources"]
    require(git(repo, "rev-parse", "HEAD").decode().strip() == sources["head_commit"], "finalization HEAD changed")
    require(file_pin(repo / PACKER) == sources["pack_evidence"], "finalization changed evidence packer")
    adapter = tracked_adapter(repo)
    require(adapter["files"] == sources["adapter"]["files"], "finalization changed adapter bytes or file modes")
    return {"adapter_inventory_sha256": adapter["inventory_sha256"],
            "tracked_adapter_files": len(adapter["files"]), "native_ci_coverage_claimed": False}
