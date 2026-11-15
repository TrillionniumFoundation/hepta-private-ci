"""Observe a fresh native child through the real token factories and broker."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--file-boundary", action="store_true")
    args = parser.parse_args()
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--no-deps", "--format-version=1"],
            text=True,
        )
    )
    target = Path(metadata["target_directory"]) / "debug"
    sources = {
        "windows_crypto_diagnostic.exe": target
        / "examples/windows_crypto_diagnostic.exe",
        "codex-windows-sandbox-setup.exe": target / "codex-windows-sandbox-setup.exe",
        "codex-command-runner.exe": target / "codex-command-runner.exe",
    }
    # Use the same sibling layout as the installed product. An example's build
    # directory alone is not a supported helper-discovery location.
    with tempfile.TemporaryDirectory(
        prefix="native-crypto-driver-", dir=args.output.parent
    ) as bundle:
        bundle = Path(bundle)
        hashes = {}
        for name, source in sources.items():
            destination = bundle / name
            shutil.copyfile(source, destination)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError(f"diagnostic bundle changed {name}")
            hashes[name] = digest
        records = []
        modes = (
            ["files"]
            if args.file_boundary
            else ["base", "full", "capability", "broker"]
        )
        for mode in modes:
            command = [
                str(bundle / "windows_crypto_diagnostic.exe"),
                mode,
                str(args.probe.resolve()),
            ]
            try:
                result = subprocess.run(command, capture_output=True, timeout=120)
                stdout, stderr = result.stdout, result.stderr
                record = {
                    "mode": mode,
                    "driver_exit": result.returncode,
                    "timed_out": False,
                }
            except subprocess.TimeoutExpired as error:
                stdout, stderr = error.stdout or b"", error.stderr or b""
                record = {"mode": mode, "driver_exit": None, "timed_out": True}
            record["output_truncated"] = len(stdout) > 65536 or len(stderr) > 65536
            record["stdout"] = stdout[:65536].decode("utf-8", errors="replace")
            record["stderr"] = stderr[:65536].decode("utf-8", errors="replace")
            if not record["output_truncated"] and (
                record["driver_exit"] == 0 or args.file_boundary
            ):
                try:
                    record["observation"] = json.loads(record["stdout"])
                except json.JSONDecodeError as error:
                    record["observation_parse_error"] = str(error)
            records.append(record)
            # Persist completed modes even if a subsequent baseline check fails.
            args.output.write_text(
                json.dumps(
                    {
                        "observation_only": True,
                        "binary_sha256": hashes,
                        "probe_sha256": hashlib.sha256(
                            args.probe.read_bytes()
                        ).hexdigest(),
                        "modes": records,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(json.dumps(record), flush=True)
        if args.file_boundary:
            observation = records[0].get("observation", {})
            if (
                records[0]["driver_exit"] != 0
                or not observation.get("complete")
                or not observation.get("policy_passed")
            ):
                raise ValueError(
                    "actual CRT-free file operations did not satisfy the original owner boundary"
                )
            return
        baseline = records[0].get("observation", {}).get("result", {})
        required = [
            "probe_entry=1",
            "bcrypt_preloaded=0x00000000",
            "bcrypt_preloaded_after_observation=0x00000000",
            "primitives_preloaded_after_observation=0x00000000",
            "system_rng_ntstatus=0x00000000",
            "probe_complete=1",
        ]
        if baseline.get("exit_code") != 0 or not all(
            part in baseline.get("stdout", "") for part in required
        ):
            raise ValueError(
                "unrestricted kernel32-only baseline did not establish a usable crypto probe"
            )
        if (
            baseline.get("stdout", "")
            .splitlines()
            .count("self_handles_complete=0x00000001")
            != 2
        ):
            raise ValueError(
                "unrestricted before/after handle enumeration did not complete"
            )
        # Restricted and broker results are observations. The unchanged complete
        # owner suite remains responsible for permission and runtime assertions.


if __name__ == "__main__":
    main()
