"""Structural validation of current native receipts, not execution authority."""
import hashlib
import math
from pathlib import Path
import re

from qualify import CHECKS

NATIVE_SCHEMA = "hepta.secrets-native-feedback.v2"
REQUIRED_COMMANDS = {name: command for name, _, command in CHECKS}
REQUIRED_CHECKS = frozenset(REQUIRED_COMMANDS)
TEST_CHECKS = frozenset({"tests", "authbus-schema", "authbus-operation"})
HEX = frozenset("0123456789abcdef")


def validate_native_checks(value: dict, role: str) -> None:
    if value.get("schema") != NATIVE_SCHEMA:
        raise ValueError(f"unexpected {role} receipt schema")
    if value.get("expectedSha") != value.get("head"):
        raise ValueError(f"{role} expected SHA does not match executed source")
    if (
        value.get("trackedAndUntrackedBefore") != ""
        or value.get("trackedAndUntrackedAfter") != ""
        or type(value.get("diffCheckBefore")) is not int
        or value["diffCheckBefore"] != 0
        or type(value.get("diffCheckAfter")) is not int
        or value["diffCheckAfter"] != 0
    ):
        raise ValueError(f"{role} source cleanliness is missing or inconsistent")
    if value.get("buildSurface") != "single_complete":
        raise ValueError(f"{role} unexpected build surface")
    if not isinstance(value.get("rustToolchain"), str) or not value["rustToolchain"].startswith("rustc "):
        raise ValueError(f"{role} executed Rust toolchain is missing")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"{role} has no native checks")
    names = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError(f"{role} invalid check entry")
        name = check.get("check")
        if not isinstance(name, str) or name not in REQUIRED_CHECKS or name in names:
            raise ValueError(f"{role} missing, duplicate or unexpected native check")
        names.add(name)
        if type(check.get("exitCode")) is not int or check["exitCode"] != 0:
            raise ValueError(f"{role} native check {name} failed or did not execute")
        digest = check.get("logSha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in HEX for c in digest):
            raise ValueError(f"{role} check {name} has no valid log digest")
        duration = check.get("durationSeconds")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ValueError(f"{role} check {name} has invalid execution duration")
        if check.get("command") != REQUIRED_COMMANDS[name]:
            raise ValueError(f"{role} check {name} has an unexpected qualification scope")
    if names != REQUIRED_CHECKS:
        raise ValueError(f"{role} native qualification is incomplete")
    for flag in (
        "providerDynamicE2E", "productionExecutionProved", "storageProfileQualified",
        "productComposed", "independentAcceptance", "releaseAuthority",
    ):
        if value.get(flag) is not False:
            raise ValueError(f"{role} unsupported authority claim: {flag}")


def validate_native_logs(value: dict, role: str, directory) -> dict:
    """Recompute retained log digests and reject zero-execution test summaries."""
    directory = Path(directory)
    counts = {}
    for check in value['checks']:
        name = check['check']
        if name not in REQUIRED_CHECKS:
            raise ValueError(f'{role} unexpected qualification gate: {name}')
        path = directory / f'{name}.log'
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError(f'{role} retained log unavailable: {name}')
        digest = hashlib.sha256()
        count = 0
        with path.open('rb') as stream:
            for line in stream:
                digest.update(line)
                match = re.search(rb'test result: ok\. (\d+) passed;', line)
                if match:
                    count += int(match.group(1))
        if digest.hexdigest() != check['logSha256']:
            raise ValueError(f'{role} retained log digest mismatch: {name}')
        if name in TEST_CHECKS:
            if count == 0:
                raise ValueError(f'{role} zero executed native tests: {name}')
            counts[name] = count
    return counts
