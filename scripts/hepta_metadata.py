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


def authority_fixture() -> dict[str, bool]:
    """Return the canonical deny-all metadata object for generated fixtures."""

    return dict.fromkeys(AUTHORITY_KEYS, False)


def has_schema_version(value: object, expected: int) -> bool:
    """Check a versioned registry envelope without repeating shape plumbing."""

    return isinstance(value, dict) and value.get("schemaVersion") == expected
