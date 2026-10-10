"""Bounded inventory parsing only, never systemd or dpkg execution."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import re


class DiscoveryError(ValueError):
    """A safe error code; no raw metadata, secrets or absolute path in messages."""


@dataclass(frozen=True, order=True)
class Package:
    name: str
    architecture: str
    version: str
    selection: str
    error_flag: str


@dataclass(frozen=True, order=True)
class Unit:
    name: str
    after: tuple[str, ...]
    before: tuple[str, ...]
    requires: tuple[str, ...]
    wants: tuple[str, ...]


def _lines(data: bytes, max_bytes: int) -> list[str]:
    if len(data) > max_bytes:
        raise DiscoveryError("byte_limit")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise DiscoveryError("invalid_utf8") from None
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        raise DiscoveryError("control_character")
    lines = text.splitlines()
    if any(len(line) > 4096 for line in lines):
        raise DiscoveryError("line_limit")
    return lines


def parse_os_release(data: bytes) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in _lines(data, 16_384):
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise DiscoveryError("invalid_os_release")
        if key not in {"ID", "VERSION_ID"}:
            continue
        if key in fields:
            raise DiscoveryError("duplicate_os_field")
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
            raise DiscoveryError("unsupported_os_value")
        fields[key] = value
    if fields.get("ID") != "debian" or "VERSION_ID" not in fields:
        raise DiscoveryError("unsupported_os")
    return fields["ID"], fields["VERSION_ID"]


def parse_packages(data: bytes) -> tuple[tuple[Package, ...], int]:
    packages: list[Package] = []
    seen: set[tuple[str, str]] = set()
    fields: dict[str, str] = {}
    last_key = ""
    record_count = 0
    required = {"Package", "Architecture", "Version", "Status"}
    for line in _lines(data, 2_097_152) + [""]:
        if not line:
            if fields:
                record_count += 1
                if record_count > 4096:
                    raise DiscoveryError("package_limit")
                if "Package" not in fields or "Status" not in fields:
                    raise DiscoveryError("missing_package_field")
                status = fields["Status"].split()
                if (len(status) != 3
                        or status[0] not in {"unknown", "install", "hold", "deinstall", "purge"}
                        or status[1] not in {"ok", "reinstreq"}
                        or status[2] not in {"not-installed", "config-files", "half-installed", "unpacked",
                                             "half-configured", "triggers-awaited", "triggers-pending", "installed"}):
                    raise DiscoveryError("invalid_package_status")
                if status[2] == "installed":
                    if not required <= fields.keys():
                        raise DiscoveryError("missing_package_field")
                    name, arch, version = (fields[k] for k in ("Package", "Architecture", "Version"))
                    if (not re.fullmatch(r"[a-z0-9][a-z0-9+.-]{1,127}", name)
                            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", arch)
                            or not re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,256}", version)):
                        raise DiscoveryError("unsupported_package_value")
                    if (name, arch) in seen:
                        raise DiscoveryError("duplicate_package")
                    seen.add((name, arch))
                    packages.append(Package(name, arch, version, status[0], status[1]))
                fields = {}
                last_key = ""
            continue
        if line[0] in " \t":
            if not last_key or last_key in required:
                raise DiscoveryError("unsupported_continuation")
            continue
        key, sep, value = line.partition(":")
        if not sep or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", key):
            raise DiscoveryError("invalid_package_field")
        if key in fields or len(fields) >= 128:
            raise DiscoveryError("duplicate_or_excess_package_field")
        fields[key] = value.strip()
        last_key = key
    return tuple(sorted(packages)), record_count


def valid_unit_name(name: str) -> bool:
    return bool(re.fullmatch(
        r"[A-Za-z0-9_:@.-]{1,200}\.(service|target|socket|mount|path|timer|slice)", name
    ))


def parse_unit(name: str, data: bytes) -> Unit:
    if not data:
        raise DiscoveryError("masked_unit")
    if not valid_unit_name(name):
        raise DiscoveryError("unsupported_unit_name")
    section = ""
    relations: dict[str, set[str]] = {key: set() for key in ("After", "Before", "Requires", "Wants")}
    for line in _lines(data, 65_536):
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.endswith("\\"):
            raise DiscoveryError("unsupported_continuation")
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise DiscoveryError("invalid_unit_directive")
        key = key.strip()
        if section != "Unit" or key not in relations:
            continue
        # Dependency assignments are additive; an empty value does not reset.
        for dependency in value.split():
            if not valid_unit_name(dependency):
                raise DiscoveryError("unsupported_dependency")
            relations[key].add(dependency)
            if len(relations[key]) > 128:
                raise DiscoveryError("dependency_limit")
    return Unit(name, *(tuple(sorted(relations[key])) for key in ("After", "Before", "Requires", "Wants")))


def ordering_graph(units: tuple[Unit, ...]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Order After/Before only; Requires/Wants are not ordering constraints.

    The second result is blocked nodes (including cycle dependents), not SCCs.
    Missing referenced units remain explicit and are not fabricated inventory.
    """
    if len(units) > 64 or len({unit.name for unit in units}) != len(units):
        raise DiscoveryError("duplicate_or_excess_unit")
    names = {unit.name for unit in units}
    outgoing: dict[str, set[str]] = {name: set() for name in names}
    indegree = dict.fromkeys(names, 0)
    missing: set[str] = set()
    for unit in units:
        missing.update(set(unit.after + unit.before + unit.requires + unit.wants) - names)
        for source, target in [(dep, unit.name) for dep in unit.after] + [(unit.name, dep) for dep in unit.before]:
            if source in names and target in names and target not in outgoing[source]:
                outgoing[source].add(target)
                indegree[target] += 1
    ready = [name for name in names if indegree[name] == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        source = heapq.heappop(ready)
        ordered.append(source)
        for target in sorted(outgoing[source]):
            indegree[target] -= 1
            if not indegree[target]:
                heapq.heappush(ready, target)
    return tuple(ordered), tuple(sorted(names - set(ordered))), tuple(sorted(missing))
