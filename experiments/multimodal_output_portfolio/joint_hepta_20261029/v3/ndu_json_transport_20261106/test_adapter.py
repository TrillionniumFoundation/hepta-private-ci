"""Synthetic contract boundaries only; no pilot outputs, models, or tools read."""
import hashlib
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ndu_llm_confirmation.transport import invoke

from adapter import DecodeError, Decoded, Schema, decode


class EnvelopeTests(unittest.TestCase):
    def reject(self, text, schema=Schema.QUALIFICATION, code=None):
        with self.assertRaises(DecodeError) as caught:
            decode(text, schema=schema)
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def test_native_and_single_fence_preserve_value_and_bind_raw_bytes(self):
        for text, body, envelope in (
            ('[1]', '[1]', 'native_json'),
            (' \r\n[1]\t', '[1]', 'native_json'),
            ('```json\n[1]\n```', '[1]', 'json_fence'),
            (' \t```json\r\n[1]\r\n```\r\n', '[1]', 'json_fence'),
            ('```json\n \n[1]\n \n```', ' \n[1]\n ', 'json_fence'),
        ):
            with self.subTest(text=text):
                self.assertEqual(decode(text, schema=Schema.QUALIFICATION), Decoded(
                    [1], envelope, 'qualification', hashlib.sha256(text.encode()).hexdigest(),
                    hashlib.sha256(body.encode()).hexdigest()))

    def test_rejects_explanation_multiple_blocks_and_non_json_fences(self):
        invalid = [
            'Here is the answer: [1]', '[1] done', 'text\n```json\n[1]\n```',
            '```json\n[1]\n```\nExplanation', '```json\n[1]\n```\n```json\n[1]\n```',
            '[1]\n[1]', '```\n[1]\n```', '```JSON\n[1]\n```',
            '```python\n[1]\n```', '```javascript\n[1]\n```',
            '````json\n[1]\n````', '~~~json\n[1]\n~~~',
            '```json \n[1]\n```', '```json [1]```', '```json\r[1]\r```',
            '```json\n[1]\n ```', '\ufeff[1]', '\v[1]', '[1]\u00a0',
        ]
        for text in invalid:
            with self.subTest(text=text):
                self.reject(text)

    def test_rejects_truncation_comments_and_python_without_completion(self):
        for text in ('', ' ', '[1', '[1,]', '```json\n[1]', '```json\n[1\n```',
                     '[1] // comment', '[/*comment*/1]', "{'value': 1}",
                     '```json\n[1]\n```\nprint(1)', 'print([1])',
                     '__import__("os").system("echo should-never-run")'):
            with self.subTest(text=text):
                self.reject(text)

    def test_duplicate_keys_include_escaped_and_nested_keys(self):
        for text in ('{"query":"SELECT 1","query":"SELECT 2"}',
                     '{"query":"SELECT 1","q\\u0075ery":"SELECT 2"}',
                     '{"query":{"x":1,"x":2}}'):
            for wrapped in (text, '```json\n'+text+'\n```'):
                with self.subTest(text=wrapped):
                    self.reject(wrapped, Schema.SQL_QUERY, 'duplicate_key')

    def test_rejects_nonfinite_literals_and_numeric_overflow(self):
        for token in ('NaN', 'Infinity', '-Infinity', '1e999', '-1e999'):
            for text in ('[['+token+']]', '```json\n[['+token+']]\n```'):
                with self.subTest(text=text):
                    self.reject(text, Schema.ROWS_ANSWER, 'nonfinite_number')
        self.reject('[[Inf]]', Schema.ROWS_ANSWER, 'invalid_json')

    def test_string_contents_remain_data(self):
        values = ['NaN', 'Infinity', '```json\n[1]\n```', 'print(1)', '中文', '\U0001f642']
        for value in values:
            text = json.dumps([value])
            with self.subTest(value=value):
                self.assertEqual(decode(text, schema=Schema.STRINGS_ANSWER).value, [value])

    def test_unicode_must_encode_as_valid_utf8(self):
        for text in ('["\\ud800"]', '{"\\udfff":"x"}', '["\ud800"]'):
            with self.subTest(text=repr(text)):
                self.reject(text, Schema.STRINGS_ANSWER, 'invalid_unicode')
        self.assertEqual(decode('["\\ud83d\\ude42"]', schema=Schema.STRINGS_ANSWER).value, ['\U0001f642'])

    def test_type_size_depth_and_schema_fail_closed(self):
        for text in (None, b'[1]', [1]):
            self.reject(text, code='text_type')
        self.assertEqual(decode('[1]'+' '*65533, schema=Schema.QUALIFICATION).value, [1])
        self.reject('[1]'+' '*65534, code='text_size')
        self.reject('['*4000+'1'+']'*4000)
        self.reject('[1]', 'qualification', 'unknown_schema')
        for text in ('[true]', '[1.0]', '["1"]', '[1,1]', '1', 'null', 'true'):
            self.reject(text, code='schema_mismatch')


