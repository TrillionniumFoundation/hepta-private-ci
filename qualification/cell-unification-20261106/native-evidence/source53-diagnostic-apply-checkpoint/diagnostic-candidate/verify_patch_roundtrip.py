from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    manifest_raw = (ROOT / "source-manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    patch = ROOT / "diagnostic.patch"
    assert pin(patch.read_bytes()) == {k: manifest["patch"][k] for k in ("bytes", "sha256", "git_blob")}
    runs = []
    with tempfile.TemporaryDirectory(prefix="bedrock-diagnostic-roundtrip-") as directory:
        target = Path(directory)
        for row in manifest["files"]:
            before = ROOT / "original" / row["path"]
            after = ROOT / "source" / row["path"]
            assert pin(before.read_bytes()) == row["before"]
            assert pin(after.read_bytes()) == row["after"]
            path = target / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before, path)
        for arguments in (["--check"], [], ["--reverse", "--check"], ["--reverse"]):
            command = ["git", "apply", *arguments, str(patch)]
            result = subprocess.run(command, cwd=target, capture_output=True, check=False)
            runs.append({"command": command, "cwd": "temporary isolated directory", "exit_code": result.returncode, "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
            assert result.returncode == 0, runs[-1]
            if arguments == []:
                for row in manifest["files"]:
                    assert (target / row["path"]).read_bytes() == (ROOT / "source" / row["path"]).read_bytes()
            if arguments == ["--reverse"]:
                for row in manifest["files"]:
                    assert (target / row["path"]).read_bytes() == (ROOT / "original" / row["path"]).read_bytes()
    expected = {"config_precedence_start", "config_precedence_complete", "profile_validation_start", "profile_validation_complete", "login_cancel_start", "login_cancel_complete", "provider_config_start", "provider_config_complete", "handler_entered"}
    assert set(manifest["stage_labels"]) == expected
    for row in manifest["files"]:
        assert row["mode"] == "100644"
    report = {
        "schema": "hepta.bedrock-r29-diagnostic-patch-roundtrip.v1",
        "classification": "STATIC_ONLY_DIAGNOSTIC_CANDIDATE_NOT_QUALIFICATION",
        "manifest": pin(manifest_raw),
        "patch": pin(patch.read_bytes()),
        "git_apply_checks": runs,
        "all_four_git_commands_exit_zero": True,
        "forward_and_reverse_entire_file_bytes_match": True,
        "non_candidate_source_changes": False,
        "rust_tests_formatter_or_diagnostic_executed": False,
    }
    path = ROOT / "PATCH-ROUNDTRIP-READBACK.json"
    data = (json.dumps(report, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"path": path.name, **pin(data)}, indent=2))


if __name__ == "__main__":
    main()
