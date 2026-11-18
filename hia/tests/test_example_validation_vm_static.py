"""Fail-closed static screening for the restricted source interpreter.

This is independent of the Hepta compiler: it prevents the Python proxy from
accepting malformed HIA that happens not to execute its invalid instruction.
"""
import unittest
from pathlib import Path

from example_validation_source_vm import Program

SOURCE = (Path(__file__).parent / 'example_validation_continuation.hepta').read_text()


class VmStaticScreen(unittest.TestCase):
    def test_original_source_admitted(self):
        self.assertEqual(len(Program(SOURCE).blocks), 26)

    def test_header_and_signature_must_match_exactly(self):
        for old in (SOURCE.splitlines()[0], SOURCE.splitlines()[1]):
            with self.subTest(prefix=old[:16]):
                with self.assertRaises(ValueError):
                    Program(SOURCE.replace(old, old + ' trailing-garbage', 1))

    def test_reject_unknown_unreachable_opcode(self):
        source = SOURCE.replace(
            'block invalid()\n',
            'block invalid()\n  ignored:u64 = panic.unknown()\n', 1,
        )
        with self.assertRaisesRegex(ValueError, 'unsupported operation'):
            Program(source)

    def test_reject_undefined_value_before_execution(self):
        source = SOURCE.replace(
            'e09_is_hit:bool = compare.eq(e09_hit,e09_one)',
            'e09_is_hit:bool = compare.eq(e09_absent,e09_one)', 1,
        )
        with self.assertRaisesRegex(ValueError, 'undefined SSA'):
            Program(source)

    def test_reject_wrong_block_argument_types(self):
        source = SOURCE.replace(
            'negative_stop(e09_output,e09_index)',
            'negative_stop(e09_index,e09_output)', 1,
        )
        with self.assertRaisesRegex(ValueError, 'wrong block argument types'):
            Program(source)

    def test_reject_wrong_operand_types(self):
        source = SOURCE.replace(
            'e09_is_hit:bool = compare.eq(e09_hit,e09_one)',
            'e09_is_hit:bool = compare.eq(e09_hit,e09_output)', 1,
        )
        with self.assertRaisesRegex(ValueError, 'invalid compare operands'):
            Program(source)

    def test_reject_early_terminator_even_if_last_is_valid(self):
        source = SOURCE.replace(
            'block invalid()\n',
            'block invalid()\n  jump short()\n', 1,
        )
        with self.assertRaisesRegex(ValueError, 'terminator must be final'):
            Program(source)

    def test_reject_duplicate_block_parameter(self):
        source = SOURCE.replace(
            'block load(e03_source:readbuf,e03_output:mutbuf)',
            'block load(e03_source:readbuf,e03_source:mutbuf)', 1,
        )
        with self.assertRaisesRegex(ValueError, 'duplicate or invalid parameter'):
            Program(source)


if __name__ == '__main__':
    unittest.main()
