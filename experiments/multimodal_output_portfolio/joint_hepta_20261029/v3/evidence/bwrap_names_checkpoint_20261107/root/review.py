"""Verify the complete names34 packet with the qualified inert reader."""

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
        sys.flags.optimize == 1 and sys.dont_write_bytecode, "reader execution flags"
    )
    publication = BASE / "round3_core_ci/BWRAP34_CHECKPOINT_PUBLICATION_MANIFEST.json"
    package = BASE / "round3_core_ci/bwrap34_evidence_checkpoint"
    source_api = BASE / "round3_bwrap34_checkpoint_canonical_api.json"
    require(
        identity(publication)["sha256"]
        == "f7039fea427115a0105540aa1751fc1da3be19ce9cf31646e825f692f610b4fa",
        "fixed publication manifest",
    )
    manifest = json.loads(publication.read_bytes())
    require(
        len(manifest["files"]) == len({r["path"] for r in manifest["files"]}) == 14,
        "fourteen files",
    )
    before = {}
    for row in manifest["files"]:
        path = Path(row["local_path"])
        require(
            path.parent == package
            and not path.is_symlink()
            and stat.S_IMODE(path.lstat().st_mode) == 0o644
            and row["mode"] == "100644",
            "ordinary publication path and mode",
        )
        expected = {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        require(identity(path) == expected, "publication bytes")
        before[str(path)] = expected
    template = BASE / "round3_native/sdk_product_evidence_20261106/restore.py"
    template_raw = template.read_bytes()
    require(
        identity(template)["sha256"]
        == "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d",
        "qualified canonical reader",
    )
    api = json.loads(source_api.read_bytes())
    require(
        api["head"] == "35365065c0adfa9fb7e01eabcf7ba77523e4ddd8"
        and api["tree"] == "ca3e3f268372e88c23ca980b6322725f682f45c6"
        and len(api["leaves"]) == 1,
        "fresh exact source",
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
    require(
        template_raw.count(seal(template_raw).encode()) == 1
        and template_raw.replace(seal(template_raw).encode(), seal(raw).encode(), 1)
        == raw,
        "only fixed index seal differs",
    )
    require(
        not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(raw))),
        "active checks",
    )
    module = runpy.run_path(str(reader), run_name="fixed_in_memory_reader")
    index, recovered = module["read_package"](package)
    require(
        identity(package / "INDEX.json")["sha256"]
        == seal(raw)
        == "cf1d3812d649643170c432a6008a269017accd8e88dd5b1b34b5a0dc459fee97",
        "exact sealed index",
    )
    rows = {row["path"]: row for row in index["files"]}
    require(
        len(rows) == len(index["files"]) == len(recovered) == 1019
        and set(rows) == set(recovered),
        "all members",
    )
    require(sum(map(len, recovered.values())) == 4802076, "all original bytes")
    private = {"fd9ac9c0a39855de8793c7db525f23cd8e295eb528e004172506b15b52c25b7f"}
    require(
        {row["sha256"] for row in index["excluded"]} == private,
        "private console excluded",
    )
    official = "round3_core_ci/bwrap_parser_names_34/native_observations/42345546246/artifact-13563517151.zip"
    official_sha = "39cd25c1f832c3e746955a050189962f9c805952a6c9abcd922fafe846a8cd3f"
    require(
        hashlib.sha256(recovered[official]).hexdigest() == official_sha,
        "exact official ZIP",
    )
    allowed_restricted = {official: official_sha}
    with zipfile.ZipFile(BASE / official) as archive:
        require(
            len(archive.infolist()) == 147 and archive.testzip() is None,
            "147 original CRC-valid members",
        )
        parent = str(Path(official).parent / "artifact_members")
        for name in archive.namelist():
            data = archive.read(name)
            require(
                recovered[parent + "/" + name] == data, "original ZIP member equality"
            )
            allowed_restricted[parent + "/" + name] = hashlib.sha256(data).hexdigest()
    restricted = set()
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
        require(row["sha256"] not in private, "private bytes absent")
        if row["source_permission_bits"] == "0600":
            restricted.add(name)
            require(
                allowed_restricted.get(name) == row["sha256"],
                "accepted official restricted input only",
            )
    require(
        restricted == set(allowed_restricted) and len(restricted) == 148,
        "all restricted members accounted for",
    )
    required = {
        "round3_local_qualification/bwrap34_terminal_root/ROOT_REVIEW.json": "9bb2b4c8ee52ce1489b63de7e5ab6f2f439817eb4f3f7cbbd1cae4c9c95609c4",
        "round3_local_qualification/bwrap34_native_checks/ROOT_CHECKS.json": "8f217aaa706a0c3cfdbd7d9b318c9a0167f8603f48006162c410a64212d6c1f3",
    }
    for name, digest in required.items():
        require(
            name in recovered and hashlib.sha256(recovered[name]).hexdigest() == digest,
            "original root evidence retained",
        )
    checks = json.loads((package / "CHECKS.json").read_bytes())
    require(
        checks["accepted_originals"] == checks["full_slots"] == 146
        and checks["missing_originals"] == 0
        and checks["diagnostic_complete"] is True
        and checks["mechanism_qualified"] is True
        and checks["product_P0_closed"] is False,
        "complete bounded mechanism and open product scope",
    )
    earlier = set()
    for folder in (
        "bwrap28_evidence_checkpoint_v2",
        "bwrap29_evidence_checkpoint",
        "bwrap31_evidence_checkpoint",
        "bwrap32_evidence_checkpoint",
        "bwrap33_evidence_checkpoint",
    ):
        old = json.loads((BASE / "round3_core_ci" / folder / "INDEX.json").read_bytes())
        earlier.update(row["path"] for row in old["files"])
    require(
        not (set(recovered) & earlier)
        and checks["source_path_intersection_with_prior_checkpoints"] == [],
        "no repackaged prior source paths",
    )
    require(
        all(
            not name.startswith("round3_core_ci/core_profile_bridge_35/")
            for name in recovered
        ),
        "later Core35 sources absent",
    )
    require(
        all(identity(Path(name)) == expected for name, expected in before.items()),
        "publication unchanged",
    )
    proof = BASE / "round3_local_qualification/bwrap34_checkpoint_root"
    proof.mkdir(exist_ok=False)
    result = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Independent canonical reader and complete original bytes and modes",
        "publication": identity(publication),
        "index": identity(package / "INDEX.json"),
        "canonical_source_API": identity(source_api),
        "reader": identity(reader),
        "reader_only_seal_changed": True,
        "original_files": 1019,
        "original_bytes": 4802076,
        "publication_files": 14,
        "accepted_native_originals": 146,
        "missing_native_originals": 0,
        "official_ZIP_members": 147,
        "all_CRC_and_original_members_verified": True,
        "every_original_byte_and_source_mode_equal": True,
        "root_evidence_included": required,
        "private_console_contents_excluded": True,
        "archived_sources_executed": False,
        "expanded_restore_written": False,
        "new_native_execution": False,
        "mechanism_qualified": True,
        "product_P0_closed": False,
        "qualification": "Complete evidence of the unique 5260 VM mechanism is preserved. The same-fd ACL-preserving prerequisite, exact names gate, additive profile load and post-namespace checks pass. No Core test, production P0 closure, old-VM state or VM teardown qualification follows.",
        "reviewer": identity(Path(__file__)),
    }
    target = proof / "ROOT_REVIEW.json"
    with target.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"review": identity(target), "files": 1019, "bytes": 4802076}))


if __name__ == "__main__":
    main()
