"""Structural validation of native receipts, not independent execution proof."""
import math

REQUIRED_CHECKS = {"format", "tests", "clippy", "authbus-schema"}
HEX = frozenset("0123456789abcdef")


def validate_native_checks(value: dict, role: str) -> None:
    if value.get("expectedSha") != value.get("head"):
        raise ValueError(f"{role} expected SHA does not match executed source")
    if value.get("trackedChangesBefore") != "" or value.get("trackedChangesAfter") != "":
        raise ValueError(f"{role} source cleanliness is missing or inconsistent")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"{role} has no native checks")
    names = []
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError(f"{role} invalid check entry")
        name = check.get("check")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"{role} missing or duplicate native check")
        names.append(name)
        if type(check.get("exitCode")) is not int or check["exitCode"] != 0:
            raise ValueError(f"{role} native check {name} failed or did not execute")
        digest = check.get("logSha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in HEX for c in digest):
            raise ValueError(f"{role} check {name} has no valid log digest")
        duration = check.get("durationSeconds")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ValueError(f"{role} check {name} has invalid execution duration")
        command = check.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(c, str) or not c for c in command):
            raise ValueError(f"{role} check {name} has no executable command")
        verb = {"format": "fmt", "tests": "test", "clippy": "clippy", "authbus-schema": "test"}.get(name)
        if verb and (command[:2] != ["cargo", verb] or "--no-run" in command):
            raise ValueError(f"{role} check {name} did not invoke its native gate")
        required = {
            "format": {"cargo", "fmt", "codex-hepta-bao-adapter", "--check"},
            "tests": {"cargo", "test", "--locked", "codex-hepta-bao-adapter", "--all-targets"},
            "clippy": {"cargo", "clippy", "--locked", "codex-hepta-bao-adapter", "--all-targets", "-D", "warnings"},
            "authbus-schema": {"cargo", "test", "--locked", "codex-hepta-authbus", "authority_schema"},
        }.get(name, set())
        if not required.issubset(command):
            raise ValueError(f"{role} check {name} has an unexpected qualification scope")
    if not REQUIRED_CHECKS.issubset(names):
        raise ValueError(f"{role} native qualification is incomplete")
    for flag in ("providerDynamicE2E", "productionExecutionProved", "independentAcceptance", "releaseAuthority"):
        if value.get(flag) is not False:
            raise ValueError(f"{role} unsupported authority claim: {flag}")


def validate_native_logs(value: dict, role: str, directory) -> dict:
    """Recompute retained log digests and reject zero-execution test summaries."""
    import hashlib
    import re
    from pathlib import Path
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
        if name in ('tests', 'authbus-schema'):
            if count == 0:
                raise ValueError(f'{role} zero executed native tests: {name}')
            counts[name] = count
    return counts
