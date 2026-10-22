from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCRIPT = Path(__file__).with_name("hepta-cell-split-target-matrix.py")
SPEC = importlib.util.spec_from_file_location("cell_split_matrix", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def current_checkout_sha() -> str:
    return subprocess.run(
        ["git", "-C", str(SCRIPT.resolve().parent.parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def example_metrics() -> dict[str, object]:
    return {
        "p50Micros": 10,
        "p95Micros": 20,
        "p99Micros": 30,
        "throughputPerSecond": 100.0,
        "cpuMicros": 100,
        "rssBytes": 200,
        "gpuObserved": False,
        "gpuMicros": None,
        "gpuBytes": None,
        "communicationBytes": 300,
        "fsyncCount": 1,
        "walBytes": 400,
        "walFsyncCount": 1,
        "lockWaitMicros": 2,
        "recoveryMicros": 3,
        "negativeMigrationQ32": 0,
    }


def test_default_matrix_is_64_unique_cases_across_four_cell_counts() -> None:
    cases = MODULE.matrix_cases()
    assert len(cases) == 64
    assert [count for count in MODULE.CELL_COUNTS] == [64, 256, 1024, 4096]
    assert len({case["caseId"] for case in cases}) == 64
    assert (
        len(
            {
                (case["cellCount"], *(case[name] for name, _ in MODULE.FACTORS))
                for case in cases
            }
        )
        == 64
    )
    for count in MODULE.CELL_COUNTS:
        one = MODULE.matrix_cases(count)
        assert len(one) == 16
        assert all(case["cellCount"] == count for case in one)
    with pytest.raises(ValueError, match="unsupported Cell count"):
        MODULE.matrix_cases(8)


def test_measurement_requires_all_metrics_and_monotonic_quantiles() -> None:
    metrics = example_metrics()
    assert MODULE.validate_metrics(metrics) == metrics
    with pytest.raises(ValueError, match="quantiles"):
        MODULE.validate_metrics({**metrics, "p95Micros": 40})
    for missing in (
        "walBytes",
        "walFsyncCount",
        "gpuObserved",
        "gpuMicros",
        "gpuBytes",
    ):
        incomplete = dict(metrics)
        del incomplete[missing]
        with pytest.raises(ValueError, match="missing metrics"):
            MODULE.validate_metrics(incomplete)


def test_missing_gpu_is_explicit_null_not_fake_zero() -> None:
    metrics = example_metrics()
    assert MODULE.validate_metrics(metrics)["gpuObserved"] is False
    with pytest.raises(ValueError, match="unobserved GPU"):
        MODULE.validate_metrics({**metrics, "gpuMicros": 0})
    with pytest.raises(ValueError, match="unobserved GPU"):
        MODULE.validate_metrics({**metrics, "gpuBytes": 0})
    with pytest.raises(ValueError, match="gpuObserved"):
        MODULE.validate_metrics({**metrics, "gpuObserved": 0})
    with pytest.raises(ValueError, match="gpuMicros"):
        MODULE.validate_metrics({**metrics, "gpuObserved": True})
    measured = {**metrics, "gpuObserved": True, "gpuMicros": 12, "gpuBytes": 256}
    assert MODULE.validate_metrics(measured) == measured


def test_measurement_rejects_nonfinite_or_unbounded_counters() -> None:
    base = example_metrics()
    for name, bad_value in (
        ("throughputPerSecond", float("nan")),
        ("p95Micros", float("inf")),
        ("negativeMigrationQ32", float("-inf")),
        ("rssBytes", 1 << 128),
        ("walBytes", -1),
        ("walFsyncCount", 1.5),
    ):
        with pytest.raises(ValueError):
            MODULE.validate_metrics({**base, name: bad_value})


def test_pretty_json_workload_receipt_is_parsed() -> None:
    receipt = {"caseId": "case-1", "metrics": example_metrics()}
    assert MODULE.parse_workload_output(json.dumps(receipt, indent=2)) == receipt


def test_isolated_process_rejects_timeouts_and_leftover_descendants(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    healthy = MODULE.run_isolated_command(
        [sys.executable, "-c", "print('healthy')"],
        env=env,
        timeout_seconds=5,
    )
    assert healthy.returncode == 0
    assert healthy.stdout.strip() == "healthy"

    with pytest.raises(ValueError, match="deadline; process group terminated"):
        MODULE.run_isolated_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=env,
            timeout_seconds=0.2,
        )

    leaky = tmp_path / "leaky-worker.py"
    leaky.write_text(
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],"
        " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,"
        " stderr=subprocess.DEVNULL)\n"
        "print('launcher finished')\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="descendant processes"):
        MODULE.run_isolated_command(
            [sys.executable, str(leaky)],
            env=env,
            timeout_seconds=5,
        )


@pytest.mark.parametrize("target_fd", (1, 2))
def test_isolated_process_output_is_bounded_and_flood_group_is_killed(
    target_fd: int,
) -> None:
    # Produce more bytes than the one-MiB bounded capture without closing the
    # stream. This must fail before the five-second deadline expires.
    source = (
        "import os\n"
        "chunk = b'x' * 65536\n"
        "while True:\n"
        f"    os.write({target_fd}, chunk)\n"
    )
    with pytest.raises(ValueError, match="output exceeds bounded capture"):
        MODULE.run_isolated_command(
            [sys.executable, "-c", source],
            env=os.environ.copy(),
            timeout_seconds=5,
        )


def test_isolated_process_preserves_both_small_output_streams() -> None:
    output = MODULE.run_isolated_command(
        [
            sys.executable,
            "-c",
            "import sys; print('receipt'); print('diagnostic', file=sys.stderr)",
        ],
        env=os.environ.copy(),
        timeout_seconds=5,
    )
    assert output.returncode == 0
    assert output.stdout.strip() == "receipt"
    assert output.stderr.strip() == "diagnostic"



@pytest.mark.parametrize("alias", ("identical", "symlink", "hardlink"))
def test_matrix_report_output_never_overwrites_frozen_workload(
    tmp_path: Path, alias: str
) -> None:
    frozen = tmp_path / "frozen-tasks"
    original = b"original frozen task corpus must remain unchanged"
    frozen.write_bytes(original)
    output = tmp_path / "matrix.json"
    if alias == "identical":
        output = frozen
    elif alias == "symlink":
        output.symlink_to(frozen)
    else:
        os.link(frozen, output)
    with pytest.raises(ValueError, match="matrix report output"):
        MODULE.run_matrix(
            workload_command=None,
            observer_command=None,
            workload_digest=hashlib.sha256(original).hexdigest(),
            source_commit="f" * 40,
            workload_path=frozen,
            output=output,
        )
    assert frozen.read_bytes() == original


def test_matrix_report_symlink_cannot_overwrite_unrelated_artifact(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "protected-evidence"
    protected.write_bytes(b"unrelated retained evidence")
    output = tmp_path / "matrix.json"
    output.symlink_to(protected)
    with pytest.raises(ValueError, match="must not be a symlink"):
        MODULE.run_matrix(
            workload_command=None,
            observer_command=None,
            workload_digest="a" * 64,
            source_commit="f" * 40,
            output=output,
        )
    assert protected.read_bytes() == b"unrelated retained evidence"


def test_matrix_report_atomic_replacement_leaves_no_staging_files(
    tmp_path: Path,
) -> None:
    output = tmp_path / "matrix.json"
    output.write_text("previous report", encoding="utf-8")
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=output,
    )
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert not list(tmp_path.glob(".matrix.json.*.tmp"))
    MODULE.validate_report(report)


def test_dry_run_is_blocked_until_workload_and_observer_exist(tmp_path: Path) -> None:
    output = tmp_path / "matrix.json"
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=output,
        host_id="test-host",
    )
    assert report["status"] == "blocked"
    assert report["authority"] == "DENY_ALL"
    assert len(report["cases"]) == 64
    assert report["cellCounts"] == list(MODULE.CELL_COUNTS)
    assert "independent-observer" in report["blockingCases"]
    MODULE.validate_report(json.loads(output.read_text(encoding="utf-8")))


def test_single_count_workload_passes_count_and_remains_diagnostic(
    tmp_path: Path,
) -> None:
    workload = tmp_path / "frozen-tasks"
    workload.write_bytes(b"fixture only: not a production task corpus")
    frozen_digest = hashlib.sha256(workload.read_bytes()).hexdigest()
    worker = tmp_path / "fixture-worker.py"
    worker.write_text(
        "import json, os, sys\n"
        f"METRICS = {example_metrics()!r}\n"
        "assert sys.argv[1] == os.environ['HEPTA_MATRIX_CELL_COUNT']\n"
        "print(json.dumps({"
        "'caseId': os.environ['HEPTA_MATRIX_CASE_ID'],"
        "'cellCount': int(os.environ['HEPTA_MATRIX_CELL_COUNT']),"
        "'sourceCommit': os.environ['HEPTA_MATRIX_SOURCE_COMMIT'],"
        "'workloadDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'workloadSourceDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'encoder_topology': os.environ['HEPTA_MATRIX_ENCODER_TOPOLOGY'],"
        "'execution': os.environ['HEPTA_MATRIX_EXECUTION'],"
        "'feature_materialization': os.environ['HEPTA_MATRIX_FEATURE_MATERIALIZATION'],"
        "'persistence': os.environ['HEPTA_MATRIX_PERSISTENCE'],"
        "'metrics': METRICS"
        "}))\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=(
            f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))} {{cellCount}}"
        ),
        observer_command=None,
        workload_digest=frozen_digest,
        source_commit=current_checkout_sha(),
        output=tmp_path / "matrix.json",
        workload_path=workload,
        host_id="fixture-only",
        cell_count=64,
    )
    assert len(report["cases"]) == 16
    assert all(case["status"] == "measured" for case in report["cases"])
    assert report["status"] == "blocked"
    assert "full-scale-matrix" in report["blockingCases"]
    assert "independent-observer" in report["blockingCases"]
    MODULE.validate_report(report)


