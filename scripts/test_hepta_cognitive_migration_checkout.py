#!/usr/bin/env python3
"""Exercise Windows Git checkout bytes against the actual SQLite schema oracle."""

import hashlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = Path("codex-rs/hepta-memory/migrations")
SOURCE = (ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs").read_text()
OBJECTS = re.findall(
    r'\(\s*"([^"]+)",\s*"([^"]+)"\s*,?\s*\)',
    SOURCE.split("const REQUIRED_SCHEMA_OBJECTS:")[1].split(
        "const REQUIRED_SCHEMA_ORACLE_SHA256:"
    )[0],
)
EXPECTED = re.search(
    r'REQUIRED_SCHEMA_ORACLE_SHA256: &str\s*=\s*"([a-f0-9]+)"', SOURCE
).group(1)


def schema_oracle(root: Path) -> str:
    with sqlite3.connect(":memory:") as database:
        for migration in sorted((root / MIGRATIONS).glob("*.sql")):
            database.executescript(migration.read_bytes().decode("utf-8"))
        rows = []
        for name, expected_type in OBJECTS:
            kind, sql = database.execute(
                "SELECT type, sql FROM sqlite_schema WHERE name = ?", (name,)
            ).fetchone()
            assert kind == expected_type
            rows.append((name, kind, sql))
        hasher = hashlib.sha256()
        parts = [
            b"hepta:cognitive:required-schema-oracle:v1",
            len(rows).to_bytes(8, "big"),
        ]
        parts.extend(value.encode("utf-8") for row in sorted(rows) for value in row)
        for part in parts:
            hasher.update(len(part).to_bytes(8, "big"))
            hasher.update(part)
        return hasher.hexdigest()


class CognitiveMigrationCheckoutTests(unittest.TestCase):
    def checkout(self, directory: Path, attributes: str) -> Path:
        source = directory / "source"
        source.mkdir()
        shutil.copytree(ROOT / MIGRATIONS, source / MIGRATIONS)
        (source / ".gitattributes").write_text(attributes, encoding="utf-8")
        commands = [
            ["git", "init", "-q", str(source)],
            ["git", "-C", str(source), "add", "."],
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Checkout fixture",
                "-c",
                "user.email=checkout@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "migration inputs",
            ],
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "clone",
                "-q",
                "--local",
                str(source),
                str(directory / "checkout"),
            ],
        ]
        for command in commands:
            subprocess.run(command, check=True, capture_output=True)
        return directory / "checkout"

    def test_windows_checkout_preserves_the_exact_migration_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = self.checkout(
                Path(temporary), (ROOT / ".gitattributes").read_text()
            )
            self.assertEqual(schema_oracle(checkout), EXPECTED)
            for migration in (checkout / MIGRATIONS).glob("*.sql"):
                self.assertNotIn(b"\r", migration.read_bytes())

    def test_unpinned_windows_checkout_reproduces_the_native_ci_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = self.checkout(Path(temporary), "")
            self.assertEqual(
                schema_oracle(checkout),
                "0d4c6e5e3e1c7f5cd356f779db66da8ab281525b4e7250455617d482d5ea6aa5",
            )
            self.assertNotEqual(schema_oracle(checkout), EXPECTED)


if __name__ == "__main__":
    unittest.main()
