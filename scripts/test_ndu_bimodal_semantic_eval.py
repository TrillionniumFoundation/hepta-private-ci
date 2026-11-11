"""Semantic failures are checked from bytes without importing the generator."""

import unittest

from ndu_bimodal.semantic_eval import assess, expected_caption


def card(rgb):
    return b"P6\n16 16\n255\n" + bytes(rgb) * 256


class SemanticChecks(unittest.TestCase):
    def test_valid_framing_does_not_mask_incorrect_content(self):
        red, blue = card((192, 10, 10)), card((10, 10, 192))
        correct = "This image is red.\n".ljust(128)
        cases = (
            (correct, red, True, True),
            ("ue" + "e" * 126, red, False, True),
            ("This image is blue.\n".ljust(128), red, False, True),
            (correct, blue, True, False),
            (correct, card((80, 75, 75)), True, False),
            (correct, b"not an image", True, False),
        )
        for text, generated, text_ok, image_ok in cases:
            with self.subTest(text=text[:24], image_size=len(generated)):
                result = assess(red, text, generated)
                self.assertEqual(
                    (
                        result["text_correct"],
                        result["image_correct"],
                        result["both_correct"],
                    ),
                    (text_ok, image_ok, text_ok and image_ok),
                )

    def test_caption_uses_source_and_rejects_ambiguous_source(self):
        self.assertEqual(expected_caption(card((11, 200, 9))), "This image is green.")
        with self.assertRaises(ValueError):
            expected_caption(card((100, 100, 100)))
        with self.assertRaises(ValueError):
            expected_caption(b"P6\n1 1\n255\n" + bytes((255, 0, 0)))

    def test_trailing_semantic_garbage_and_truncated_delivery_fail(self):
        source = card((12, 15, 200))
        for text in (
            "This image is blue.",
            "This image is blue. Other colour is green.".ljust(128),
            "This image is blue.".ljust(129),
        ):
            with self.subTest(length=len(text)):
                self.assertFalse(assess(source, text, source)["text_correct"])


if __name__ == "__main__":
    unittest.main()
