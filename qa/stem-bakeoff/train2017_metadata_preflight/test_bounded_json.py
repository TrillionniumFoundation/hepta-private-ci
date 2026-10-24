import hashlib
import io
import unittest
from bounded_json import PreflightError, StreamJSON


class ParserTests(unittest.TestCase):
    def parse(self, raw, **kwargs):
        parser = StreamJSON(io.BytesIO(raw), **dict({"byte_limit": len(raw)}, **kwargs))
        return list(parser.items({"images"})), parser

    def test_unicode_tiny_reads_complete_digest(self):
        class Tiny(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 3))

        raw = '{"info":{},"images":[{"text":"猫犬"},{"id":12345}]}'.encode()
        parser = StreamJSON(Tiny(raw), len(raw))
        self.assertEqual(
            list(parser.items({"images"})),
            [("images", {"text": "猫犬"}), ("images", {"id": 12345})],
        )
        self.assertEqual(
            (parser.total_bytes, parser.sha256.hexdigest()),
            (len(raw), hashlib.sha256(raw).hexdigest()),
        )

    def test_rejects_ambiguous_malformed_and_unbounded_json(self):
        cases = [
            b'{"info":{},"images":[],"images":[]}',
            b'{"info":{"x":1,"\\u0078":2},"images":[]}',
            b'{"info":{},"images":[{"x":1,"x":2}]}',
            b'{"info":{},"images":null}',
            b'{"info":{},"images":[1]}',
            b'{"info":{},"images":[{} ,]}',
            b'{"info":{},"images":[],}',
            b'{"images":[]}',
            b'{"info":{},"images":[],"extra":[]}',
            b'{"info":{"x":NaN},"images":[]}',
            b'{"info":{"x":1e999},"images":[]}',
            b'{"info":{},"images":[]} x',
            b'{"info":{},"images":[{',
            b'{"info":{},"images":[{"s":"\xff"}]}',
        ]
        for raw in cases:
            with (
                self.subTest(raw=raw),
                self.assertRaises((PreflightError, UnicodeError)),
            ):
                self.parse(raw)
        raw = b'{"info":{},"images":[{"x":"' + b"a" * 128 + b'"}]}'
        with self.assertRaises(PreflightError):
            self.parse(raw, buffer_limit=32)
        with self.assertRaises(PreflightError):
            self.parse(raw, byte_limit=len(raw) - 1)


if __name__ == "__main__":
    unittest.main()
