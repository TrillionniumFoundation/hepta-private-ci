"""Shared metadata vocabulary for Hepta repository verifiers.

The authority vocabulary is a repository contract, not a copy of every
verifier's implementation. Keeping it here prevents schema drift while each
verifier remains responsible for the rules of its own document family. The
JSON registries still carry explicit deny-all flags on their wire format so a
reviewer can see the boundary without inferring it from verifier code.
"""

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
