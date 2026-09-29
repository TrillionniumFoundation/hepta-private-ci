#!/usr/bin/env python3
"""Bind knowledge.graph qualification and acceptance to the full migration tree."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "scripts/hepta_kg_acceptance_manifest.py"
LANE = ROOT / "scripts/hepta_kg_qualification_lane.sh"
TEST = ROOT / "scripts/test_hepta_kg_acceptance_manifest.py"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one exact predecessor, found {count}")
    return text.replace(old, new, 1)


def patch_acceptance() -> None:
    text = ACCEPTANCE.read_text(encoding="utf-8")
    if "def sha256_tracked_tree" in text:
        return
    text = replace_once(
        text,
        'SCHEMA_PATH = "codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql"\n',
        'SCHEMA_ROOT = "codex-rs/hepta-memory/migrations"\n',
        "schema root constant",
    )
    text = replace_once(
        text,
        "    SCHEMA_PATH,\n",
        "    SCHEMA_ROOT,\n",
        "schema fingerprint root",
    )
    digest_anchor = """def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_clean(root: Path) -> None:
"""
    digest_replacement = """def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tracked_tree(root: Path, relative_root: str) -> str:
    paths = [
        value
        for value in run_git(root, "ls-files", "--", relative_root).splitlines()
        if value
    ]
    if not paths:
        raise AcceptanceError(f"tracked acceptance tree is empty: {relative_root}")
    digest = hashlib.sha256()
    for relative in sorted(paths):
        path = root / relative
        if not path.is_file():
            raise AcceptanceError(f"tracked acceptance input is not a file: {relative}")
        entry = {
            "path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def require_clean(root: Path) -> None:
"""
    text = replace_once(
        text,
        digest_anchor,
        digest_replacement,
        "tracked schema-tree digest",
    )
    text = replace_once(
        text,
        '        "schemaSha256": required_digest(SCHEMA_PATH),\n',
        '        "schemaSha256": sha256_tracked_tree(root, SCHEMA_ROOT),\n',
        "candidate schema digest",
    )
    ACCEPTANCE.write_text(text, encoding="utf-8")


def patch_lane() -> None:
    text = LANE.read_text(encoding="utf-8")
    if "def tracked_tree_digest" in text:
        return
    helper_anchor = """def file_digest(relative: str) -> str | None:
    path = root / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

results = []
"""
    helper_replacement = """def file_digest(relative: str) -> str | None:
    path = root / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tracked_tree_digest(relative_root: str) -> str | None:
    try:
        tracked = git("ls-files", "--", relative_root).splitlines()
    except subprocess.CalledProcessError:
        return None
    paths = sorted(value for value in tracked if value)
    if not paths:
        return None
    digest = hashlib.sha256()
    for relative in paths:
        path = root / relative
        if not path.is_file():
            return None
        entry = {
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()

results = []
"""
    text = replace_once(text, helper_anchor, helper_replacement, "lane tree digest helper")
    old_schema = """    "kgSchemaSha256": file_digest(
        "codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql"
    ),
"""
    new_schema = """    "kgSchemaSha256": tracked_tree_digest(
        "codex-rs/hepta-memory/migrations"
    ),
"""
    text = replace_once(text, old_schema, new_schema, "lane schema digest")
    LANE.write_text(text, encoding="utf-8")


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    fixture_anchor = """            "codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql": "CREATE TABLE kg(x);\\n",
"""
    fixture_replacement = fixture_anchor + """            "codex-rs/hepta-memory/migrations/0017_kg_generation_kernel_delta_receipts.sql": "CREATE TABLE kg_delta(x);\\n",
"""
    if "0017_kg_generation_kernel_delta_receipts.sql" not in text:
        text = replace_once(
            text,
            fixture_anchor,
            fixture_replacement,
            "multi-migration fixture",
        )

    if "test_any_schema_migration_change_invalidates_candidate" not in text:
        test_anchor = """    def test_mixed_harness_receipt_is_rejected(self) -> None:
"""
        test_insertion = """    def test_any_schema_migration_change_invalidates_candidate(self) -> None:
        before = self.module.candidate_fingerprint(self.root)
        migration = (
            self.root
            / "codex-rs/hepta-memory/migrations/0017_kg_generation_kernel_delta_receipts.sql"
        )
        migration.write_text("CREATE TABLE kg_delta_changed(x);\\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "schema drift"],
            check=True,
        )
        after = self.module.candidate_fingerprint(self.root)
        self.assertNotEqual(before["schemaSha256"], after["schemaSha256"])
        self.assertNotEqual(before["sourceManifestSha256"], after["sourceManifestSha256"])

    def test_mixed_harness_receipt_is_rejected(self) -> None:
"""
        text = replace_once(
            text,
            test_anchor,
            test_insertion,
            "schema drift invalidation test",
        )
    TEST.write_text(text, encoding="utf-8")


def main() -> int:
    patch_acceptance()
    patch_lane()
    patch_test()
    print("PASS_APPLY_KG_ACCEPTANCE_BINDING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
