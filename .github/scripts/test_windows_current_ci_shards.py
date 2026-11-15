"""Synthetic receipt rejection controls; these are not native Windows evidence."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath

from aggregate_windows_current_ci import artifact_name, validate_shards
from windows_current_ci import (
    SANDBOX_HELPERS,
    SHARD_PACKAGES,
    assess,
    export_sandbox_helper_evidence,
    original_command,
    scope_digest,
    selected_groups,
)


class OriginalWindowsShardControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.evidence = Path(self.temp.name)
        self.manifest = json.loads(
            (Path(__file__).resolve().parents[1] / "fixtures/windows-current-ci-scope.json").read_text()
        )
        self.head, self.tree, self.run_id, self.attempt = "a" * 40, "b" * 40, "123", "1"
        self.lock = b"version = 4\n"
        self.native_paths = {"checkout": r"D:\a\source", "target": r"D:\a\_temp\native-target"}
        self.receipts = {}
        self.source = {
            "head": self.head, "tree": self.tree, "trackedChanges": "",
            "cargoLockSha256": hashlib.sha256(self.lock).hexdigest(),
        }
        for shard in SHARD_PACKAGES:
            directory = self.directory(shard)
            directory.mkdir()
            rows = []
            for group in selected_groups(self.manifest, shard):
                index = self.manifest["groups"].index(group) + 1
                log = f"Nextest run ID {index:08x}-0000-4000-8000-000000000001 with nextest profile: local\n"
                log += f"Starting {group['expectedTestCount']} tests across 1 binary\n"
                log += "".join(f"PASS [ 0.01s] {group['package']} {name}\n" for name in group["requiredTests"])
                log += f"Summary [ 0.01s] {group['expectedTestCount']} tests run: {group['expectedTestCount']} passed, 0 skipped\n"
                data = log.encode()
                (directory / (group["id"] + ".log")).write_bytes(data)
                rows.append({**assess(group, 0, log), "command": original_command(group), "logSha256": hashlib.sha256(data).hexdigest(), "durationSeconds": 0.01})
            helpers = None
            if shard == "process":
                artifacts, records = [], []
                binaries = directory / "sandbox-helper-binaries"
                binaries.mkdir()
                root = PureWindowsPath(self.native_paths["checkout"])
                profile = PureWindowsPath(self.native_paths["target"]) / "dev-small"
                for name, source in zip(SANDBOX_HELPERS, ("setup_main", "command_runner")):
                    data = b"MZ-synthetic-receipt-unit-fixture-only-" + name.encode()
                    binary = profile / (name + ".exe")
                    (binaries / binary.name).write_bytes(data)
                    artifacts.append({"name": name, "source": str(binary), "testSibling": str(profile / "deps" / binary.name), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "evidenceFile": "sandbox-helper-binaries/" + binary.name})
                    records.append({"reason": "compiler-artifact", "manifest_path": str(root / "codex-rs/windows-sandbox-rs/Cargo.toml"), "target": {"name": name, "kind": ["bin"], "crate_types": ["bin"], "src_path": str(root / f"codex-rs/windows-sandbox-rs/src/bin/{source}/main.rs")}, "executable": str(binary), "filenames": [str(binary)], "profile": {"test": False}})
                records.append({"reason": "build-finished", "success": True})
                build = ("\n".join(json.dumps(record) for record in records) + "\n").encode()
                (directory / "sandbox-helper-build.log").write_bytes(build)
                command = ["cargo", "build", "--locked", "-p", "codex-windows-sandbox", "--profile", "dev-small", "--message-format=json"]
                for name in SANDBOX_HELPERS:
                    command.extend(["--bin", name])
                helpers = {"command": command, "exitCode": 0, "passed": True, "logSha256": hashlib.sha256(build).hexdigest(), "artifacts": artifacts}
                self.write_json(directory / "sandbox-helper-preparation.json", helpers)
            compiler = b"rustc 1.96.0 (unit-fixture)\nhost: x86_64-pc-windows-msvc\n"
            (directory / "compiler.txt").write_bytes(compiler)
            receipt = {
                "schema": "hepta.windows-current-ci-shard-receipt.v1", "shard": shard,
                "status": "PASS_DECLARED_WINDOWS_SHARD", "declaredScopeDigest": scope_digest(self.manifest),
                "sourceBefore": self.source.copy(), "sourceAfter": self.source.copy(), "sourceUnchanged": True,
                "workflow": {"runId": self.run_id, "runAttempt": self.attempt, "runnerOs": "Windows", "runnerName": "synthetic-" + shard},
                "nativePaths": self.native_paths.copy(),
                "platform": "Windows-unit-fixture", "compilerSha256": hashlib.sha256(compiler).hexdigest(),
                "groups": rows, "sandboxHelperPreparation": helpers, "testRetries": 0,
                "productionAuthorityGranted": False, "finalProductQualification": False,
            }
            self.receipts[shard] = receipt
            self.save(shard, receipt)

    def directory(self, shard):
        return self.evidence / artifact_name(self.head, self.run_id, self.attempt, shard)

    def write_json(self, path, value):
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def save(self, shard, receipt):
        directory = self.directory(shard)
        self.write_json(directory / "receipt.json", receipt)
        self.write_json(directory / "groups.json", receipt["groups"])
        self.write_json(directory / "source-before.json", receipt["sourceBefore"])
        self.write_json(directory / "source-after.json", receipt["sourceAfter"])

    def validate(self, matrix_result="success"):
        return validate_shards(self.manifest, self.head, self.tree, self.lock, self.run_id, self.attempt, matrix_result, self.evidence)

    def test_exact_disjoint_partition_and_complete_synthetic_receipts(self):
        owners = selected_groups(self.manifest, "owners")
        process = selected_groups(self.manifest, "process")
        self.assertEqual((len(owners), sum(g["expectedTestCount"] for g in owners)), (8, 98))
        self.assertEqual((len(process), sum(g["expectedTestCount"] for g in process)), (11, 69))
        self.assertFalse({g["package"] for g in owners} & {g["package"] for g in process})
        result = self.validate()
        self.assertEqual((result["groupCount"], result["testCount"]), (19, 167))
        self.assertTrue(all(row["source"] == self.source for row in result["groups"]))

    def test_unknown_shard_or_changed_scope_cannot_silently_drop_cases(self):
        with self.assertRaises(ValueError):
            selected_groups(self.manifest, "typo")
        for change in ("drop", "duplicate", "unknown-package"):
            manifest = copy.deepcopy(self.manifest)
            if change == "drop":
                manifest["groups"].pop()
            elif change == "duplicate":
                manifest["groups"][-1] = copy.deepcopy(manifest["groups"][0])
            else:
                manifest["groups"][0]["package"] = "unassigned"
            with self.subTest(change=change), self.assertRaises(ValueError):
                selected_groups(manifest)

    def test_missing_partial_duplicate_and_extra_artifacts_fail_closed(self):
        path = self.directory("process") / "receipt.json"
        data = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.validate()
        path.write_bytes(data)
        for rows in (self.receipts["owners"]["groups"][:-1], self.receipts["owners"]["groups"] + [self.receipts["owners"]["groups"][0]]):
            receipt = copy.deepcopy(self.receipts["owners"])
            receipt["groups"] = rows
            self.save("owners", receipt)
            with self.assertRaises(ValueError):
                self.validate()
        self.save("owners", self.receipts["owners"])
        (self.evidence / "historical-or-duplicate").mkdir()
        with self.assertRaises(ValueError):
            self.validate()

    def test_raw_failure_cannot_be_relabelled_as_pass_even_with_updated_hash(self):
        original = self.receipts["owners"]
        path = self.directory("owners") / (original["groups"][0]["id"] + ".log")
        data = path.read_bytes()
        for status in (b"FAIL", b"TIMEOUT", b"EXECFAIL", b"LEAK", b"SKIP"):
            changed = data.replace(b"PASS [", status + b" [", 1)
            receipt = copy.deepcopy(original)
            receipt["groups"][0]["logSha256"] = hashlib.sha256(changed).hexdigest()
            path.write_bytes(changed)
            self.save("owners", receipt)
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.validate()

    def test_nonzero_missing_or_boolean_native_exit_is_not_a_terminal_pass(self):
        for code in (100, None, False):
            receipt = copy.deepcopy(self.receipts["owners"])
            receipt["groups"][0]["exitCode"] = code
            self.save("owners", receipt)
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.validate()

    def test_raw_log_or_exact_command_change_is_rejected(self):
        original = self.receipts["owners"]
        path = self.directory("owners") / (original["groups"][0]["id"] + ".log")
        data = path.read_bytes()
        path.write_bytes(data + b"unbound bytes\n")
        with self.assertRaises(ValueError):
            self.validate()
        path.write_bytes(data)
        for flag, value in (("--retries", "1"), ("--cargo-profile", "test"), ("-E", "all()")):
            receipt = copy.deepcopy(original)
            command = receipt["groups"][0]["command"]
            command[command.index(flag) + 1] = value
            self.save("owners", receipt)
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.validate()

    def test_wrong_dirty_or_changed_source_is_rejected(self):
        for key, value in (("head", "d" * 40), ("tree", "d" * 40), ("cargoLockSha256", "d" * 64), ("trackedChanges", " M source.rs"), ("trackedChanges", False)):
            receipt = copy.deepcopy(self.receipts["owners"])
            receipt["sourceBefore"][key] = value
            receipt["sourceAfter"][key] = value
            self.save("owners", receipt)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate()
        receipt = copy.deepcopy(self.receipts["owners"])
        receipt["sourceAfter"]["tree"] = "d" * 40
        self.save("owners", receipt)
        with self.assertRaises(ValueError):
            self.validate()

    def test_historical_run_wrong_shard_or_raised_authority_is_rejected(self):
        mutations = [
            lambda r: r["workflow"].update(runId="122"),
            lambda r: r["workflow"].update(runAttempt="2"),
            lambda r: r["workflow"].update(runnerName="synthetic-process"),
            lambda r: r["workflow"].update(runnerOs="Linux"),
            lambda r: r.update(shard="process"),
            lambda r: r.update(declaredScopeDigest="0" * 64),
            lambda r: r.update(status="FAIL_DECLARED_WINDOWS_SHARD"),
            lambda r: r.update(productionAuthorityGranted=True),
            lambda r: r.update(finalProductQualification=True),
        ]
        for index, change in enumerate(mutations):
            receipt = copy.deepcopy(self.receipts["owners"])
            change(receipt)
            self.save("owners", receipt)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate()

    def test_native_compiler_host_and_helper_build_are_required(self):
        directory = self.directory("owners")
        compiler = (directory / "compiler.txt").read_bytes()
        changed = compiler.replace(b"x86_64-pc-windows-msvc", b"x86_64-unknown-linux-gnu")
        receipt = copy.deepcopy(self.receipts["owners"])
        receipt["compilerSha256"] = hashlib.sha256(changed).hexdigest()
        (directory / "compiler.txt").write_bytes(changed)
        self.save("owners", receipt)
        with self.assertRaises(ValueError):
            self.validate()
        (directory / "compiler.txt").write_bytes(compiler)
        self.save("owners", self.receipts["owners"])
        for change in ("failed", "missing-artifact", "command"):
            receipt = copy.deepcopy(self.receipts["process"])
            helpers = receipt["sandboxHelperPreparation"]
            if change == "failed":
                helpers.update(passed=False, exitCode=101)
            elif change == "missing-artifact":
                helpers["artifacts"].pop()
            else:
                helpers["command"].append("--release")
            self.save("process", receipt)
            self.write_json(self.directory("process") / "sandbox-helper-preparation.json", helpers)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate()

    def test_native_matrix_failure_cannot_be_overridden_by_receipts(self):
        for status in ("failure", "cancelled", "skipped"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.validate(matrix_result=status)

    def test_json_boolean_cannot_substitute_for_original_integer_policy(self):
        self.manifest["policy"]["testRetries"] = False
        for shard, original in self.receipts.items():
            receipt = copy.deepcopy(original)
            receipt["declaredScopeDigest"] = scope_digest(self.manifest)
            self.save(shard, receipt)
        with self.assertRaises(ValueError):
            self.validate()

    def test_duplicate_json_keys_are_rejected(self):
        path = self.directory("owners") / "receipt.json"
        text = path.read_text().rstrip()
        path.write_text(text[:-1] + ', "status": "PASS_DECLARED_WINDOWS_SHARD"}\n')
        with self.assertRaises(ValueError):
            self.validate()

    def test_two_complete_runs_cannot_be_deduplicated_into_one_pass(self):
        receipt = copy.deepcopy(self.receipts["owners"])
        row = receipt["groups"][0]
        path = self.directory("owners") / (row["id"] + ".log")
        changed = path.read_bytes() * 2
        path.write_bytes(changed)
        row["logSha256"] = hashlib.sha256(changed).hexdigest()
        self.save("owners", receipt)
        with self.assertRaisesRegex(ValueError, "exactly one Nextest"):
            self.validate()

    def test_all_selected_success_may_omit_zero_skipped_suffix(self):
        receipt = copy.deepcopy(self.receipts["owners"])
        row = receipt["groups"][0]
        path = self.directory("owners") / (row["id"] + ".log")
        data = path.read_bytes().replace(b", 0 skipped\n", b"\n")
        path.write_bytes(data)
        row["logSha256"] = hashlib.sha256(data).hexdigest()
        self.save("owners", receipt)
        self.assertEqual(self.validate()["testCount"], 167)

    def test_fake_historical_helper_metadata_cannot_replace_actual_bytes(self):
        receipt = copy.deepcopy(self.receipts["process"])
        helpers = receipt["sandboxHelperPreparation"]
        for item in helpers["artifacts"]:
            item.update(bytes=1, sha256="e" * 64, source=r"Z:\historical\helper.exe", testSibling=r"Z:\historical\deps\helper.exe")
        self.save("process", receipt)
        self.write_json(self.directory("process") / "sandbox-helper-preparation.json", helpers)
        with self.assertRaisesRegex(ValueError, "original compiler artifact"):
            self.validate()

    def test_exported_helper_bytes_are_independently_verified(self):
        original = self.receipts["process"]
        item = original["sandboxHelperPreparation"]["artifacts"][0]
        path = self.directory("process") / item["evidenceFile"]
        data = path.read_bytes()
        for changed in (None, data + b"changed", b"NO" + data[2:]):
            receipt = copy.deepcopy(original)
            if changed is None:
                path.unlink()
            else:
                path.write_bytes(changed)
                if changed.startswith(b"NO"):
                    claim = receipt["sandboxHelperPreparation"]["artifacts"][0]
                    claim.update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
            self.save("process", receipt)
            self.write_json(self.directory("process") / "sandbox-helper-preparation.json", receipt["sandboxHelperPreparation"])
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.validate()
            path.write_bytes(data)

    def test_helper_cargo_source_target_and_profile_are_checked(self):
        directory = self.directory("process")
        build_path = directory / "sandbox-helper-build.log"
        records = [json.loads(line) for line in build_path.read_text().splitlines()]
        mutations = [
            lambda r: r[0].update(manifest_path=r"Z:\historical\Cargo.toml"),
            lambda r: r[0]["target"].update(src_path=r"Z:\historical\main.rs"),
            lambda r: r[0]["target"].update(name="different-helper"),
            lambda r: r[0]["target"].update(kind=["lib"]),
            lambda r: r[0]["profile"].update(test=True),
            lambda r: r[0].update(executable=r"D:\a\_temp\native-target\release\wrong.exe"),
            lambda r: r[-1].update(success=False),
        ]
        for index, mutation in enumerate(mutations):
            changed = copy.deepcopy(records)
            mutation(changed)
            data = ("\n".join(json.dumps(record) for record in changed) + "\n").encode()
            build_path.write_bytes(data)
            receipt = copy.deepcopy(self.receipts["process"])
            helpers = receipt["sandboxHelperPreparation"]
            helpers["logSha256"] = hashlib.sha256(data).hexdigest()
            self.save("process", receipt)
            self.write_json(directory / "sandbox-helper-preparation.json", helpers)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate()

    def test_missing_or_mismatched_single_run_terminal_is_rejected(self):
        original = self.receipts["owners"]
        path = self.directory("owners") / (original["groups"][0]["id"] + ".log")
        data = path.read_bytes()
        mutations = [
            lambda d: b"\n".join(d.splitlines()[1:]) + b"\n",
            lambda d: b"\n".join(d.splitlines()[:-1]) + b"\n",
            lambda d: d.replace(b"profile: local", b"profile: default"),
            lambda d: d.replace(b"passed, 0 skipped", b"passed, 1 skipped"),
            lambda d: d + d.splitlines()[-1] + b"\n",
        ]
        for index, mutation in enumerate(mutations):
            changed = mutation(data)
            path.write_bytes(changed)
            receipt = copy.deepcopy(original)
            receipt["groups"][0]["logSha256"] = hashlib.sha256(changed).hexdigest()
            self.save("owners", receipt)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate()

    def test_helper_export_preserves_bytes_and_rejects_stale_sibling(self):
        root = self.evidence / "export-unit-fixture"
        root.mkdir()
        source, sibling = root / "source.exe", root / "sibling.exe"
        data = b"MZ-synthetic-export-control"
        source.write_bytes(data)
        sibling.write_bytes(data)
        item = {"name": SANDBOX_HELPERS[0], "source": str(source), "testSibling": str(sibling), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        output = root / "valid"
        output.mkdir()
        export_sandbox_helper_evidence(output, [item])
        self.assertEqual((output / item["evidenceFile"]).read_bytes(), data)
        sibling.write_bytes(data + b"stale")
        output = root / "stale"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "before evidence export"):
            export_sandbox_helper_evidence(output, [item])


if __name__ == "__main__":
    unittest.main()
