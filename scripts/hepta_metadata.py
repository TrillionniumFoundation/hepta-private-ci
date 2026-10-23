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


def validate_protocol_field_requirements(
    requirements: object, required_protocols: list[str], protocols: dict[str, dict]
) -> None:
    """Compare declared design-field semantics with canonical protocol schemas.

    The design registry owns the required shape; this checker does not embed
    protocol-specific field names or infer a native implementation from it.
    """

    if not isinstance(requirements, dict) or not requirements:
        raise ValueError("protocol field requirements must be a nonempty object")
    for protocol_id, fields in requirements.items():
        if not isinstance(protocol_id, str) or protocol_id not in required_protocols:
            raise ValueError(
                f"field requirements for nonrequired protocol {protocol_id}"
            )
        if protocol_id not in protocols:
            raise ValueError(f"field requirements for missing protocol {protocol_id}")
        if not isinstance(fields, list) or not fields:
            raise ValueError(f"empty protocol field requirements {protocol_id}")
        actual_fields = protocols[protocol_id].get("fields")
        if not isinstance(actual_fields, list) or not all(
            isinstance(field, dict) and isinstance(field.get("name"), str)
            for field in actual_fields
        ):
            raise ValueError(f"invalid protocol fields {protocol_id}")
        actual = {field["name"]: field for field in actual_fields}
        if len(actual) != len(actual_fields):
            raise ValueError(f"protocol duplicate field {protocol_id}")
        seen = set()
        for field in fields:
            if not isinstance(field, dict) or not (
                {"name", "type", "required"}
                <= set(field)
                <= {"name", "type", "required", "maxBytes"}
            ):
                raise ValueError(f"invalid protocol field requirement {protocol_id}")
            name = field["name"]
            if not isinstance(name, str) or not name or name in seen:
                raise ValueError(
                    f"invalid or duplicate field requirement {protocol_id}"
                )
            seen.add(name)
            if (
                not isinstance(field["type"], str)
                or not field["type"]
                or type(field["required"]) is not bool
            ):
                raise ValueError(f"invalid field semantics {protocol_id}.{name}")
            if "maxBytes" in field and (
                type(field["maxBytes"]) is not int or field["maxBytes"] <= 0
            ):
                raise ValueError(
                    f"invalid field bound requirement {protocol_id}.{name}"
                )
            if name not in actual:
                raise ValueError(
                    f"required protocol field missing {protocol_id}.{name}"
                )
            if actual[name].get("type") != field["type"]:
                raise ValueError(f"protocol field type drift {protocol_id}.{name}")
            if actual[name].get("required") is not field["required"]:
                raise ValueError(
                    f"protocol field requiredness drift {protocol_id}.{name}"
                )
            if "maxBytes" in field and (
                type(actual[name].get("maxBytes")) is not int
                or actual[name]["maxBytes"] != field["maxBytes"]
            ):
                raise ValueError(f"protocol field bound drift {protocol_id}.{name}")
