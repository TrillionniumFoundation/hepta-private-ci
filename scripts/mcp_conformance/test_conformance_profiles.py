"""Profile metadata and migration tests use synthetic reports, not attestations."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import conformance_profiles as profiles
from run_codex_compliance import (
    _compact_regression_baseline,
    _evaluate_regression_gate,
    _write_compact_regression_baseline,
    main,
)


def vendor_candidate() -> dict[str, object]:
    report = deepcopy(profiles.legacy_baseline())
    report["conformanceProfile"] = profiles.VENDOR_PROFILE
    report["officialConformance"]["gitRef"] = profiles.descriptor()["gitRef"]
    report["executionIdentity"] = {
        "identity": profiles.descriptor(),
        "descriptorSha256": profiles.DESCRIPTOR_SHA256,
    }
    for record in profiles.required_fixed_checks():
        report["checks"]["failing"].remove(record)
        report["checks"]["passing"].append(record)
    return report


def executable(tmp_path: Path) -> Path:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_historical_metadata_keeps_its_original_profile() -> None:
    original = profiles.legacy_baseline()
    assert profiles.validate_metadata(original) == profiles.LEGACY_PROFILE
    assert "conformanceProfile" not in original
    assert "executionIdentity" not in original


def test_cli_requires_an_explicit_profile_before_starting_a_binary(
    tmp_path, capsys
) -> None:
    assert main([str(executable(tmp_path))]) == 2
    assert "must be selected explicitly" in capsys.readouterr().err


def test_legacy_execution_rejects_an_unverified_cli_override(tmp_path) -> None:
    with pytest.raises(ValueError, match="arbitrary CLI overrides"):
        profiles.verify_execution(profiles.LEGACY_PROFILE, tmp_path / "cli.js")


def test_vendor_execution_rejects_a_missing_cli_before_starting_a_binary(
    tmp_path, capsys
) -> None:
    assert (
        main(
            [
                str(executable(tmp_path)),
                "--conformance-profile",
                profiles.VENDOR_PROFILE,
            ]
        )
        == 2
    )
    assert "requires --conformance-cli" in capsys.readouterr().err


@pytest.mark.parametrize(
    "mutation", ["profile", "ref", "dist", "lock", "patch", "missing_identity"]
)
def test_report_rejects_mixed_or_changed_execution_identity(mutation) -> None:
    report = vendor_candidate()
    if mutation == "profile":
        report["conformanceProfile"] = profiles.LEGACY_PROFILE
    elif mutation == "ref":
        report["officialConformance"]["gitRef"] = profiles.LEGACY_REF
    elif mutation == "missing_identity":
        del report["executionIdentity"]
    elif mutation == "dist":
        report["executionIdentity"]["identity"]["dist"]["index.js"] = "0" * 64
    else:
        pins = report["executionIdentity"]["identity"]["sourcePins"]
        name = (
            "pnpm-lock.yaml"
            if mutation == "lock"
            else "third_party/mcp-conformance-patches/sdk-1.32-reference-clients.patch"
        )
        pins[name] = "0" * 64
    assert _evaluate_regression_gate(report, vendor_candidate())["success"] is False


def test_profile_change_is_not_an_implicit_baseline_migration() -> None:
    gate = _evaluate_regression_gate(vendor_candidate(), profiles.legacy_baseline())
    assert gate["success"] is False
    assert "different conformance execution profiles" in gate["configurationErrors"][0]


def test_baseline_writer_preserves_the_original_historical_file() -> None:
    path = Path(profiles.__file__).with_name("regression-baseline-v1.json")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="must remain unchanged"):
        _write_compact_regression_baseline(vendor_candidate(), path)
    assert path.read_bytes() == before


def test_cli_rejects_a_cross_profile_baseline_before_starting_conformance(
    tmp_path, capsys
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(profiles.legacy_baseline()), encoding="utf-8")
    assert (
        main(
            [
                str(executable(tmp_path)),
                "--conformance-profile",
                profiles.VENDOR_PROFILE,
                "--baseline-report",
                str(baseline),
            ]
        )
        == 2
    )
    assert "different conformance execution profile" in capsys.readouterr().err


def test_vendor_baseline_preserves_every_legacy_pass_and_requires_the_ten_repairs() -> (
    None
):
    compact = _compact_regression_baseline(vendor_candidate())
    original = profiles.legacy_baseline()
    assert compact["conformanceProfile"] == profiles.VENDOR_PROFILE
    assert compact["officialConformance"]["gitRef"] == profiles.descriptor()["gitRef"]
    assert all(
        record in compact["checks"]["passing"]
        for record in original["checks"]["passing"]
    )
    assert all(
        record in compact["checks"]["passing"]
        for record in profiles.required_fixed_checks()
    )
    assert len(compact["checks"]["failing"]) == len(original["checks"]["failing"]) - 10
    assert _evaluate_regression_gate(vendor_candidate(), compact)["success"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_pass",
        "regressed_pass",
        "new_failure",
        "repaired_failure",
        "missing_repair",
        "identity_changed",
    ],
)
def test_vendor_baseline_migration_fails_closed(mutation) -> None:
    report = vendor_candidate()
    if mutation in {"missing_pass", "regressed_pass"}:
        record = profiles.legacy_baseline()["checks"]["passing"][0]
        report["checks"]["passing"].remove(record)
        if mutation == "regressed_pass":
            report["checks"]["failing"].append(record)
    elif mutation == "new_failure":
        record = deepcopy(report["checks"]["failing"][0])
        record["check_id"] += "-new"
        report["checks"]["failing"].append(record)
    elif mutation in {"repaired_failure", "missing_repair"}:
        record = profiles.required_fixed_checks()[0]
        report["checks"]["passing"].remove(record)
        if mutation == "repaired_failure":
            report["checks"]["failing"].append(record)
    else:
        report["executionIdentityError"] = "source changed during run"
    with pytest.raises(ValueError):
        _compact_regression_baseline(report)


@pytest.mark.parametrize(
    "flag",
    ["sourceVerified", "canonicalRebuildMatched", "selectedCli", "descriptorSha256"],
)
def test_execution_rejects_an_incomplete_verifier_result(
    monkeypatch, tmp_path, flag
) -> None:
    cli = tmp_path / "index.js"
    verified = {
        "identity": profiles.descriptor(),
        "descriptorSha256": profiles.DESCRIPTOR_SHA256,
        "sourceVerified": True,
        "canonicalRebuildMatched": True,
        "selectedCli": str(cli),
    }
    verified[flag] = False
    monkeypatch.setattr(profiles.shutil, "which", lambda _: "/owned/node")
    monkeypatch.setattr(
        profiles.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(verified)),
    )
    with pytest.raises(ValueError, match="unexpected execution identity"):
        profiles.verify_execution(profiles.VENDOR_PROFILE, cli)
