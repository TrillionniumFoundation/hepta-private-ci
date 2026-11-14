"""Bridge canonical finite binary64 inputs into Decimal uniformization.

Every numeric input is decoded from canonical big-endian binary64 hexadecimal
text without constructing a Python float.  This module certifies only that
input bridge.  Decimal exponential evaluation, finite-precision output
rounding, authentic N256 loading, and provider qualification remain separate.
"""

from dataclasses import dataclass

from qualification.hcsn_currentstate_n256_fp64_input_conversion.fp64_exact import (
    Fp64ConversionCertificate,
    Fp64InputError,
    fp64_hex_to_exact_decimal,
)
from qualification.hcsn_currentstate_n256_uniformization_primitive.uniformization import (
    TruncationCertificate,
    UniformizationError,
    uniformization_action,
)


class Fp64UniformizationBridgeError(ValueError):
    """Raised when the exact-input bridge cannot establish its domain."""


@dataclass(frozen=True)
class Fp64UniformizationBridgeCertificate:
    operator_value_conversions: int
    vector_value_conversions: int
    scalar_conversions: int
    conversion_certificates: tuple[Fp64ConversionCertificate, ...]
    truncation_certificate: TruncationCertificate
    exact_fp64_input_bridge_certified: bool = True
    uniformization_output_rounding_certified: bool = False
    authentic_n256_bundle_loaded: bool = False
    provider_qualified: bool = False


def _convert(input_hex, name, certificates):
    try:
        decimal, certificate = fp64_hex_to_exact_decimal(input_hex)
    except Fp64InputError as error:
        raise Fp64UniformizationBridgeError(f"{name}: {error}") from error
    certificates.append(certificate)
    return decimal


def uniformization_action_from_fp64(
    rows_hex,
    vector_hex,
    duration_hex,
    absolute_l1_tolerance_hex,
    *,
    precision=80,
    max_terms=200000,
):
    """Apply the bounded primitive after exact conversion of every binary64 input."""

    if not isinstance(rows_hex, (tuple, list)) or not rows_hex:
        raise Fp64UniformizationBridgeError("operator rows must be a non-empty sequence")
    certificates = []
    rows = []
    operator_count = 0
    for row in rows_hex:
        if not isinstance(row, (tuple, list)):
            raise Fp64UniformizationBridgeError("each operator row must be a sequence")
        converted_row = []
        for entry in row:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise Fp64UniformizationBridgeError("operator entry must be (column, value_hex)")
            column, value_hex = entry
            converted_row.append(
                (column, _convert(value_hex, "operator value", certificates))
            )
            operator_count += 1
        rows.append(tuple(converted_row))

    if not isinstance(vector_hex, (tuple, list)):
        raise Fp64UniformizationBridgeError("vector must be a sequence")
    vector = tuple(_convert(value, "vector value", certificates) for value in vector_hex)
    duration = _convert(duration_hex, "duration", certificates)
    tolerance = _convert(
        absolute_l1_tolerance_hex,
        "absolute_l1_tolerance",
        certificates,
    )
    try:
        output, truncation = uniformization_action(
            tuple(rows),
            vector,
            duration,
            tolerance,
            precision=precision,
            max_terms=max_terms,
        )
    except UniformizationError as error:
        raise Fp64UniformizationBridgeError(str(error)) from error
    certificate = Fp64UniformizationBridgeCertificate(
        operator_value_conversions=operator_count,
        vector_value_conversions=len(vector),
        scalar_conversions=2,
        conversion_certificates=tuple(certificates),
        truncation_certificate=truncation,
    )
    return output, certificate

