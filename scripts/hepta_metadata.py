"""Shared metadata vocabulary for Hepta repository verifiers.

The authority vocabulary is a repository contract, not a copy of every
verifier's implementation. Keeping it here prevents schema drift while each
verifier remains responsible for the rules of its own document family. The
JSON registries still carry explicit deny-all flags on their wire format so a
reviewer can see the boundary without inferring it from verifier code.
"""

from pathlib import Path, PurePosixPath


AUTHORITY_KEYS = [
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
]


_AUTHORITY_KEY_SET = frozenset(AUTHORITY_KEYS)


def has_deny_all_authority(value: object) -> bool:
    """Require exact authority keys and explicit JSON false, independent of key order.

    Numeric zero, null and empty containers are not boolean denial. This checks
    document metadata only; a successful check never grants runtime authority.
    """
    return (
        isinstance(value, dict)
        and value.keys() == _AUTHORITY_KEY_SET
        and all(flag is False for flag in value.values())
    )


def authority_fixture() -> dict[str, bool]:
    """Return the canonical deny-all metadata object for generated fixtures."""

    return dict.fromkeys(AUTHORITY_KEYS, False)


def has_schema_version(value: object, expected: int) -> bool:
    """Check a versioned registry envelope without repeating shape plumbing."""

    return (
        isinstance(value, dict)
        and type(expected) is int
        and type(value.get("schemaVersion")) is int
        and value["schemaVersion"] == expected
    )


def has_object_keys(value: object, expected: list[str]) -> bool:
    """Validate an exact JSON object shape, not its serialization key order.

    Values, collection ordering and content identities remain the owning
    verifier's responsibility. JSON loaders must still reject duplicate keys.
    """
    return isinstance(value, dict) and value.keys() == set(expected)


def has_registry_ids(rows: object, *, required=(), key: str = "id") -> bool:
    """Check named obligations and unique identities, not a historical row count.

    Required identities are semantic obligations of the owning protocol. Extra
    rows still need their owner's shape, bounds, references and authority checks.
    """
    if not isinstance(rows, list) or not rows:
        return False
    identities = []
    for row in rows:
        if not isinstance(row, dict):
            return False
        identity = row.get(key)
        if (
            not isinstance(identity, str)
            or not identity
            or identity.strip() != identity
        ):
            return False
        identities.append(identity)
    return len(identities) == len(set(identities)) and set(required) <= set(identities)


def has_repository_references(value: object, root: Path) -> bool:
    """Require real repository-local evidence files, not particular prose labels.

    Fragment names remain the format-specific consumer's responsibility. This
    verifies file identity and containment, not test execution or acceptance.
    """
    if not isinstance(value, list) or not value:
        return False
    seen = set()
    for reference in value:
        if not isinstance(reference, str) or reference in seen:
            return False
        seen.add(reference)
        target, separator, fragment = reference.partition("#")
        path = PurePosixPath(target)
        if (
            not target
            or "\\" in target
            or path.is_absolute()
            or str(path) != target
            or ".." in path.parts
            or (separator and not fragment.strip())
        ):
            return False
        try:
            resolved = (root / path).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
                return False
        except (OSError, RuntimeError):
            return False
    return True