def isolated_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, str]:
    """Make a real, isolated Git fixture; never dirty the project checkout."""
    root = tmp_path / "checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    fake_script = scripts / "hepta-cell-split-target-matrix.py"
    fake_script.write_text("# fixture only\n", encoding="utf-8")
    (root / "tracked.py").write_text("VERSION = 1\n", encoding="utf-8")
    commands = (
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=P4 Fixture",
            "-c",
            "user.email=p4-fixture@example.invalid",
            "commit",
            "-qm",
            "isolated source fixture",
        ),
    )
    for command in commands:
        subprocess.run(
            ["git", "-C", str(root), *command],
            check=True,
            capture_output=True,
        )
    monkeypatch.setattr(MODULE, "__file__", str(fake_script))
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, head


@pytest.mark.parametrize("dirty_kind", ("tracked", "untracked"))
def test_measured_source_rejects_dirty_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dirty_kind: str
) -> None:
    root, head = isolated_checkout(tmp_path, monkeypatch)
    if dirty_kind == "tracked":
        (root / "tracked.py").write_text("VERSION = 2\n", encoding="utf-8")
    else:
        (root / "untracked.py").write_text("UNTRACKED = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repository checkout is dirty"):
        MODULE.run_matrix(
            workload_command="python --version",
            observer_command=None,
            workload_digest="a" * 64,
            source_commit=head,
            output=tmp_path / "dirty.json",
            cell_count=64,
        )


