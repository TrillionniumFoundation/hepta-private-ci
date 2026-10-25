"""Synthetic evidence controls; none of these tests qualify native Rust behavior."""

import contextlib
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import native_bootstrap_evidence as evidence


def report(phase):
    expected = evidence.EXPECTED[phase]
    root = ET.Element(
        "testsuites",
        name="native-bootstrap",
        tests=str(len(expected)),
        failures="0",
        errors="0",
    )
    for classname in sorted({name for name, _ in expected}):
        names = sorted(name for group, name in expected if group == classname)
        suite = ET.SubElement(
            root,
            "testsuite",
            name=classname,
            tests=str(len(names)),
            failures="0",
            errors="0",
        )
        for name in names:
            ET.SubElement(
                suite,
                "testcase",
                classname=classname,
                name=name,
                timestamp="2026-10-24T21:00:00Z",
            )
    return root


class ReportTests(unittest.TestCase):
    def check(self, root, phase):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "junit.xml"
            ET.ElementTree(root).write(path)
            return evidence.validate_report(path, phase)

    def test_exact_five_four_ten_reports(self):
        self.assertEqual(
            {k: len(v) for k, v in evidence.EXPECTED.items()},
            {"owning": 5, "integration": 4, "bootstrap": 10},
        )
        for phase in evidence.EXPECTED:
            self.assertEqual(
                set(self.check(report(phase), phase)), evidence.EXPECTED[phase]
            )

    def test_missing_duplicate_identity_counts_and_result_tampering(self):
        for phase in evidence.EXPECTED:
            for target, key, value in (
                (".", "name", "native-fixtures"),
                (".", "tests", "0"),
                (".", "errors", "1"),
                (".", "failures", "1"),
                (".", "skipped", "1"),
                ("testsuite", "name", "wrong-owner"),
                ("testsuite", "tests", "0"),
                ("testsuite", "disabled", "1"),
                ("testsuite", "errors", None),
                ("testsuite/testcase", "name", "wrong-test"),
                ("testsuite/testcase", "classname", "codex-hepta-memory::lib"),
                ("testsuite/testcase", "timestamp", None),
            ):
                with self.subTest(phase=phase, target=target, key=key):
                    root = report(phase)
                    node = root if target == "." else root.find(target)
                    node.attrib.pop(key, None) if value is None else node.set(
                        key, value
                    )
                    with self.assertRaises(ValueError):
                        self.check(root, phase)
            for tag in (
                "failure",
                "error",
                "skipped",
                "rerunFailure",
                "flakyFailure",
                "unknown",
            ):
                root = report(phase)
                ET.SubElement(root.find("testsuite/testcase"), tag)
                with self.assertRaises(ValueError):
                    self.check(root, phase)
            for mutation in (
                "missing",
                "duplicate",
                "extra-suite",
                "unknown-suite-child",
            ):
                root = report(phase)
                suite = root.find("testsuite")
                if mutation == "missing":
                    suite.remove(suite[0])
                elif mutation == "duplicate":
                    suite.append(copy.deepcopy(suite[0]))
                elif mutation == "extra-suite":
                    root.append(copy.deepcopy(suite))
                else:
                    ET.SubElement(suite, "system-out")
                with self.assertRaises(ValueError):
                    self.check(root, phase)
        with self.assertRaises(ValueError):
            self.check(report("owning"), "integration")

    def test_new_profile_does_not_change_existing_profiles(self):
        path = Path(__file__).resolve().parents[2] / "codex-rs/.config/nextest.toml"
        text = path.read_text()
        old = text.split("\n# Isolated bootstrap validation;", 1)[0].encode()
        self.assertEqual(
            evidence.common.hashlib.sha256(old).hexdigest(),
            "2c13217e00ea45a022286aa217bcc04c2cf1ea6eedb56284a55dc3e48c99de07",
        )
        profiles = tomllib.loads(text)["profile"]
        for phase, expected in evidence.EXPECTED.items():
            profile = profiles[f"native-bootstrap-{phase}"]
            self.assertNotIn("inherits", profile)
            self.assertEqual(profile["retries"], 0)
            self.assertEqual(
                profile["junit"],
                dict(
                    path="junit.xml",
                    **{
                        "report-name": "native-bootstrap",
                        "store-success-output": True,
                        "store-failure-output": True,
                        "report-skipped": "none",
                    },
                ),
            )
            override = profile["overrides"][0]
            self.assertEqual(
                set(override["filter"].split(" | ")),
                {f"test(={name})" for _, name in expected},
            )
            self.assertEqual(override["junit"]["report-skipped"], "all")
            self.assertEqual(
                profile["slow-timeout"], {"period": "30s", "terminate-after": 8}
            )
            self.assertEqual(override["retries"], 0)

    def test_child_helpers_are_not_counted(self):
        names = {name for values in evidence.EXPECTED.values() for _, name in values}
        self.assertFalse(
            any(
                name.endswith("::bootstrap_child") or name.endswith("::recovery_child")
                for name in names
            )
        )

    def test_missing_and_malformed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "junit.xml"
            with self.assertRaises(FileNotFoundError):
                evidence.validate_report(path, "owning")
            path.write_text("<testsuites>")
            with self.assertRaises(ET.ParseError):
                evidence.validate_report(path, "owning")


