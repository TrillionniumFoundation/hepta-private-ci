"""Exact-source helpers for the additional ordinary NPQ6 paired scope."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

import hepta_ci_exec as original

PREPARER = "ccdcf7e8bb9871607c73adc78624a607b616c227b7fe581b96c48761a3805bfa"
ARCHIVE = "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a"
PROFILE = "hepta-ordinary-pon-npq6-execution-v1"
EXPORT = "export::export_ordinary_npq6_task_and_evaluator_control_material"
CHAIN_CASES = (
    "ordinary_npq6_submit_and_cold_status_execute_current_task_and_evaluator_roles",
    "ordinary_npq6_configuration_rejects_missing_null_extra_and_mixed_bindings",
    "ordinary_npq6_refuses_existing_owner_context_and_never_creates_a_missing_owner",
    "ordinary_npq6_invalid_packet_encoding_cannot_fall_back_to_classical_settings",
)
EXISTING_PREFIX = "store::pq_existing_owner_tests::"
EXISTING_CASES = tuple(
    EXISTING_PREFIX + name
    for name in (
        "existing_pq_owner_reopens_the_actual_initialized_connection",
        "existing_pq_owner_never_creates_missing_root_lock_or_empty_schema",
        "existing_pq_owner_refuses_matching_initialization_but_original_api_can_recover",
        "existing_pq_owner_refuses_database_loss_or_replacement_before_open",
        "existing_pq_owner_refuses_changed_bindings_after_connection_validation",
        "existing_pq_owner_rejects_link_special_file_and_incompatible_owner_without_repair",
    )
)
PAIRED_PREFIX = (
    "automation_effect_host::pq::tests::packet_chain_tests::npq6_chain_tests::"
)
PAIRED = (
    PAIRED_PREFIX
    + "ordinary_npq6_control_socket_executes_task_and_evaluator_then_cold_offline_receipt",
    PAIRED_PREFIX
    + "ordinary_npq6_started_child_context_refusal_stays_unknown_through_cold_reconciliation",
    PAIRED_PREFIX
    + "ordinary_npq6_signed_provider_rejects_tampered_contract_config_and_profile_before_effect",
)
PROFILE_PREFIX = "automation_effect_host::pon_profile::tests::"
PROFILE_CASES = (
    PROFILE_PREFIX + "npq6_readback_requires_all_exact_context_and_observation_fields",
    PROFILE_PREFIX
    + "npq6_readback_rejects_duplicate_unknown_and_mixed_owner_json_before_value_acceptance",
    PROFILE_PREFIX
    + "npq6_provider_owner_is_mandatory_and_closed_without_nullable_fallback",
    PROFILE_PREFIX
    + "npq6_command_profile_never_adds_classical_flags_and_development_remains_explicit",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest_file(path, *, single_link=True):
    path = Path(path)
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and (not single_link or before.st_nlink == 1),
        f"regular single-link file: {path}",
    )
    digest = hashlib.sha256()
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(
            (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
            "file changed before read",
        )
        while block := stream.read(65536):
            digest.update(block)
    after = path.lstat()
    keys = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_mode",
        "st_nlink",
    )
    require(
        all(getattr(before, k) == getattr(after, k) for k in keys),
        "file changed during read",
    )
    return {"path": str(path), "bytes": after.st_size, "sha256": digest.hexdigest()}


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def environment(changes):
    previous = {key: os.environ.get(key) for key in changes}
    try:
        os.environ.update({key: str(value) for key, value in changes.items()})
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def record(out, label, command, minimum=0, changes=None):
    receipt = out / (label + ".json")
    with environment(changes or {}):
        code = original.run(
            receipt, [str(arg) for arg in command], minimum_tests=minimum
        )
    data = json.loads(receipt.read_text())
    require(
        code == 0 and data["status"] == "passed", f"original recorder refused: {label}"
    )
    if minimum:
        require(
            data["observed_passed_tests"] == minimum
            and data["observed_failed_tests"] == 0,
            f"exact executed count required: {label}",
        )
    require(Path(data["log_file"]).name == data["log_file"], "original log basename")
    log = receipt.parent / data["log_file"]
    return data, log


def artifact(log, name, kind, test):
    found = {}
    for line in log.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        target = row.get("target", {})
        if (
            row.get("reason") == "compiler-artifact"
            and target.get("name") == name
            and kind in target.get("kind", [])
            and row.get("profile", {}).get("test") is test
            and row.get("executable")
        ):
            path = Path(row["executable"]).resolve(strict=True)
            found[str(path)] = path
    require(
        len(found) == 1, f"one actual {name}/{kind}/{test} compiler artifact required"
    )
    return next(iter(found.values()))


def retain(out, path, name):
    destination = out / name
    before = digest_file(path, single_link=False)
    require(not destination.exists(), "retained executable already exists")
    shutil.copyfile(path, destination)
    destination.chmod(0o700)
    after = digest_file(path, single_link=False)
    retained = digest_file(destination)
    require(
        before == after and retained["sha256"] == before["sha256"],
        "artifact changed during retention",
    )
    return retained


def provider(receipt, chain):
    item = json.loads(receipt.read_text())
    require(
        item.get("schema") == "trnm-ci-pq-provider-v3"
        and item.get("result") == "PREPARED_AND_SMOKE_VERIFIED"
        and item.get("exit_code") == 0
        and item.get("version") == "3.5.9"
        and item.get("static_build") is True
        and item.get("backend_exported") is True
        and item.get("source_digest_verified") is True
        and item.get("ml_dsa_65_sign_verify_and_wrong_message_rejection") is True
        and item.get("preparation_script_sha256") == PREPARER
        and item.get("source_archive_sha256_expected") == ARCHIVE,
        "original PQ provider receipt required",
    )
    require(
        digest_file(chain / "scripts/ci/prepare_pq_provider.sh")["sha256"] == PREPARER,
        "actual original provider preparer pin",
    )
    prefix = Path(item["install_prefix"]).resolve(strict=True)
    expected = {
        str(prefix / p)
        for p in (
            "bin/openssl",
            "include/openssl/opensslv.h",
            "include/openssl/configuration.h",
            "lib/libcrypto.a",
            "lib/libssl.a",
        )
    }
    actual = item["native_backend_inputs"]
    require(
        len(actual) == 5 and {row["path"] for row in actual} == expected,
        "all five backend identities",
    )
    for row in actual:
        require(
            digest_file(row["path"]) == row,
            "actual provider bytes differ from original preparation",
        )
    for key, value in {
        "OPENSSL_DIR": str(prefix),
        "OPENSSL_STATIC": "1",
        "TRNM_PQ_OPENSSL": item["cli_executable"],
        "TRNM_PQ_OPENSSL_SHA256": item["cli_sha256"],
        "TRNM_PQ_OPENSSL_VERSION": "3.5.9",
        "OPENSSL_CONF": "/dev/null",
        "OPENSSL_MODULES": item["openssl_modules"],
    }.items():
        require(
            os.environ.get(key) == value,
            f"explicit original provider environment: {key}",
        )
    return item


def exact_registry(text, expected):
    names = [line[:-6] for line in text.splitlines() if line.endswith(": test")]
    require(
        len(names) == len(set(names)) and set(names) == set(expected),
        "fresh exact registry",
    )
    return names


def passed_names(log, expected):
    text = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text())
    names = re.findall(r"^test (\S+) \.\.\. ok$", text, re.MULTILINE)
    require(
        len(names) == len(set(names)) and set(names) == set(expected),
        "exact libtest passes",
    )
    require(
        original.observed_test_counts(text) == (len(expected), 0),
        "exact terminal result",
    )


def list_exact(out, executable):
    _, log = record(
        out, "chain-new-registry", [executable, "--list", "--format", "terse"]
    )
    names = exact_registry(log.read_text(), (*CHAIN_CASES, EXPORT))
    save(out / "chain-new-registry-binding.json", {"names": names, "executed_tests": 0})