def test_worker_source_mutation_blocks_every_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, head = isolated_checkout(tmp_path, monkeypatch)
    workload = tmp_path / "frozen-workload"
    workload.write_bytes(b"synthetic fixture only")
    worker = tmp_path / "source-mutation.py"
    worker.write_text(
        "from pathlib import Path\n"
        f"Path({str(root / 'tracked.py')!r}).write_text('VERSION = 3\\n')\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))}",
        observer_command=None,
        workload_digest=hashlib.sha256(workload.read_bytes()).hexdigest(),
        source_commit=head,
        output=tmp_path / "source-mutation-report.json",
        workload_path=workload,
        cell_count=64,
    )
    assert report["status"] == "blocked"
    assert len(report["cases"]) == 16
    assert all(row["status"] == "blocked" for row in report["cases"])
    assert all(
        "repository checkout is dirty" in row["reason"] for row in report["cases"]
    )
    assert "source-checkout" in report["blockingCases"]
    MODULE.validate_report(report)


@pytest.mark.parametrize("mutation", ("source", "overwrite", "unlink"))
def test_post_observer_mutation_revokes_signed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root, head = isolated_checkout(tmp_path, monkeypatch)
    workload = tmp_path / "frozen-workload"
    workload.write_bytes(b"fixture only, no production measurements")
    workload_digest = hashlib.sha256(workload.read_bytes()).hexdigest()
    private = Ed25519PrivateKey.generate()
    public_key = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    observer_was_signed = False

    def fixture_runner(
        argv: list[str], *, env: dict[str, str], timeout_seconds: int | float
    ) -> subprocess.CompletedProcess[str]:
        nonlocal observer_was_signed
        if argv == ["fixture-observer"]:
            claim = {
                "schema": MODULE.OBSERVER_SCHEMA,
                "verified": True,
                "sourceCommit": env["HEPTA_MATRIX_SOURCE_COMMIT"],
                "workloadDigest": env["HEPTA_MATRIX_WORKLOAD_DIGEST"],
                "reportDigest": env["HEPTA_MATRIX_PROVISIONAL_DIGEST"],
                "metricsDigest": env["HEPTA_MATRIX_METRICS_DIGEST"],
                "observerId": "signed-fixture-not-independent",
            }
            claim["signatureHex"] = private.sign(
                MODULE.observer_signing_bytes(claim)
            ).hex()
            observer_was_signed = True
            if mutation == "source":
                (root / "tracked.py").write_text("VERSION = 9\n", encoding="utf-8")
            elif mutation == "overwrite":
                workload.write_bytes(b"observer overwrote frozen tasks")
            else:
                workload.unlink()
            return subprocess.CompletedProcess(argv, 0, json.dumps(claim), "")
        assert argv == ["fixture-worker"]
        case = {
            "caseId": env["HEPTA_MATRIX_CASE_ID"],
            "cellCount": int(env["HEPTA_MATRIX_CELL_COUNT"]),
            "sourceCommit": env["HEPTA_MATRIX_SOURCE_COMMIT"],
            "workloadDigest": env["HEPTA_MATRIX_WORKLOAD_DIGEST"],
            "workloadSourceDigest": env["HEPTA_MATRIX_WORKLOAD_DIGEST"],
            "metrics": example_metrics(),
        }
        for name, _ in MODULE.FACTORS:
            case[name] = env[f"HEPTA_MATRIX_{name.upper()}"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(case), "")

    monkeypatch.setattr(MODULE, "run_isolated_command", fixture_runner)
    report = MODULE.run_matrix(
        workload_command="fixture-worker",
        observer_command="fixture-observer",
        workload_digest=workload_digest,
        source_commit=head,
        output=tmp_path / "report.json",
        workload_path=workload,
        trusted_observer_public_key=public_key,
    )
    assert observer_was_signed
    assert len(report["cases"]) == 64
    assert all(case["status"] == "measured" for case in report["cases"])
    assert report["status"] == "blocked"
    expected_blocker = "source-checkout" if mutation == "source" else "frozen-workload"
    assert expected_blocker in report["blockingCases"]
    # Post-observer tampering revokes the signature and must also bind the
    # independent-observer blocker in the final report.
    assert "independent-observer" in report["blockingCases"]
    assert report["observer"]["verified"] is False
    assert "signatureHex" not in report["observer"]
    MODULE.validate_report(report)

    forged = {**report, "status": "qualified", "blockingCases": []}
    with pytest.raises(ValueError, match="lacks an independent observer receipt"):
        MODULE.validate_report(forged, trusted_observer_public_key=public_key)