class SchemaTests(unittest.TestCase):
    def reject(self, value, schema):
        with self.assertRaisesRegex(DecodeError, '^schema_mismatch$'):
            decode(json.dumps(value), schema=schema)

    def test_sql_shape_and_exact_character_limit(self):
        for value in ({'query': 'SELECT 1'}, {'query': 'x'*4000}, {'query': '中'*4000}):
            self.assertEqual(decode(json.dumps(value, ensure_ascii=False), schema=Schema.SQL_QUERY).value, value)
        for value in ({'query': ''}, {'query': 'x'*4001}, {'query': 1}, {'query': 'SELECT 1', 'extra': 1},
                      ['SELECT 1'], {'sql': 'SELECT 1'}, None):
            with self.subTest(value=str(value)[:70]):
                self.reject(value, Schema.SQL_QUERY)

    def test_sql_transport_shape_is_not_execution_authorization(self):
        value = {'query': 'DROP TABLE example'}
        self.assertEqual(decode(json.dumps(value), schema=Schema.SQL_QUERY).value, value)
        # No SQL is executed. The unchanged tool authorizer must reject this later.

    def test_source_preserves_original_limits_and_exact_integer_types(self):
        for value in ({'needle': 'x'}, {'needle': 'x'*128}, {'start_line': 1, 'line_count': 1},
                      {'start_line': 10**30, 'line_count': 120}):
            self.assertEqual(decode(json.dumps(value), schema=Schema.SOURCE_READ).value, value)
        invalid = [{'needle': ''}, {'needle': 'x'*129}, {'needle': 1}, {'needle': 'x', 'extra': 1},
                   {'start_line': 0, 'line_count': 1}, {'start_line': True, 'line_count': 1},
                   {'start_line': 1.0, 'line_count': 1}, {'start_line': 1, 'line_count': False},
                   {'start_line': 1, 'line_count': 0}, {'start_line': 1, 'line_count': 121},
                   {'start_line': 1, 'line_count': 1, 'needle': 'x'}, {'start_line': 1}]
        for value in invalid:
            with self.subTest(value=value):
                self.reject(value, Schema.SOURCE_READ)

    def test_answer_shapes_do_not_impute_missing_answers(self):
        rows = [[], [[1, 1.5, 'x', None, True]], [[0]*32 for _ in range(50)]]
        for value in rows:
            self.assertEqual(decode(json.dumps(value), schema=Schema.ROWS_ANSWER).value, value)
        for value in ([1], {'rows': [[1]]}, [[[1]]], [[{}]], [[0]*33], [[0]]*51):
            self.reject(value, Schema.ROWS_ANSWER)
        for value in ([], ['a', 'b']):
            self.assertEqual(decode(json.dumps(value), schema=Schema.STRINGS_ANSWER).value, value)
        for value in ([1], 'x', {'answer': ['x']}, [['x']], [None]):
            self.reject(value, Schema.STRINGS_ANSWER)


class TransportOutputBudgetTests(unittest.TestCase):
    def test_stdout_flood_is_stopped_at_limit_plus_one(self):
        code = 'import sys; sys.stdout.buffer.write(b"X" * 131072)'
        event, response = invoke([sys.executable, "-c", code], {}, timeout=3, limit=1024)
        self.assertEqual(event.get("status"), "oversized_output")
        self.assertEqual(event.get("error_type"), "OutputLimitExceeded")
        self.assertEqual(event.get("response_bytes_observed"), 1025)
        self.assertIs(event.get("response_complete"), False)
        self.assertIsNone(response)

    def test_small_json_worker_response_still_passes(self):
        code = 'import sys; sys.stdin.read(); print("{\\"ok\\": true}")'
        event, response = invoke([sys.executable, "-c", code], {}, timeout=3, limit=1024)
        self.assertEqual(event["status"], "ok")
        self.assertEqual(response, {"ok": True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
