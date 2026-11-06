"""Boundary checks for model-generated data before invoking the existing tools."""
import unittest
from .prompts import legal_payload, parse, prompt


class PublicBoundaryTests(unittest.TestCase):
    def test_exact_json_has_no_repair(self):
        self.assertEqual(parse(' [[1]] '), [[1]])
        for text in ('```json\n[[1]]\n```', 'answer: [[1]]', '[NaN]', '{"a":1,"a":2}', None):
            with self.assertRaises(ValueError):
                parse(text)

    def test_sql_payload_cannot_select_another_tool(self):
        task = {'family': 'sqlite_query'}
        self.assertTrue(legal_payload(task, {'query': 'SELECT 1'}))
        for value in ({'needle': 'hello'}, {'query': 'SELECT 1', 'path': '/tmp/other'}, {'query': True}, []):
            self.assertFalse(legal_payload(task, value))

    def test_source_window_has_strict_types_and_caps(self):
        task = {'family': 'source_inspection'}
        self.assertTrue(legal_payload(task, {'start_line': 1, 'line_count': 120}))
        for value in ({'start_line': True, 'line_count': 1}, {'start_line': 1, 'line_count': 121},
                      {'needle': ''}, {'needle': 'x', 'path': '/tmp/other'}):
            self.assertFalse(legal_payload(task, value))

    def test_private_oracle_fields_do_not_enter_prompts(self):
        task = {'family': 'sqlite_query', 'question': 'Count rows.', 'answer_format': 'JSON array',
                'expected': 'SECRET_EXPECTED_SENTINEL', 'oracle_payload': 'SECRET_ACTION_SENTINEL'}
        for stage in ('plan', 'direct', 'answer'):
            text = prompt(task, stage)
            self.assertNotIn('SECRET_', text)
            self.assertIn('Count rows.', text)


if __name__ == '__main__':
    unittest.main()