def test_live_worker_must_match_actual_source_checkout(tmp_path: Path) -> None:
    workload = tmp_path / "frozen"
    workload.write_bytes(b"fixture only")
    with pytest.raises(ValueError, match="does not match repository HEAD"):
        MODULE.run_matrix(
            workload_command="python --version",
            observer_command=None,
            workload_digest=hashlib.sha256(workload.read_bytes()).hexdigest(),
            source_commit="e" * 40,
            output=tmp_path / "mismatch.json",
            workload_path=workload,
            cell_count=64,
        )


def test_live_worker_must_echo_actual_factor_tuple(tmp_path: Path) -> None:
    workload = tmp_path / "frozen"
    workload.write_bytes(b"fixture only")
    worker = tmp_path / "missing-factor.py"
    worker.write_text(
        "import json, os\n"
        f"metrics = {example_metrics()!r}\n"
        "print(json.dumps({"
        "'caseId': os.environ['HEPTA_MATRIX_CASE_ID'],"
        "'cellCount': int(os.environ['HEPTA_MATRIX_CELL_COUNT']),"
        "'sourceCommit': os.environ['HEPTA_MATRIX_SOURCE_COMMIT'],"
        "'workloadDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'workloadSourceDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'metrics': metrics"
        "}))\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))}",
        observer_command=None,
        workload_digest=hashlib.sha256(workload.read_bytes()).hexdigest(),
        source_commit=current_checkout_sha(),
        output=tmp_path / "missing-factor-report.json",
        workload_path=workload,
        cell_count=64,
    )
    assert report["status"] == "blocked"
    assert all(row["status"] == "blocked" for row in report["cases"])
    assert all("identity does not bind" in row["reason"] for row in report["cases"])
    MODULE.validate_report(report)


