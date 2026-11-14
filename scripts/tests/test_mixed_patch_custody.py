import contextlib
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_source_custody_container as custody

PARSER = Path(__file__).resolve().parents[2] / custody.MIXED / "patch_parser.py"
spec = importlib.util.spec_from_file_location("maintained_mixed_patch_parser", PARSER)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class MixedContainerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = custody.MIXED
        self.collection = self.root / self.directory
        self.collection.mkdir(parents=True)
        self.payloads = {}
        self.sources = {}
        objects = []
        for number in range(30):
            raw = f'raise RuntimeError("archived source must not run {number}")\n'.encode()
            fp = custody.identity(raw)
            name = "objects/" + fp["oid"] + ".py"
            self.payloads[name] = raw
            self.sources[self.directory + "/" + name] = raw
            objects.append(
                {
                    "relative_path": name,
                    "git_blob_sha": fp["oid"],
                    "sha256": fp["sha256"],
                    "bytes": fp["bytes"],
                }
            )
        notices = []
        for number in range(3):
            raw = f"Original notice {number}\n".encode()
            fp = custody.identity(raw)
            name = "notices/" + fp["oid"] + ".txt"
            self.payloads[name] = raw
            notices.append(
                {
                    "relative_path": name,
                    "git_blob_sha": fp["oid"],
                    "sha256": fp["sha256"],
                    "bytes": fp["bytes"],
                    "role": "auxiliary original third-party notice",
                }
            )
        self.document = {
            "schema": "isolated-frozen-patch-new-file-projection-v1",
            "preserved_source_executed": False,
            "patch_applied": False,
            "new_frozen_candidates_counted": 0,
            "source_candidate_sets_unchanged": True,
            "boundaries": ["DRAFT", "SHADOW_ONLY", "DENY_ALL", "HOLD_NO_GO"],
            "frozen_candidate_count": 6116,
            "formal_verified_count_unchanged": 5887,
            "additional_source_object_count": 30,
            "additional_source_bytes": sum(map(len, self.sources.values())),
            "auxiliary_notice_count": 3,
            "objects": objects,
            "notices": notices,
        }
        original = (json.dumps(self.document) + "\n").encode()
        (self.collection / "SOURCE_MANIFEST.json").write_bytes(original)
        self.payloads.update(
            {
                "SOURCE_MANIFEST.json": original,
                "README.md": b"Original HOLD control\n",
                "PARSER_QUALIFICATION.json": b'{"historical":true}\n',
                "patch_parser.py": b'raise RuntimeError("archived parser must not run")\n',
                "verify_sources.py": b'raise RuntimeError("archived verifier must not run")\n',
            }
        )
        controls = {
            name: custody.identity(raw)["oid"]
            for name, raw in self.payloads.items()
            if not name.startswith("objects/")
        }
        registered = patch.dict(
            custody.SNAPSHOTS,
            {
                self.directory: {
                    "manifest": "SOURCE_MANIFEST.json",
                    "notice_count": 3,
                    "controls": controls,
                }
            },
            clear=True,
        )
        registered.start()
        self.addCleanup(registered.stop)
        pointers = {
            row["relative_path"]: "/objects/" + str(i) for i, row in enumerate(objects)
        }
        self.rows = [
            {
                "path": self.directory + "/" + name,
                "member": name,
                "mode": "100644",
                **custody.identity(raw),
                "role": "source" if name in pointers else "prior_control",
                "provenance_pointer": pointers.get(name),
            }
            for name, raw in self.payloads.items()
        ]
        self.index = {
            "schema": custody.SCHEMA,
            "source_commit": custody.SOURCE_COMMIT,
            "original_directory": self.directory,
            "archive": "source-custody.tar.gz",
            "source_count": 30,
            "source_bytes": self.document["additional_source_bytes"],
            "member_count": 38,
            "member_bytes": sum(map(len, self.payloads.values())),
            "members": self.rows,
            "source_executed": False,
            "scientific_or_runtime_qualification": False,
        }
        self.write_archive()

    def write_archive(self):
        stream = io.BytesIO()
        with tarfile.open(
            fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT
        ) as archive:
            for name, raw in self.payloads.items():
                member = tarfile.TarInfo(name)
                member.mode, member.size, member.mtime = 0o644, len(raw), 0
                archive.addfile(member, io.BytesIO(raw))
        raw = stream.getvalue()
        packed = gzip.compress(raw, mtime=0)
        self.index.update(
            tar_bytes=len(raw),
            tar_sha256=custody.identity(raw)["sha256"],
            archive_bytes=len(packed),
            archive_sha256=custody.identity(packed)["sha256"],
        )
        (self.collection / "source-custody.tar.gz").write_bytes(packed)
        self.write_index()

    def write_index(self):
        (self.collection / "ARCHIVE_MANIFEST.json").write_text(json.dumps(self.index))

    def test_all_sources_and_original_controls_verify_without_execution(self):
        self.assertEqual(
            custody.verify_container(self.root, self.directory), self.sources
        )
        self.assertEqual(
            custody.resolve_original_paths(self.root, list(self.sources)), self.sources
        )
        output = io.StringIO()
        with (
            patch.object(
                custody,
                "__file__",
                str(self.root / "scripts/verify_source_custody_container.py"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(custody.main([self.directory]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual((report["source_count"], report["notice_count"]), (30, 3))
        self.assertFalse(report["archived_source_executed"])
        self.assertFalse(report["research_or_runtime_qualification"])

    def test_mixed_pointer_must_bind_to_original_object_row(self):
        source = next(row for row in self.rows if row["role"] == "source")
        source["provenance_pointer"] = "/sources/0"
        self.write_index()
        with self.assertRaisesRegex(ValueError, "source manifest binding"):
            custody.verify_container(self.root, self.directory)

    def test_archived_parser_bytes_and_notice_bytes_are_bound(self):
        for name in ("patch_parser.py", self.document["notices"][0]["relative_path"]):
            with self.subTest(name=name):
                original = self.payloads[name]
                self.payloads[name] = b"!" + original[1:]
                self.write_archive()
                with self.assertRaisesRegex(ValueError, "member identity mismatch"):
                    custody.verify_container(self.root, self.directory)
                self.payloads[name] = original

    def test_mixed_source_and_notice_boundaries_are_retained(self):
        for key, value in (
            ("preserved_source_executed", True),
            ("patch_applied", True),
            ("new_frozen_candidates_counted", 1),
            ("formal_verified_count_unchanged", 5888),
            ("boundaries", ["ALLOW"]),
            ("auxiliary_notice_count", 0),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.document)
                changed[key] = value
                with self.assertRaises(ValueError):
                    custody.source_rows(changed, self.directory)
        changed = copy.deepcopy(self.document)
        changed["notices"][0]["git_blob_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "notice binding"):
            custody.source_rows(changed, self.directory)


def synthetic_patch(raw):
    lines = parser.lf_lines(raw)
    content = []
    for line in lines:
        content.append(b"+" + (line if line.endswith(b"\n") else line + b"\n"))
    if not raw.endswith(b"\n"):
        content.append(b"\\ No newline at end of file\n")
    oid = parser.fp(raw)["git_blob_sha"].encode()[:10]
    header = [
        b"diff --git a/fixture.txt b/fixture.txt\n",
        b"new file mode 100644\n",
        b"index 0000000000.." + oid + b"\n",
        b"--- /dev/null\n",
        b"+++ b/fixture.txt\n",
        b"@@ -0,0 +1," + str(len(lines)).encode() + b" @@\n",
    ]
    return header + content


class MixedPatchParserRegressionTests(unittest.TestCase):
    def test_five_exact_byte_cases(self):
        for raw in (
            b"line\n",
            b"without final newline",
            b"crlf\r\n",
            b"caf\xc3\xa9\n\n",
            b"embedded\rcarriage\n",
        ):
            with self.subTest(raw=raw):
                item, reason = parser.parse_new_file(synthetic_patch(raw))
                self.assertIsNone(reason)
                self.assertEqual(item["raw"], raw)
                self.assertEqual(item["no_final_newline"], not raw.endswith(b"\n"))

    def test_nine_original_malformed_boundaries(self):
        valid = synthetic_patch(b"x")
        with_lf = synthetic_patch(b"x\n")
        variants = {
            "truncated_add_line_missing_marker": valid[:-2] + [b"+x"],
            "duplicate_new_file_mode": valid[:2] + [valid[1]] + valid[2:],
            "inconsistent_optional_index_mode": valid[:2]
            + [valid[2].rstrip(b"\n") + b" 100755\n"]
            + valid[3:],
            "incorrect_git_index": valid[:2]
            + [b"index 0000000000..1111111111\n"]
            + valid[3:],
            "declared_line_count_too_large": valid[:5]
            + [b"@@ -0,0 +1,2 @@\n"]
            + valid[6:],
            "unexplained_additional_hunk": valid + [b"@@ -0,0 +1 @@\n", b"+y\n"],
            "context_in_new_file": with_lf[:-1] + [b" x\n"],
            "content_after_no_newline": valid + [b"+y\n"],
            "different_new_path_label": valid[:4]
            + [b"+++ b/different.txt\n"]
            + valid[5:],
        }
        for name, block in variants.items():
            with self.subTest(case=name):
                try:
                    item, reason = parser.parse_new_file(block)
                except ValueError:
                    continue
                self.assertIsNone(item)
                self.assertIsInstance(reason, str)


if __name__ == "__main__":
    unittest.main()
