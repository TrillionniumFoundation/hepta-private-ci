"""Strict offline replay of one immutable, post-hoc research artifact."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unpack(archive, target, binding):
    # Check the opaque, bounded original ZIP before invoking any ZIP parser.
    require(archive.stat().st_size == binding["zip_bytes"], "ZIP byte count")
    with archive.open("rb") as stream:
        raw = stream.read(binding["zip_bytes"] + 1)
    require(len(raw) == binding["zip_bytes"], "ZIP changed size")
    require(digest(raw) == binding["zip_sha256"], "ZIP digest")
    require(not target.exists(), "destination must not exist")
    expected = binding["zip_members"]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries = z.infolist()
        require(len(entries) <= 150, "member count")
        require(len({i.filename for i in entries}) == len(entries), "duplicate member")
        require({i.filename for i in entries} == set(expected), "exact member set")
        require(sum(i.file_size for i in entries) <= 25_000_000, "total size")
        content = {}
        for i in entries:
            p = PurePosixPath(i.filename)
            require(
                not p.is_absolute()
                and ".." not in p.parts
                and "\\" not in i.filename
                and ":" not in i.filename
                and str(p) == i.filename,
                "unsafe path",
            )
            mode = i.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG), "nonregular member")
            require(not i.flag_bits & 1 and i.compress_type in (0, 8), "ZIP method")
            require(0 <= i.file_size <= 8_000_000, "member size")
            require(i.file_size == expected[i.filename]["bytes"], "member byte count")
            b = z.read(
                i
            )  # zipfile validates CRC; all size bounds precede decompression.
            require(digest(b) == expected[i.filename]["sha256"], "member digest")
            content[i.filename] = b
        # No JSON/NumPy parser sees an input until all eight inputs match.
        for name, h in binding["inputs_sha256"].items():
            require(digest(content[name]) == h, "consumed input digest")
        for name, b in content.items():
            p = target / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)


def check_sources(repo, binding):
    for name, h in binding["source_sha256"].items():
        require(
            digest((repo / name).read_bytes()) == h, "original source digest: " + name
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-python", type=Path, required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, "original controls require assertions enabled")
    import numpy as np

    require(
        platform.python_version() == "3.12.14" and np.__version__ == "1.26.4",
        "locked runtime",
    )
    binding = json.loads((HERE / "bindings.json").read_bytes())
    for name, h in binding["original_controls_sha256"].items():
        require(digest((HERE / name).read_bytes()) == h, "original control bytes")
    check_sources(args.repo, binding)
    args.output.mkdir(parents=True, exist_ok=False)
    artifact = args.output / "caption-run-audit-539d-20261024T2256Z/artifact"
    unpack(args.zip, artifact, binding)
    for path in artifact.rglob("*.npz"):
        with zipfile.ZipFile(path) as z:
            entries = z.infolist()
            require(
                len(entries) <= 16 and sum(i.file_size for i in entries) <= 8_000_000,
                "NPZ size bound",
            )
            require(len({i.filename for i in entries}) == len(entries), "NPZ duplicate")
            require(
                all(
                    i.filename.endswith(".npy")
                    and "/" not in i.filename
                    and not i.flag_bits & 1
                    for i in entries
                ),
                "NPZ member",
            )
            require(z.testzip() is None, "NPZ CRC")
    subprocess.run(
        [
            str(args.ledger_python.absolute()),
            "-B",
            str(HERE / "audit_ledgers.py"),
            "--repo",
            str(args.repo.resolve()),
            "--artifact",
            str(artifact.resolve()),
            "--receipt",
            str((args.output / "ledger-audit.json").resolve()),
        ],
        check=True,
        timeout=90,
    )
    ledger_count = 20
    env = dict(
        os.environ,
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    work = args.output / "caption-strong-controls-539d-20261025T0007Z"
    work.mkdir()
    for name in binding["original_controls_sha256"]:
        shutil.copyfile(HERE / name, work / name)
    outputs = {}
    for repeat in range(2):
        with (args.output / f"replay-{repeat}.log").open("wb") as log:
            subprocess.run(
                [sys.executable, "-B", str((work / "evaluate.py").resolve())],
                check=True,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=90,
            )
        hashes = {
            n: digest((work / n).read_bytes()) for n in binding["expected_outputs"]
        }
        require(
            hashes == binding["expected_outputs"],
            "original output digest mismatch (no tolerance/acceptance substitution)",
        )
        require(not outputs or hashes == outputs, "repeat mismatch")
        outputs = hashes
    with (args.output / "controls-tests.log").open("wb") as log:
        subprocess.run(
            [sys.executable, "-B", "test_controls.py", "-v"],
            cwd=work,
            check=True,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    # Detect any accidental input modification after replay.
    for name, pin in binding["zip_members"].items():
        require(
            digest((artifact / name).read_bytes()) == pin["sha256"], "input changed"
        )
    receipt = {
        "status": "REPLAY_MATCH_ONLY_NOT_ACCEPTANCE",
        "authority": "DENY_ALL",
        "production_activation_allowed": False,
        "original_source": binding["original_source"],
        "zip_sha256": binding["zip_sha256"],
        "inputs_sha256": binding["inputs_sha256"],
        "outputs_sha256": outputs,
        "verified_ledgers": ledger_count,
        "repeats": 2,
        "original_tests": 8,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "bindings_sha256": digest((HERE / "bindings.json").read_bytes()),
    }
    (args.output / "replay-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