def test_live_worker_cannot_mutate_frozen_workload(tmp_path: Path) -> None:
    workload = tmp_path / "frozen"
    workload.write_bytes(b"immutable fixture")
    original_digest = hashlib.sha256(workload.read_bytes()).hexdigest()
    worker = tmp_path / "tamper.py"
    worker.write_text(
        "import json, os\n"
        "with open(os.environ['HEPTA_MATRIX_WORKLOAD_PATH'], 'ab') as out:\n"
        "    out.write(b'tamper')\n"
        f"metrics = {example_metrics()!r}\n"
        "print(json.dumps({"
        "'caseId': os.environ['HEPTA_MATRIX_CASE_ID'],"
        "'cellCount': int(os.environ['HEPTA_MATRIX_CELL_COUNT']),"
        "'sourceCommit': os.environ['HEPTA_MATRIX_SOURCE_COMMIT'],"
        "'workloadDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'workloadSourceDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'encoder_topology': os.environ['HEPTA_MATRIX_ENCODER_TOPOLOGY'],"
        "'execution': os.environ['HEPTA_MATRIX_EXECUTION'],"
        "'feature_materialization': os.environ['HEPTA_MATRIX_FEATURE_MATERIALIZATION'],"
        "'persistence': os.environ['HEPTA_MATRIX_PERSISTENCE'],"
        "'metrics': metrics"
        "}))\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))}",
        observer_command=None,
        workload_digest=original_digest,
        source_commit=current_checkout_sha(),
        output=tmp_path / "tamper-report.json",
        workload_path=workload,
        cell_count=64,
    )
    assert report["status"] == "blocked"
    assert all(row["status"] == "blocked" for row in report["cases"])
    assert "changed during" in report["cases"][0]["reason"]
    assert "changed before" in report["cases"][1]["reason"]
    MODULE.validate_report(report)


def test_report_rejects_duplicate_or_swapped_case_factors(tmp_path: Path) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    duplicated = {**report, "cases": [dict(x) for x in report["cases"]]}
    duplicated["cases"][0] = dict(duplicated["cases"][1])
    with pytest.raises(ValueError, match="unique and complete"):
        MODULE.validate_report(duplicated)
    swapped = {**report, "cases": [dict(x) for x in report["cases"]]}
    swapped["cases"][0]["encoder_topology"] = "incorrect"
    with pytest.raises(ValueError, match="factor or Cell-count"):
        MODULE.validate_report(swapped)
    bad_digest = {**report, "reportDigest": "0" * 64}
    with pytest.raises(ValueError, match="report digest mismatch"):
        MODULE.validate_report(bad_digest)


