"""Verify the complete ACL33 evidence packet with the fixed canonical reader."""

import ast
import datetime
import hashlib
import json
from pathlib import Path
import runpy
import stat
import sys
import zipfile

from review_core24b2 import BASE, identity, require


def seal(raw):
    values = [
        ast.literal_eval(node.value)
        for node in ast.parse(raw).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EXPECTED_INDEX_SHA256"
            for target in node.targets
        )
    ]
    require(len(values) == 1, "one fixed reader seal")
    return values[0]


def main():
    require(
        sys.flags.optimize == 1 and sys.dont_write_bytecode,
        "optimized no-bytecode reader",
    )
    publication = BASE / "round3_core_ci/BWRAP33_CHECKPOINT_PUBLICATION_MANIFEST.json"
    package = BASE / "round3_core_ci/bwrap33_evidence_checkpoint"
    source_api_path = BASE / "round3_bwrap33_checkpoint_canonical_api.json"
    require(
        identity(publication)["sha256"]
        == "c6820bca7f6796149acaf0c837f658e46968fb172af82cb3043515268a15a38f",
        "fixed publication manifest",
    )
    manifest = json.loads(publication.read_bytes())
    require(
        len(manifest["files"]) == len({row["path"] for row in manifest["files"]}) == 14,
        "fourteen publication files",
    )
    before = {}
    for row in manifest["files"]:
        source = Path(row["local_path"])
        require(
            source.parent == package
            and not source.is_symlink()
            and stat.S_IMODE(source.stat().st_mode) == 0o644
            and row["mode"] == "100644",
            "ordinary publication path and mode",
        )
        expected = {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        require(identity(source) == expected, "publication bytes")
        before[str(source)] = expected
    template = BASE / "round3_native/sdk_product_evidence_20261106/restore.py"
    template_raw = template.read_bytes()
    require(
        identity(template)["sha256"]
        == "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d",
        "qualified canonical reader",
    )
    api = json.loads(source_api_path.read_bytes())
    require(
        api["head"] == "6c48024f199c28bb0050dfa7b89d63fe7c2dcfd7"
        and api["tree"] == "50271ed84113bd46faf048a853ea3c42d9ecd14c"
        and len(api["leaves"]) == 1,
        "fresh exact parent source",
    )
    leaf = next(iter(api["leaves"].values()))
    require(
        leaf["sha"] == identity(template)["git_blob"]
        and leaf["mode"] == "100644"
        and leaf["size"] == len(template_raw),
        "canonical source leaf",
    )
    reader = package / "restore.py"
    raw = reader.read_bytes()
    index_sha = "8c9d0ed50db9b1c3dc65aa1849eff8e0d439b66dad9818dad1cc332b3a6cc779"
    require(
        template_raw.count(seal(template_raw).encode()) == 1
        and template_raw.replace(seal(template_raw).encode(), seal(raw).encode(), 1)
        == raw,
        "only fixed index seal differs",
    )
    require(
        not any(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(raw))),
        "reader checks active under optimization",
    )
    module = runpy.run_path(str(reader), run_name="fixed_in_memory_reader")
    index, recovered = module["read_package"](package)
    require(
        identity(package / "INDEX.json")["sha256"] == index_sha == seal(raw),
        "exact sealed index",
    )
    rows = {row["path"]: row for row in index["files"]}
    require(
        len(rows) == len(index["files"]) == len(recovered) == 420
        and set(rows) == set(recovered),
        "all original members",
    )
    require(sum(map(len, recovered.values())) == 2208974, "all original byte count")
    private = {
        "3b2c88d2891b823ad6c85cac9aade0405ad36092735570c5d1611f70932306b4",
    }
    require(
        {row["sha256"] for row in index["excluded"]} == private,
        "exact private console exclusions",
    )
    official_name = (
        "round3_core_ci/bwrap_default_acl_preservation_33/native_observations/"
        "42343428376/artifact-13562004209.zip"
    )
    official_sha = "49d0a20ac40438301cec83675aebd82621b640fe61661487a9dfa29cc10c8c1f"
    restricted = []
    allowed_restricted = {official_name: official_sha}
    with zipfile.ZipFile(BASE / official_name) as archive:
        require(
            len(archive.infolist()) == 137 and archive.testzip() is None,
            "137 exact original ZIP members with valid CRC",
        )
        parent = str(Path(official_name).parent / "artifact_members")
        for name in archive.namelist():
            data = archive.read(name)
            require(
                recovered[parent + "/" + name] == data,
                "accepted originals equal original ZIP",
            )
            allowed_restricted[parent + "/" + name] = hashlib.sha256(data).hexdigest()
    for name, data in recovered.items():
        source, row = BASE / name, rows[name]
        mode = source.lstat().st_mode
        require(
            stat.S_ISREG(mode)
            and not source.is_symlink()
            and data == source.read_bytes()
            and len(data) == row["bytes"]
            and hashlib.sha256(data).hexdigest() == row["sha256"],
            "every original byte and identity",
        )
        require(
            format(stat.S_IMODE(mode), "04o") == row["source_permission_bits"]
            and format(mode, "06o") == row["source_stat_mode"],
            "every original mode",
        )
        require(row["sha256"] not in private, "private consoles absent")
        if row["source_permission_bits"] == "0600":
            restricted.append(name)
            require(
                allowed_restricted.get(name) == row["sha256"],
                "only exact accepted official ZIP or member has restricted mode",
            )
    require(
        set(restricted) == set(allowed_restricted) and len(restricted) == 138,
        "all restricted inputs belong to the exact original accepted artifact",
    )
    required = {
        "round3_local_qualification/bwrap33_terminal_root/ROOT_REVIEW.json": "b874bead960c601712079f0ab551a2bdde619589f2aa75577e3defc17e2c44aa",
        "round3_local_qualification/bwrap33_native_checks/ROOT_CHECKS.json": "d461753052a6061dc4428ed80575abcdca79fb7c005d2f1fe7ba2ab23b9ea502",
    }
    for name, digest in required.items():
        require(
            name in recovered and hashlib.sha256(recovered[name]).hexdigest() == digest,
            "root native evidence and original quality checks retained",
        )
    checks = json.loads((package / "CHECKS.json").read_bytes())
    require(
        checks["accepted_originals"] == 136
        and checks["full_slots"] == 146
        and checks["missing_originals"] == 10
        and checks["diagnostic_complete"] is False
        and checks["mechanism_qualified"] is checks["product_P0_closed"] is False,
        "original incomplete parser failure and open mechanism scope",
    )
    require(
        checks["source_path_intersection_with_28_29_31_32"] == [],
        "old checkpoint paths not repackaged",
    )
    require(
        all(identity(Path(name)) == expected for name, expected in before.items()),
        "publication inputs unchanged",
    )
    proof = BASE / "round3_local_qualification/bwrap33_checkpoint_root"
    proof.mkdir(exist_ok=False)
    result = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Independent canonical reader and complete original bytes and modes",
        "publication": identity(publication),
        "index": identity(package / "INDEX.json"),
        "canonical_source_API": identity(source_api_path),
        "reader": identity(reader),
        "reader_only_seal_changed": True,
        "original_files": 420,
        "original_bytes": 2208974,
        "publication_files": 14,
        "accepted_native_originals": 136,
        "missing_native_originals": 10,
        "official_ZIP_members": 137,
        "all_CRC_and_original_members_verified": True,
        "every_original_byte_and_source_mode_equal": True,
        "root_evidence_included": required,
        "private_console_contents_excluded": True,
        "archived_sources_executed": False,
        "expanded_restore_written": False,
        "new_native_execution": False,
        "mechanism_qualified": False,
        "product_P0_closed": False,
        "qualification": "Original ACL-preserving mode tightening and successful parser prechecks followed by exact names-guard rejection. The 136 accepted and ten missing slots remain incomplete; no profile load, post-namespace success or product qualification follows.",
        "reviewer": identity(Path(__file__)),
    }
    target = proof / "ROOT_REVIEW.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"review": identity(target), "files": 420, "bytes": 2208974}))


if __name__ == "__main__":
    main()
