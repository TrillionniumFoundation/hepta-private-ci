"""Dependency-contract tests; manufactured identities grant no authenticity."""

from dataclasses import FrozenInstanceError, replace
import unittest

from .critic_context import (
    CriticContext,
    CriticContextError,
    context_digest,
    require_context,
)


class CriticContextTests(unittest.TestCase):
    def test_strict_complete_immutable_identity_round_trip(self):
        context = CriticContext(
            **{name: "a" * 64 for name in CriticContext.__dataclass_fields__}
        )
        self.assertEqual(CriticContext.from_wire(context.to_wire()), context)
        self.assertEqual(require_context(context, context), context)
        with self.assertRaises(FrozenInstanceError):
            context.encoder_sha256 = "b" * 64
        for field in CriticContext.__dataclass_fields__:
            wire = context.to_wire()
            del wire[field]
            with self.assertRaises(CriticContextError):
                CriticContext.from_wire(wire)
            changed = replace(context, **{field: "b" * 64})
            self.assertNotEqual(context_digest(changed), context_digest(context))
            with self.assertRaisesRegex(CriticContextError, field):
                require_context(changed, context)
        for value in (None, False, 0, "a" * 63, "A" * 64, "g" * 64):
            with self.assertRaises(CriticContextError):
                replace(context, encoder_sha256=value)
        for wire in (None, {}, {**context.to_wire(), "extra": "a" * 64}):
            with self.assertRaises(CriticContextError):
                CriticContext.from_wire(wire)
        with self.assertRaises(CriticContextError):
            require_context(None, context)


if __name__ == "__main__":
    unittest.main()