def test_full_scale_cannot_be_forged_from_one_count(tmp_path: Path) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
        cell_count=256,
    )
    forged = {**report, "status": "qualified", "blockingCases": []}
    with pytest.raises(ValueError, match="full scale"):
        MODULE.validate_report(forged)


@pytest.mark.parametrize(
    "untrusted_root",
    (None, "00" * 32, "ff" * 32, "not-a-public-key"),
)
def test_untrusted_observer_cannot_launch_without_pinned_prime_order_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, untrusted_root: str | None
) -> None:
    def forbidden_launch(*args: object, **kwargs: object) -> None:
        raise AssertionError("observer launched without a trusted public key")

    monkeypatch.setattr(MODULE, "run_isolated_command", forbidden_launch)
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command="untrusted-observer",
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "untrusted-observer.json",
        trusted_observer_public_key=untrusted_root,
    )
    assert report["status"] == "blocked"
    assert "independent-observer" in report["blockingCases"]
    assert report["observer"] == {
        "verified": False,
        "reason": "trusted independent Ed25519 observer public key is required",
    }
    MODULE.validate_report(report)


def test_signed_observer_requires_out_of_band_trust_root() -> None:
    private = Ed25519PrivateKey.generate()
    trusted_key = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    receipt = {
        "schema": MODULE.OBSERVER_SCHEMA,
        "verified": True,
        "sourceCommit": "a" * 40,
        "workloadDigest": "b" * 64,
        "reportDigest": "c" * 64,
        "metricsDigest": "d" * 64,
        "observerId": "independent-observer",
    }
    receipt["signatureHex"] = private.sign(MODULE.observer_signing_bytes(receipt)).hex()
    MODULE.verify_observer_signature(receipt, trusted_key)
    with pytest.raises(ValueError, match="trusted independent"):
        MODULE.verify_observer_signature(receipt, None)
    with pytest.raises(ValueError, match="signature invalid"):
        MODULE.verify_observer_signature(receipt, "00" * 32)
    tampered = {**receipt, "metricsDigest": "e" * 64}
    with pytest.raises(ValueError, match="signature invalid"):
        MODULE.verify_observer_signature(tampered, trusted_key)
    with pytest.raises(ValueError, match="missing or malformed"):
        MODULE.verify_observer_signature({**receipt, "signatureHex": None}, trusted_key)


def test_observer_signature_does_not_authorize_unsigned_extensions() -> None:
    private = Ed25519PrivateKey.generate()
    trusted_key = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    claim = {
        "schema": MODULE.OBSERVER_SCHEMA,
        "verified": True,
        "sourceCommit": "a" * 40,
        "workloadDigest": "b" * 64,
        "reportDigest": "c" * 64,
        "metricsDigest": "d" * 64,
        "observerId": "test-signer-not-independent",
    }
    claim["signatureHex"] = private.sign(MODULE.observer_signing_bytes(claim)).hex()
    MODULE.verify_observer_signature(claim, trusted_key)
    complete = {**claim, "receiptDigest": MODULE.digest(claim)}
    MODULE.verify_observer_signature(complete, trusted_key)

    # The original signature authenticates only the v1 fields. Recomputing
    # the unsigned receipt digest must not make a forged approval valid.
    for unauthorized in ("authority", "productionApproved", "keyRotation"):
        forged = {**claim, unauthorized: "ALLOW"}
        forged["receiptDigest"] = MODULE.digest(forged)
        with pytest.raises(ValueError, match="unknown or missing fields"):
            MODULE.verify_observer_signature(forged, trusted_key)


