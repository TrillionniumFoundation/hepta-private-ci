"""Verify the exact-source fixed-base format and paired current owner observations."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
OLD = "e4be1e972707f5c376033fd59e18fb4f260da891"
NEW = "97a379c5a347f0e66c5ed9a0cbd38303d1f92cb5"


def main():
    receipt = json.loads((HERE / "hosted-receipt.json").read_text())
    data = (HERE / "original-fixed-base-hosted.zip").read_bytes()
    assert hashlib.sha256(data).hexdigest() == receipt["sha256"] == "d15bf0347101795d3cff2a96c162cebc8fc9c9dcaf3a221e1219f05f153b819f"
    assert receipt["original_base"] == "b8e8c6e82abc1479c573f61a5e17d28d581e6cad" and receipt["source"] == NEW
    with zipfile.ZipFile(HERE / "original-fixed-base-hosted.zip") as z:
        pair = json.loads(z.read("paired-source.json"))
        files = json.loads((HERE / "sources.json").read_bytes())
        assert len(files) == 12
        for arm, sha, field in [("before", OLD, "original_blob"), ("after", NEW, "formatted_blob")]:
            result = pair[arm]
            assert result["ref"] == sha
            assert result["source_blobs"] == {v["path"]: v[field] for v in files}
            assert result["context_owner_check"][0] == 1 and b"source identity policy" in z.read(arm + "-context.log")
            assert result["wire_own_manifest"][0] != 0 and b"believes it" in z.read(arm + "-wire.log")
            assert result["standalone_fault_compile"][0] == 0
            assert result["standalone_fault_with_qualification_compile"][0] == 0
            assert result["standalone_fault_test"][0] == 0 and b"1 passed;" in z.read(arm + "-fault-test.log")
        assert pair["before"]["workspace_package_count"] == pair["after"]["workspace_package_count"]
        unequal = [p for p in pair["before"]["parsed"] if pair["before"]["parsed"][p] != pair["after"]["parsed"][p]]
        assert sorted(unequal) == sorted([
            "codex-rs/hepta-memory-federation-wire/src/protocol.rs",
            "codex-rs/hepta-memory-federation-wire/src/codec.rs",
            "codex-rs/hepta-supervisor/src/qualification_fault.rs",
        ])
        assert b"Ran 41 tests" in z.read("formatter-tests.log") and b"Ran 3 tests" in z.read("starlark-tests.log")
        for label in ["check", "original"]:
            report = receipt["fixed_base"][label]
            assert int(z.read("full-" + label + ".exit")) == report["exit"] == 0
            assert z.read("after-" + label + ".status").decode().splitlines() == report["changed_paths"] == []
            assert hashlib.sha256(z.read("full-" + label + ".log")).hexdigest() == report["log_sha256"]
    print(json.dumps({"source": NEW, "paired_source_rows": 12, "before_and_after_standalone_supervisor_test": "1/1 each", "context_identity_policy_and_wire_workspace_membership": "unresolved on both source commits", "fixed_base": receipt["fixed_base"]}, indent=2))


if __name__ == "__main__":
    main()
