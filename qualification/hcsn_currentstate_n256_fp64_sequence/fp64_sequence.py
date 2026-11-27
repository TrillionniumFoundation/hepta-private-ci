"""Evaluate an explicit finite binary64 register program in declared order.

Every non-FMA instruction rounds through one frozen single-operation primitive.
Every FMA instruction has one fused rounding boundary. Nonfinite inputs and
nonfinite intermediates are outside this deliberately narrow source contract.
"""

from dataclasses import dataclass

from qualification.hcsn_currentstate_n256_fp64_add_sub.fp64_add_sub import (
    Fp64AddSubError,
    binary64_add_sub,
)
from qualification.hcsn_currentstate_n256_fp64_fma.fp64_fma import (
    Fp64FmaError,
    binary64_fma,
)
from qualification.hcsn_currentstate_n256_fp64_mul_div.fp64_mul_div import (
    Fp64MulDivError,
    _decode_finite_fp64_hex,
    binary64_mul_div,
)


class Fp64SequenceError(ValueError):
    """Raised when a program is outside the explicit finite sequence contract."""


@dataclass(frozen=True)
class Fp64SequenceStep:
    index: int
    operation: str
    destination: str
    input_registers: tuple
    input_hex: tuple
    output_hex: str


@dataclass(frozen=True)
class Fp64SequenceCertificate:
    input_register_count: int
    instruction_count: int
    steps: tuple
    final_registers: tuple
    rounding_mode: str = "roundTiesToEven"
    explicit_finite_sequence_certified: bool = True
    arbitrary_program_certified: bool = False
    n256_provider_qualified: bool = False


def _validate_register_name(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 32:
        raise Fp64SequenceError("register names must be 1..32 ASCII identifier characters")
    if not (name[0].isalpha() or name[0] == "_"):
        raise Fp64SequenceError("register names must start with an ASCII letter or underscore")
    if not name.isascii() or any(not (character.isalnum() or character == "_") for character in name):
        raise Fp64SequenceError("register names must be ASCII identifiers")


def _require_finite(value_hex):
    try:
        _decode_finite_fp64_hex(value_hex)
    except Fp64MulDivError as error:
        raise Fp64SequenceError(str(error)) from error


def _source(registers, name):
    _validate_register_name(name)
    if name not in registers:
        raise Fp64SequenceError(f"unknown source register: {name}")
    return registers[name]


def binary64_evaluate_sequence(input_registers, instructions):
    """Execute a validated register program with explicit binary64 boundaries."""

    if not isinstance(input_registers, dict) or not input_registers:
        raise Fp64SequenceError("input_registers must be a nonempty dictionary")
    if not isinstance(instructions, (list, tuple)) or not instructions:
        raise Fp64SequenceError("instructions must be a nonempty list or tuple")
    registers = {}
    for name, value_hex in input_registers.items():
        _validate_register_name(name)
        if name in registers:
            raise Fp64SequenceError(f"duplicate input register: {name}")
        _require_finite(value_hex)
        registers[name] = value_hex

    steps = []
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, dict):
            raise Fp64SequenceError("each instruction must be a dictionary")
        operation = instruction.get("op")
        destination = instruction.get("dst")
        _validate_register_name(destination)
        try:
            if operation in {"add", "subtract", "multiply", "divide"}:
                expected = {"op", "dst", "lhs", "rhs"}
                if set(instruction) != expected:
                    raise Fp64SequenceError("binary instruction keys do not match the contract")
                input_names = (instruction["lhs"], instruction["rhs"])
                input_hex = tuple(_source(registers, name) for name in input_names)
                if operation in {"add", "subtract"}:
                    output_hex, _ = binary64_add_sub(*input_hex, operation)
                else:
                    output_hex, _ = binary64_mul_div(*input_hex, operation)
            elif operation == "fma":
                expected = {"op", "dst", "multiplicand", "multiplier", "addend"}
                if set(instruction) != expected:
                    raise Fp64SequenceError("FMA instruction keys do not match the contract")
                input_names = (
                    instruction["multiplicand"],
                    instruction["multiplier"],
                    instruction["addend"],
                )
                input_hex = tuple(_source(registers, name) for name in input_names)
                output_hex, _ = binary64_fma(*input_hex)
            else:
                raise Fp64SequenceError("unsupported operation")
        except (Fp64AddSubError, Fp64MulDivError, Fp64FmaError) as error:
            raise Fp64SequenceError(str(error)) from error
        _require_finite(output_hex)
        registers[destination] = output_hex
        steps.append(
            Fp64SequenceStep(
                index=index,
                operation=operation,
                destination=destination,
                input_registers=input_names,
                input_hex=input_hex,
                output_hex=output_hex,
            )
        )

    final_registers = tuple(sorted(registers.items()))
    certificate = Fp64SequenceCertificate(
        input_register_count=len(input_registers),
        instruction_count=len(instructions),
        steps=tuple(steps),
        final_registers=final_registers,
    )
    return dict(final_registers), certificate