def test_report_rejects_unsigned_top_level_extensions(tmp_path: Path) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    MODULE.validate_report(report)
    with pytest.raises(ValueError, match="unknown or missing fields"):
        MODULE.validate_report({**report, "physicalSplitApproved": True})
    incomplete = dict(report)
    del incomplete["blockingCases"]
    with pytest.raises(ValueError, match="unknown or missing fields"):
        MODULE.validate_report(incomplete)


def test_ed25519_observer_key_must_have_prime_order() -> None:
    """Strict key validation prevents low-order and mixed-order acceptance."""
    private = Ed25519PrivateKey.generate()
    trusted_key = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    assert MODULE._ed25519_prime_order_public_key(trusted_key)
    field = 2**255 - 19
    low_order_and_noncanonical = (
        bytes(32),
        b"\x01" + bytes(31),
        field.to_bytes(32, "little"),
        b"\xff" * 32,
    )
    for key in low_order_and_noncanonical:
        assert not MODULE._ed25519_prime_order_public_key(key)

    # On twisted Edwards25519, adding its order-2 point (0, -1)
    # changes (x, y) to (-x, -y), preserving the curve but adding torsion.
    encoded = int.from_bytes(trusted_key, "little")
    y = encoded & ((1 << 255) - 1)
    x_sign = encoded >> 255
    mixed = (((-y) % field) | ((1 - x_sign) << 255)).to_bytes(32, "little")
    assert not MODULE._ed25519_prime_order_public_key(mixed)


def test_forged_verified_observer_cannot_qualify_report_without_signature(
    tmp_path: Path,
) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    for row in report["cases"]:
        row["status"] = "measured"
        row["metrics"] = example_metrics()
        row["metricsDigest"] = MODULE.digest(row["metrics"])
        row.pop("reason", None)
    provisional = {
        key: report[key]
        for key in (
            "schema",
            "authority",
            "cellCounts",
            "sourceCommit",
            "workloadDigest",
            "workloadSourceDigest",
            "host",
            "cases",
        )
    }
    observer = {
        "schema": MODULE.OBSERVER_SCHEMA,
        "verified": True,
        "sourceCommit": report["sourceCommit"],
        "workloadDigest": report["workloadDigest"],
        "reportDigest": MODULE.digest(provisional),
        "metricsDigest": MODULE.digest(
            [
                {"caseId": row["caseId"], "metricsDigest": row["metricsDigest"]}
                for row in report["cases"]
            ]
        ),
        "observerId": "untrusted",
    }
    observer["signatureHex"] = "00" * 64
    observer["receiptDigest"] = MODULE.digest(observer)
    report["observer"] = observer
    report["blockingCases"] = []
    report["status"] = "qualified"
    report["reportDigest"] = MODULE.digest({**provisional, "observer": observer})
    with pytest.raises(ValueError, match="trusted independent"):
        MODULE.validate_report(report)
    with pytest.raises(ValueError, match="signature invalid"):
        MODULE.validate_report(report, trusted_observer_public_key="00" * 32)


def test_integer_measurement_units_reject_fractional_counter_values() -> None:
    base = example_metrics()
    for name in (
        "p50Micros",
        "p95Micros",
        "p99Micros",
        "cpuMicros",
        "rssBytes",
        "communicationBytes",
        "fsyncCount",
        "walBytes",
        "walFsyncCount",
        "lockWaitMicros",
        "recoveryMicros",
        "negativeMigrationQ32",
    ):
        with pytest.raises(ValueError, match="must be an integer"):
            MODULE.validate_metrics({**base, name: 1.5})
    with pytest.raises(ValueError, match="bounded counter range"):
        MODULE.validate_metrics({**base, "throughputPerSecond": 1e100})


