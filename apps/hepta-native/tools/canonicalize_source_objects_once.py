#!/usr/bin/env python3
"""Materialize canonical source-object refresh, then remove this transport."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def replace(relative, old, new):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"canonical-map preimage mismatch: {relative}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main():
    relative = "apps/hepta-native/tools/prepare_current_source.py"
    replace(relative, "def sync_metadata():", '''def refresh_source_objects(entries, revision):
    """Refresh identities without dropping paths; match the verifier's order."""
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("native source objects must be a nonempty list")
    paths = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"path", "object", "blobSha"}:
            raise RuntimeError("invalid native source object entry")
        path = entry.get("path")
        if (not isinstance(path, str) or not path or path.startswith("/")
                or ":" in path or chr(92) in path
                or any(part in ("", ".", "..") for part in path.split("/"))):
            raise RuntimeError("invalid native source object path")
        if path in paths:
            raise RuntimeError("duplicate native source object path")
        paths.append(path)
    return [
        {"path": path, "object": git("rev-parse", f"{revision}:{path}")}
        for path in sorted(paths)
    ]


def sync_metadata():''')
    replace(relative,
            '    for item in data.get("sourceObjects", []):\n        item["object"] = git("rev-parse", f"{source}:{item[\'path\']}")',
            '    data["sourceObjects"] = refresh_source_objects(data.get("sourceObjects"), source)')
    replace("scripts/test_hepta_ui_native_source.py",
            "    def test_wrong_current_branch_refused(self):", '''    def test_source_objects_use_the_verifiers_canonical_path_order(self):
        revision = self.git("rev-parse", "HEAD")
        paths = ["apps/hepta-native/source.rs", "apps/hepta-native/CURRENT_SOURCE.json"]
        entries = [{"path": path, "object": "0" * 40} for path in paths]
        result = source.refresh_source_objects(entries, revision)
        self.assertEqual(result, [
            {"path": path, "object": self.git("rev-parse", f"{revision}:{path}")}
            for path in sorted(paths)
        ])

    def test_duplicate_source_object_cannot_be_silently_collapsed(self):
        entry = {"path": "apps/hepta-native/source.rs", "object": "0" * 40}
        with self.assertRaises(RuntimeError):
            source.refresh_source_objects([entry, entry], self.git("rev-parse", "HEAD"))

    def test_invalid_source_object_paths_are_rejected(self):
        for path in ("/absolute", "../outside", "apps//empty", "HEAD:path", "apps/./source"):
            with self.assertRaises(RuntimeError):
                source.refresh_source_objects([{"path": path}], self.git("rev-parse", "HEAD"))

    def test_wrong_current_branch_refused(self):''')
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
