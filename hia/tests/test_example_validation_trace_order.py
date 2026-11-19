"""Pure-source, independent Rust-semantics trace oracle for HIA example validation.

This executes only the checked-in HIA text using the restricted Python VM;
it does not call the Hepta compiler, Rust callbacks, or the Codex product.
"""

import itertools
import random
import unittest
from pathlib import Path

from example_validation_source_vm import Program, interpret_event


HIA_SOURCE = Path(__file__).resolve().parents[1] / "example_validation_continuation.hepta"
FALLBACK = "unable to render example"


class CallbackPanic(Exception):
    pass


def _perform_callback(index, hits, actions, panic_at):
    actions.append(("match", index))
    if index == panic_at:
        actions.append(("match_panic", index))
        raise CallbackPanic(index)
    return hits[index]


def _format_missing(index, actions, fails):
    actions.append(("render", index))
    return FALLBACK if index in fails else f"example-{index}"


def _debug_rules(actions, panic_debug):
    actions.append(("debug_rules",))
    if panic_debug:
        actions.append(("debug_panic",))
        raise CallbackPanic("debug")
    return ["rule-0", "rule-1"]


def _debug_first_rule(index, actions, panic_debug):
    actions.append(("debug_first", index))
    if panic_debug:
        actions.append(("debug_panic",))
        raise CallbackPanic("debug")
    return f"rule-{index}"


def original_rust_trace(mode, hits, panic_at=None, render_fails=(), panic_debug=False):
    """Faithful event ordering of the two original loops in execpolicy/rule.rs."""
    actions = []
    try:
        if mode == 1:
            missing = []
            for index in range(len(hits)):
                if _perform_callback(index, hits, actions, panic_at):
                    continue
                missing.append(_format_missing(index, actions, render_fails))
            if missing:
                rules = _debug_rules(actions, panic_debug)
                return ("positive_error", rules, missing), actions
            return ("ok",), actions
        for index in range(len(hits)):
            if _perform_callback(index, hits, actions, panic_at):
                rule = _debug_first_rule(index, actions, panic_debug)
                rendered = _format_missing(index, actions, render_fails)
                return ("negative_error", rule, rendered), actions
        return ("ok",), actions
    except CallbackPanic as exc:
        return ("panic", str(exc)), actions


def hia_trace(program, mode, hits, panic_at=None, render_fails=(), panic_debug=False):
    """Use HIA decisions as a driver, with host-only callbacks and formatting."""
    actions = []
    misses = []
    index = 0
    try:
        if not hits:
            assert interpret_event(program, mode, 0, 0, 0, 0) == (0, 0, 0, 0)
            return ("ok",), actions
        while index < len(hits):
            hit = _perform_callback(index, hits, actions, panic_at)
            event = interpret_event(program, mode, len(hits), index, len(misses), int(hit))
            if event is None:
                raise AssertionError("HIA rejected reachable state")
            tag, next_index, nmisses, reserved = event
            if reserved != 0:
                raise AssertionError("nonzero reserved HIA response")
            if tag == 4:
                if mode != 0 or not hit or next_index != index:
                    raise AssertionError("invalid negative-stop continuation")
                rule = _debug_first_rule(index, actions, panic_debug)
                rendered = _format_missing(index, actions, render_fails)
                return ("negative_error", rule, rendered), actions
            if tag in (2, 3):
                if mode != 1 or hit:
                    raise AssertionError("unexpected render request")
                misses.append(_format_missing(index, actions, render_fails))
            if nmisses != len(misses) or next_index != index + 1:
                raise AssertionError("inconsistent HIA continuation")
            if tag == 0:
                if next_index != len(hits) or misses:
                    raise AssertionError("early or invalid HIA completion")
                return ("ok",), actions
            if tag in (3, 5):
                if next_index != len(hits) or not misses:
                    raise AssertionError("invalid positive-error continuation")
                rules = _debug_rules(actions, panic_debug)
                return ("positive_error", rules, misses), actions
            if tag not in (1, 2):
                raise AssertionError("unknown or early HIA event")
            index = next_index
        raise AssertionError("HIA did not terminate")
    except CallbackPanic as exc:
        return ("panic", str(exc)), actions


class ExampleValidationTraceOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = Program(HIA_SOURCE.read_text(encoding="utf-8"))

    def check_script(self, mode, hits, panic_at=None, render_fails=(), panic_debug=False):
        expected = original_rust_trace(mode, hits, panic_at, render_fails, panic_debug)
        observed = hia_trace(self.program, mode, hits, panic_at, render_fails, panic_debug)
        self.assertEqual(observed, expected)

    def test_exhaustive_boolean_scripts_and_callback_panic_boundaries(self):
        for n in range(9):
            for hits in itertools.product((False, True), repeat=n):
                for mode in (0, 1):
                    self.check_script(mode, hits)
                    for panic_at in range(n):
                        self.check_script(mode, hits, panic_at=panic_at)

    def test_render_fallback_and_debug_panic_order(self):
        for n in range(7):
            for bits in itertools.product((False, True), repeat=n):
                for mode in (0, 1):
                    self.check_script(mode, bits, render_fails=range(n))
                    self.check_script(mode, bits, panic_debug=True)

    def test_longer_randomized_interleavings_are_deterministic(self):
        rng = random.Random(0x18E5)
        for _ in range(2500):
            n = rng.randrange(0, 32)
            bits = [bool(rng.getrandbits(1)) for _ in range(n)]
            mode = rng.randrange(2)
            panic_at = rng.randrange(n) if n and rng.randrange(5) == 0 else None
            render_fails = set(i for i in range(n) if rng.randrange(7) == 0)
            self.check_script(mode, bits, panic_at, render_fails, rng.randrange(4) == 0)


if __name__ == "__main__":
    unittest.main()