class BindingTests(unittest.TestCase):
    def test_byte_exact_patch_source_drift_commands_and_failed_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, out = root / "repo", root / "evidence"
            repo.mkdir()
            out.mkdir()

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(repo), *args], stderr=subprocess.PIPE
                )

            def commit():
                git("add", ".")
                git(
                    "-c",
                    "user.name=Evidence control",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-qm",
                    "control",
                )
                return git("rev-parse", "HEAD").decode().strip()

            git("init", "-q")
            lock = repo / "codex-rs/Cargo.lock"
            lock.parent.mkdir()
            lock.write_text("synthetic lock\n")
            (lock.parent / "rustfmt.toml").write_text('edition = "2024"\n')
            fixture = repo / "fixture.txt"
            fixture.write_text("before\n\n")
            base = commit()
            tree = git("rev-parse", "HEAD^{tree}").decode().strip()
            lock_hash = git("rev-parse", "HEAD:codex-rs/Cargo.lock").decode().strip()
            fixture.write_text("after\n\n")
            head = commit()
            with (
                contextlib.chdir(repo),
                patch.dict(os.environ, CANDIDATE_SHA=head, WORKFLOW_SHA=head),
                patch.multiple(
                    evidence,
                    BASE=base,
                    BASE_TREE=tree,
                    PINS={
                        "fixture.txt": evidence.digest(fixture),
                        "codex-rs/rustfmt.toml": evidence.digest(
                            lock.parent / "rustfmt.toml"
                        ),
                    },
                    CHANGED_SOURCES={"fixture.txt"},
                    CI_FILES=set(),
                    SUPPORT={"codex-rs/Cargo.lock", "codex-rs/rustfmt.toml"},
                ),
                patch.object(evidence.common, "LOCK", lock_hash),
            ):
                evidence.bind(out)
                self.assertIn(
                    "codex-rs/rustfmt.toml",
                    json.loads((out / "source.json").read_text())["files"],
                )
                raw = git("diff", "--binary", "--full-index", base, head)
                self.assertTrue(raw.endswith(b" \n"))
                self.assertEqual((out / "candidate.patch").read_bytes(), raw)
                (out / "tools.json").write_text(
                    json.dumps(
                        {
                            "versions": evidence.TOOL_VERSIONS,
                            "sha256": evidence.common.TOOL_HASHES,
                        }
                    )
                )
                (out / "rustfmt.exit").write_text("0\n")
                for phase in evidence.EXPECTED:
                    target = out / phase
                    target.mkdir()
                    ET.ElementTree(report(phase)).write(target / "junit.xml")
                    (target / "command.txt").write_text(
                        evidence.shlex.join(evidence.command(phase))
                    )
                    (target / "native-tests.log").write_text(
                        "".join(
                            f"PASS [0.001s] {owner} {name}\n"
                            for owner, name in sorted(evidence.EXPECTED[phase])
                        )
                    )
                    (target / "started-unix.txt").write_text("1\n")
                    for name in ("test.exit", "tee.exit", "report-copy.exit"):
                        (target / name).write_text("0\n")
                self.assertEqual(set(evidence.verify(out)), set(evidence.EXPECTED))
                for phase in evidence.EXPECTED:
                    for name in (
                        "test.exit",
                        "tee.exit",
                        "report-copy.exit",
                        "command.txt",
                    ):
                        path = out / phase / name
                        original = path.read_bytes()
                        path.write_text("100\n")
                        with self.assertRaises(ValueError):
                            evidence.verify(out)
                        path.write_bytes(original)
                for phase in evidence.EXPECTED:
                    for name, bad in (
                        ("started-unix.txt", "9999999999\n"),
                        ("native-tests.log", "not native output\n"),
                    ):
                        path = out / phase / name
                        saved = path.read_bytes()
                        path.write_text(bad)
                        with self.assertRaises(ValueError):
                            evidence.verify(out)
                        path.write_bytes(saved)
                    path = out / phase / "native-tests.log"
                    saved = path.read_text()
                    for bad in (
                        saved.replace("PASS", "FAIL", 1),
                        saved + saved.splitlines()[0] + "\n",
                    ):
                        path.write_text(bad)
                        with self.assertRaises(ValueError):
                            evidence.verify(out)
                    path.write_text(saved)
                fmt = out / "rustfmt.exit"
                fmt.write_text("1\n")
                with self.assertRaises(ValueError):
                    evidence.verify(out)
                fmt.write_text("0\n")
                receipt_path = out / "source.json"
                saved_receipt = receipt_path.read_bytes()
                for key in ("tree", "head", "base", "base_tree"):
                    altered = json.loads(saved_receipt)
                    altered[key] = "wrong"
                    receipt_path.write_text(json.dumps(altered))
                    with self.assertRaises(ValueError):
                        evidence.verify(out)
                altered = json.loads(saved_receipt)
                altered["files"]["fixture.txt"]["blob"] = "wrong"
                receipt_path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    evidence.verify(out)
                receipt_path.write_bytes(saved_receipt)
                tools_path = out / "tools.json"
                tools_bytes = tools_path.read_bytes()
                tools_path.write_text(json.dumps({"versions": {}, "sha256": {}}))
                with self.assertRaises(ValueError):
                    evidence.verify(out)
                tools_path.write_bytes(tools_bytes)
                # The real checksum-bound nextest binary emits a verbose version.
                # Reject truncation and changes to every identity line, not merely
                # a mismatched first-line version number.
                original_tools = json.loads(tools_bytes)
                nextest_lines = original_tools["versions"]["cargo-nextest"].splitlines()
                self.assertEqual(len(nextest_lines), 5)
                for value in [
                    nextest_lines[0],
                    *[
                        "\n".join(
                            lines[:index] + ["wrong identity"] + lines[index + 1 :]
                        )
                        for index in range(len(nextest_lines))
                        for lines in [nextest_lines]
                    ],
                ]:
                    altered = copy.deepcopy(original_tools)
                    altered["versions"]["cargo-nextest"] = value
                    tools_path.write_text(json.dumps(altered))
                    with self.assertRaisesRegex(ValueError, "unverified tool identity"):
                        evidence.verify(out)
                for binary in original_tools["sha256"]:
                    altered = copy.deepcopy(original_tools)
                    altered["sha256"][binary] = "0" * 64
                    tools_path.write_text(json.dumps(altered))
                    with self.assertRaisesRegex(ValueError, "unverified tool identity"):
                        evidence.verify(out)
                tools_path.write_bytes(tools_bytes)
                source_path = out / "source.json"
                source_bytes = source_path.read_bytes()
                receipt = json.loads(source_bytes)
                receipt["files"] = {}
                source_path.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):
                    evidence.verify(out)
                source_path.write_bytes(source_bytes)
                missing = out / "integration/report-copy.exit"
                saved = missing.read_bytes()
                missing.unlink()
                with self.assertRaises(FileNotFoundError):
                    evidence.verify(out)
                missing.write_bytes(saved)
                fixture.write_text("drift\n")
                with self.assertRaises(ValueError):
                    evidence.verify(out)
                git("checkout", "--", "fixture.txt")
                with patch.dict(os.environ, WORKFLOW_SHA="wrong"):
                    with self.assertRaises(ValueError):
                        evidence.bind(out)
                with patch.dict(evidence.PINS, {"fixture.txt": "unreviewed"}):
                    with self.assertRaises(ValueError):
                        evidence.bind(out)
                with patch.object(evidence, "CI_FILES", {"unexpected.py"}):
                    with self.assertRaises(ValueError):
                        evidence.bind(out)
                with patch.object(
                    evidence,
                    "CHANGED_SOURCES",
                    {
                        "fixture.txt",
                        "codex-rs/hepta-agentd/tests/support/cognitive_recovery_snapshot.rs",
                    },
                ):
                    with self.assertRaisesRegex(
                        ValueError, "unexpected/missing candidate paths"
                    ):
                        evidence.bind(out)
                original_run = evidence.run

                def changed_with_extra(*args):
                    result = original_run(*args)
                    return (
                        result + "\nunexpected.py"
                        if args[:4] == ("git", "diff", "--no-renames", "--name-only")
                        else result
                    )

                with patch.object(evidence, "run", side_effect=changed_with_extra):
                    with self.assertRaisesRegex(
                        ValueError, "unexpected/missing candidate paths"
                    ):
                        evidence.bind(out)
                with patch.dict(
                    evidence.PINS, {"codex-rs/rustfmt.toml": "wrong unchanged pin"}
                ):
                    with self.assertRaisesRegex(ValueError, "unreviewed source"):
                        evidence.bind(out)
                git("checkout", "-q", "--detach", base)
                git("apply", "--check", str(out / "candidate.patch"))
                git("apply", str(out / "candidate.patch"))
                self.assertEqual(fixture.read_text(), "after\n\n")
                self.assertEqual(git("diff", "--binary", "--full-index"), raw)

    def test_actual_workflow_loop_keeps_first_report_when_second_compile_fails(self):
        scripts = Path(__file__).resolve().parent
        workflow = (
            scripts.parent / "workflows/hepta-private-bootstrap.yml"
        ).read_text()
        section = workflow.split(
            "      - name: Five owning, four integration and ten bootstrap cases\n"
        )[1]
        shell = textwrap.dedent(
            section.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "evidence"
            out.mkdir()
            dest = root / ".github/scripts"
            dest.mkdir(parents=True)
            for name in ("native_bootstrap_evidence.py", "native_fixture_evidence.py"):
                shutil.copyfile(scripts / name, dest / name)
            original = root / "first.xml"
            ET.ElementTree(report("owning")).write(original)
            transient = (
                root / "codex-rs/target/nextest/native-bootstrap-owning/junit.xml"
            )
            transient.parent.mkdir(parents=True)
            binary = root / "bin"
            binary.mkdir()
            just = binary / "just"
            just.write_text(
                '#!/bin/sh\necho synthetic compile control\ncase " $* " in *" --lib "*) cp "$CONTROL_REPORT" "$CONTROL_NEXT_REPORT";; *) exit 100;; esac\n'
            )
            just.chmod(0o700)
            env = dict(
                os.environ,
                GITHUB_WORKSPACE=str(root),
                EVIDENCE=str(out),
                CONTROL_REPORT=str(original),
                CONTROL_NEXT_REPORT=str(transient),
                PATH=f"{binary}:{os.environ['PATH']}",
            )
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", shell],
                env=env,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                (out / "owning/junit.xml").read_bytes(), original.read_bytes()
            )
            self.assertFalse((out / "integration/junit.xml").exists())
            self.assertEqual((out / "integration/test.exit").read_text(), "100\n")
            self.assertNotEqual(
                (out / "integration/report-copy.exit").read_text(), "0\n"
            )

    def test_runner_errexit_preserves_failed_native_reports_and_runs_both_phases(self):
        scripts = Path(__file__).resolve().parent
        workflow = (
            scripts.parent / "workflows/hepta-private-bootstrap.yml"
        ).read_text()
        section = workflow.split(
            "      - name: Five owning, four integration and ten bootstrap cases\n"
        )[1]
        shell = textwrap.dedent(
            section.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
        )
        for failed_phase in evidence.EXPECTED:
            with (
                self.subTest(failed_phase=failed_phase),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                out = root / "evidence"
                out.mkdir()
                dest = root / ".github/scripts"
                dest.mkdir(parents=True)
                for name in (
                    "native_bootstrap_evidence.py",
                    "native_fixture_evidence.py",
                ):
                    shutil.copyfile(scripts / name, dest / name)
                transient = (
                    root / "codex-rs/target/nextest/native-bootstrap-owning/junit.xml"
                )
                transient.parent.mkdir(parents=True)
                for phase in evidence.EXPECTED:
                    fixture = report(phase)
                    if phase == failed_phase:
                        fixture.set("failures", "1")
                        fixture.find("testsuite").set("failures", "1")
                        ET.SubElement(
                            fixture.find("testsuite/testcase"), "failure"
                        ).text = "synthetic native failure"
                    ET.ElementTree(fixture).write(root / f"{phase}.xml")
                binary = root / "bin"
                binary.mkdir()
                just = binary / "just"
                just.write_text(
                    '#!/bin/sh\necho synthetic native control\ncase " $* " in *"database_init_tests"*) phase=bootstrap;; *" --lib "*) phase=owning;; *) phase=integration;; esac\ntarget="$GITHUB_WORKSPACE/codex-rs/target/nextest/native-bootstrap-$phase/junit.xml"; mkdir -p "$(dirname "$target")"; cp "$CONTROL_ROOT/$phase.xml" "$target" || exit 99\nif test "$phase" = "$CONTROL_FAILED_PHASE"; then exit 100; fi\n'
                )
                just.chmod(0o700)
                env = dict(
                    os.environ,
                    GITHUB_WORKSPACE=str(root),
                    EVIDENCE=str(out),
                    CONTROL_ROOT=str(root),
                    CONTROL_FAILED_PHASE=failed_phase,
                    CONTROL_NEXT_REPORT=str(transient),
                    PATH=f"{binary}:{os.environ['PATH']}",
                )
                result = subprocess.run(
                    [
                        "bash",
                        "--noprofile",
                        "--norc",
                        "-e",
                        "-o",
                        "pipefail",
                        "-c",
                        shell,
                    ],
                    env=env,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                for phase in evidence.EXPECTED:
                    self.assertEqual(
                        (out / phase / "junit.xml").read_bytes(),
                        (root / f"{phase}.xml").read_bytes(),
                    )
                    self.assertEqual(
                        (out / phase / "test.exit").read_text(),
                        "100\n" if phase == failed_phase else "0\n",
                    )
                    for receipt in ("tee.exit", "report-copy.exit"):
                        self.assertEqual((out / phase / receipt).read_text(), "0\n")
                    if phase == failed_phase:
                        with self.assertRaises(ValueError):
                            evidence.validate_report(out / phase / "junit.xml", phase)
                    else:
                        evidence.validate_report(out / phase / "junit.xml", phase)

    def test_runner_errexit_preserves_formatter_failure_receipt(self):
        scripts = Path(__file__).resolve().parent
        workflow = (
            scripts.parent / "workflows/hepta-private-bootstrap.yml"
        ).read_text()
        section = workflow.split(
            "      - name: Read-only Rust format check (never changes qualified source)\n"
        )[1]
        shell = textwrap.dedent(
            section.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "evidence"
            out.mkdir()
            binary = root / "bin"
            binary.mkdir()
            rustup = binary / "rustup"
            rustup.write_text('#!/bin/sh\nprintf "%s\\n" "$CONTROL_FORMATTER"\n')
            formatter = binary / "rustfmt"
            formatter.write_text(
                '#!/bin/sh\nif test "$1" = --version; then echo "synthetic rustfmt"; exit 0; fi\necho "synthetic format difference"\nexit 1\n'
            )
            for executable in (rustup, formatter):
                executable.chmod(0o700)
            env = dict(
                os.environ,
                EVIDENCE=str(out),
                CONTROL_FORMATTER=str(formatter),
                PATH=f"{binary}:{os.environ['PATH']}",
            )
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", shell],
                env=env,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual((out / "rustfmt.exit").read_text(), "1\n")
            self.assertIn(
                "synthetic format difference", (out / "rustfmt.log").read_text()
            )


class ArtifactSealTests(unittest.TestCase):
    def test_seal_excludes_itself_and_refuses_replacement_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "failure.log").write_text("retained failure\n")
            evidence.seal(root)
            seal = json.loads((root / "artifact-seal.json").read_text())
            self.assertEqual(set(seal["files"]), {"failure.log"})
            self.assertEqual(
                seal["files"]["failure.log"]["sha256"],
                evidence.digest(root / "failure.log"),
            )
            with self.assertRaises(ValueError):
                evidence.seal(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original").write_text("bytes")
            (root / "alias").symlink_to(root / "original")
            with self.assertRaises(ValueError):
                evidence.seal(root)

    def test_actual_verify_pipeline_failure_still_seals_upload_input_and_stays_failed(
        self,
    ):
        scripts = Path(__file__).resolve().parent
        workflow = (
            scripts.parent / "workflows/hepta-private-bootstrap.yml"
        ).read_text()

        def section(name):
            value = workflow.split(f"      - name: {name}\n", 1)[1]
            return value.split("      - name:", 1)[0]

        verification = section(
            "Preserve and verify all official reports even on failure"
        )
        sealing = section(
            "Seal immutable artifact after verification writer has exited"
        )
        uploading = section("Retain complete source-bound success or failure evidence")
        self.assertIn("if: always()", sealing)
        self.assertIn("if: always()", uploading)
        self.assertIn("if-no-files-found: error", uploading)
        verify_shell = textwrap.dedent(verification.split("        run: |\n", 1)[1])
        seal_shell = textwrap.dedent(sealing.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "hepta-native-bootstrap-evidence"
            out.mkdir()
            dest = root / ".github/scripts"
            dest.mkdir(parents=True)
            for name in ("native_bootstrap_evidence.py", "native_fixture_evidence.py"):
                shutil.copyfile(scripts / name, dest / name)
            binary = root / "bin"
            binary.mkdir()
            (binary / "git").write_text("#!/bin/sh\nexit 0\n")
            (binary / "python3").write_text(
                '#!/bin/sh\nif test "$2" = verify; then printf \'{"status":"failed"}\\n\' > "$3/verify-status.json"; echo "synthetic verifier final output"; exit 73; fi\nexec "$CONTROL_PYTHON" "$@"\n'
            )
            for executable in binary.iterdir():
                executable.chmod(0o700)
            env = dict(
                os.environ,
                RUNNER_TEMP=str(root),
                EVIDENCE=str(out),
                CONTROL_PYTHON=__import__("sys").executable,
                PYTHONDONTWRITEBYTECODE="1",
                PATH=f"{binary}:{os.environ['PATH']}",
            )
            failed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    verify_shell,
                ],
                cwd=root,
                env=env,
                capture_output=True,
            )
            self.assertEqual(failed.returncode, 73)
            final_log = (out / "verification.log").read_bytes()
            self.assertIn(b"synthetic verifier final output", final_log)
            sealed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    seal_shell,
                ],
                cwd=root,
                env=env,
                capture_output=True,
            )
            self.assertEqual(sealed.returncode, 0, sealed.stderr)
            # Local capture of the actual upload input, not a claimed cloud upload.
            upload_input = root / "captured-upload-input"
            shutil.copytree(out, upload_input)
            seal = json.loads((upload_input / "artifact-seal.json").read_text())
            self.assertNotIn("artifact-seal.json", seal["files"])
            self.assertEqual(
                (upload_input / "verification.log").read_bytes(), final_log
            )
            for name, identity in seal["files"].items():
                self.assertEqual(
                    evidence.digest(upload_input / name), identity["sha256"]
                )
            self.assertEqual(
                json.loads((upload_input / "verify-status.json").read_text())["status"],
                "failed",
            )
            self.assertNotEqual(failed.returncode or sealed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