def test_report_validator_rejects_unknown_status_and_removed_blockers(
    tmp_path: Path,
) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    # The current reportDigest does not bind status/blockingCases; validation
    # must independently enforce canonical fail-closed classification.
    assert MODULE.validate_report(report) is None
    for invalid in ("released", "ready", "", None):
        with pytest.raises(ValueError, match="invalid matrix report status"):
            MODULE.validate_report({**report, "status": invalid})
    with pytest.raises(ValueError, match="blocker list/status inconsistent"):
        MODULE.validate_report({**report, "blockingCases": []})
    with pytest.raises(ValueError, match="blocker list/status inconsistent"):
        MODULE.validate_report({**report, "blockingCases": ["independent-observer"]})
    with pytest.raises(ValueError, match="noncanonical matrix blocker list"):
        MODULE.validate_report(
            {
                **report,
                "blockingCases": report["blockingCases"] + [report["blockingCases"][0]],
            }
        )
    with pytest.raises(ValueError, match="blocker list/status inconsistent"):
        MODULE.validate_report(
            {
                **report,
                "blockingCases": sorted(report["blockingCases"] + ["unexpected"]),
            }
        )


def test_report_validator_rejects_unknown_case_status_even_if_rehashed(
    tmp_path: Path,
) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    forged = {**report, "cases": [dict(row) for row in report["cases"]]}
    forged["cases"][0]["status"] = "skipped"
    provisional = {
        key: forged[key]
        for key in (
            "schema",
            "authority",
            "cellCounts",
            "sourceCommit",
            "workloadDigest",
            "workloadSourceDigest",
            "host",
            "cases",
        )
    }
    forged["reportDigest"] = MODULE.digest(
        {**provisional, "observer": forged["observer"]}
    )
    with pytest.raises(ValueError, match="invalid matrix case status"):
        MODULE.validate_report(forged)


@pytest.mark.parametrize(
    "bad_metrics", (None, 7, True, "".join(MODULE.REQUIRED_METRICS))
)
def test_malformed_worker_metrics_block_all_cases_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_metrics: object
) -> None:
    frozen = tmp_path / "frozen-tasks"
    frozen.write_bytes(b"malformed worker metrics fixture only")
    frozen_digest = hashlib.sha256(frozen.read_bytes()).hexdigest()

    def malformed_worker(
        argv: list[str], *, env: dict[str, str], timeout_seconds: int | float
    ) -> subprocess.CompletedProcess[str]:
        assert argv == ["fixture-worker"]
        assert timeout_seconds > 0
        receipt = {
            "caseId": env["HEPTA_MATRIX_CASE_ID"],
            "cellCount": int(env["HEPTA_MATRIX_CELL_COUNT"]),
            "sourceCommit": env["HEPTA_MATRIX_SOURCE_COMMIT"],
            "workloadDigest": env["HEPTA_MATRIX_WORKLOAD_DIGEST"],
            "workloadSourceDigest": env["HEPTA_MATRIX_WORKLOAD_DIGEST"],
            "metrics": bad_metrics,
        }
        for name, _ in MODULE.FACTORS:
            receipt[name] = env[f"HEPTA_MATRIX_{name.upper()}"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(receipt), "")

    monkeypatch.setattr(MODULE, "run_isolated_command", malformed_worker)
    report = MODULE.run_matrix(
        workload_command="fixture-worker",
        observer_command=None,
        workload_digest=frozen_digest,
        source_commit=current_checkout_sha(),
        output=tmp_path / "malformed-report.json",
        workload_path=frozen,
        cell_count=64,
    )
    assert report["status"] == "blocked"
    assert len(report["cases"]) == 16
    assert all(case["status"] == "blocked" for case in report["cases"])
    assert all(
        "metrics must be a JSON object" in case["reason"] for case in report["cases"]
    )
    MODULE.validate_report(report)


@pytest.mark.parametrize("bad_id", ([], {}, ["forged-case-id"]))
def test_report_rejects_nonstring_case_ids_without_unhandled_error(
    tmp_path: Path, bad_id: object
) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "invalid-case-id.json",
    )
    report["cases"][0]["caseId"] = bad_id
    with pytest.raises(ValueError, match="unique and complete matrix cases"):
        MODULE.validate_report(report)


def test_metrics_reject_unrecognized_claim_fields() -> None:
    metrics = {**example_metrics(), "productionQualified": True}
    with pytest.raises(ValueError, match="unrecognized fields"):
        MODULE.validate_metrics(metrics)
