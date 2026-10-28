"""Source-custody and observation-integrity tests; no Windows substitute claim."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from experiments.multimodal_output_portfolio.closure_20261028 import ops_windows_acl_probe as probe


ROOT = Path(__file__).resolve().parents[3]


def complete_transcript():
    # Structurally complete parser fixture, not an assertion of native behavior.
    lines = [f"CHECK\t{name}\ttrue" for name in sorted(probe.CHECKS)]
    lines += [f"OP\t{name}\ttrue\t0\tNone" for name in sorted(probe.OPS)]
    lines += [f"REPAIR\t{name}\tfalse" for name in sorted(probe.REPAIRS)]
    lines += [f"OPEN\t{name}\t{access}\t{mask}\tfalse\t5" for name in sorted(probe.OPEN_LABELS) for access, mask in probe.OPEN_MASKS.items()]
    for name in sorted(probe.ACL_LABELS):
        lines += [f"ACL\t{name}\t1", f"ACE\t{name}\t0\t0\t03\t001f01ff\t001f01ff\tS-1-1-0"]
    for name in sorted(probe.TOKEN_LABELS):
        lines.append(f"FLAG\t{name}\trestricted\tfalse")
        for kind in sorted(probe.TOKEN_KINDS):
            count = 0 if (name, kind) == ("broad.base", "restricting") else 1
            lines.append(f"GROUPS\t{name}\t{kind}\t{count}")
            if count:
                lines.append(f"TOKEN\t{name}\t{kind}\t0\t00000000\tS-1-1-0")
    return lines + ["DONE\t2"]


class ProbeIntegrityTests(unittest.TestCase):
    def test_actual_git_rejects_live_and_index_only_source_changes(self):
        paths = (*probe.PRODUCTION, *probe.CONFIG, *((probe.RELATIVE / p).as_posix() for p in probe.HARNESS))
        paths += ((probe.RELATIVE / "ops_windows_acl_probe.py").as_posix(),)
        with tempfile.TemporaryDirectory(prefix="hepta-acl-custody-") as temporary:
            fixture = Path(temporary)
            for relative in paths:
                path = fixture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / relative).read_bytes())
            def git(*args):
                return subprocess.check_output(["git", "-C", str(fixture), *args], stderr=subprocess.STDOUT)
            git("init", "--quiet")
            git("config", "core.autocrlf", "false")
            git("add", ".")
            git("-c", "user.name=ACL probe fixture", "-c", "user.email=fixture@invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "owned fixture")
            head = git("rev-parse", "HEAD").decode().strip()
            records, blobs = probe.bind_sources(fixture, head)
            source = fixture / probe.PRODUCTION[0]
            original = source.read_bytes()
            source.write_bytes(original + b"\n// changed fixture\n")
            with self.assertRaisesRegex(ValueError, "working-tree bytes"):
                probe.bind_sources(fixture, head)
            git("add", probe.PRODUCTION[0])
            source.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "index differs"):
                probe.bind_sources(fixture, head)
            crate = fixture / "isolated"
            probe.prepare(crate, blobs)
            for path in probe.PRODUCTION:
                self.assertEqual((crate / "src" / Path(path).name).read_bytes(), blobs[path])
            self.assertEqual(records[probe.PRODUCTION[0]]["sha256"], probe.sha(original))

    def test_complete_transcript_keeps_false_invariant_as_observed_failure(self):
        lines = complete_transcript()
        probe.observations("\n".join(lines))
        lines[0] = lines[0].removesuffix("true") + "false"
        rows = probe.observations("\n".join(lines))
        self.assertEqual([row["name"] for row in rows if row["kind"] == "CHECK" and not row["passed"]], [lines[0].split("\t")[1]])

    def test_incomplete_or_duplicated_native_observation_cannot_complete(self):
        lines = complete_transcript()
        cases = {
            "done_only": ["DONE\t2"],
            "missing_check": lines[1:],
            "duplicate_check": [lines[0], *lines],
            "missing_open_group": [line for line in lines if not line.startswith("OPEN\tbroad.outside.file\t")],
            "missing_open_mask": [line for line in lines if not line.startswith("OPEN\tbroad.outside.file\tdelete\t")],
            "missing_acl": [line for line in lines if not line.startswith("ACL\tbroad.fixture\t")],
            "missing_ace": [line for line in lines if not line.startswith("ACE\tbroad.fixture\t")],
            "missing_token_kind": [line for line in lines if not line.startswith("GROUPS\tbroad.base\trestricting\t")],
            "missing_token_sid": [line for line in lines if not line.startswith("TOKEN\tbroad.production\tuser\t")],
            "missing_done": lines[:-1],
            "duplicate_done": [*lines, "DONE\t2"],
        }
        for name, partial in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                probe.observations("\n".join(partial))

    def test_dependency_without_existing_checksum_cannot_enter_probe(self):
        original = (ROOT / "codex-rs/Cargo.lock").read_bytes()
        selected = probe.dependency_closure(original)
        checksum = next(p["checksum"] for p in selected if p["name"] == "anyhow")
        corrupted = original.replace(f'checksum = "{checksum}"'.encode(), b'checksum = "missing"', 1)
        with self.assertRaisesRegex(ValueError, "checksum"):
            probe.dependency_closure(corrupted)


if __name__ == "__main__":
    unittest.main()
