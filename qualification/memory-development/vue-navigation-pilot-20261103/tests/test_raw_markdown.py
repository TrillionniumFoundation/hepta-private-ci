"""Self-contained synthetic parser tests; no real corpus or historical fixture pins."""
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
import hashlib
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import raw_markdown as rm

def make_parser(bodies, mode=True, *, commit=("0" * 40)):
    bodies = {k: v.encode() if isinstance(v, str) else v for k, v in bodies.items()}
    calls = []
    entries = [rm.Entry(source, path, rm.git_blob_sha1(body), hashlib.sha256(body).hexdigest())
               for (source, path), body in bodies.items()]
    def loader(source, path):
        calls.append((source, path))
        return bodies[(source, path)]
    return rm.Parser(entries, loader, commit=commit, extract_links=mode), calls

def shared_fields(parent):
    return (parent.id, parent.source, parent.path, parent.sha256, parent.start_line, parent.end_line,
            parent.title, parent.breadcrumb, parent.anchors, parent.text, parent.url, parent.citation)

class RawMarkdownTests(unittest.TestCase):
    def test_flag_is_required_and_boolean(self):
            with self.assertRaises(TypeError):
                rm.Parser([], lambda *_: b'', commit=("0" * 40))
            with self.assertRaises(ValueError):
                rm.Parser([], lambda *_: b'', commit=("0" * 40), extract_links='false')

    def test_column_zero_atx_only(self):
            body = '# A {#a}\n\n > # Quote\n  # Indented\n- # Nested\n####### Seven\nSetext\n======\n#\n'
            p, _ = make_parser({('toy', 'src/a.md'): body})
            d = p.parse('toy', 'src/a.md')
            self.assertEqual(d.status, 'supported')
            self.assertEqual([q.title for q in d.parents], ['A', ''])
            self.assertEqual(''.join(q.text for q in d.parents), body)

    def test_lexical_unresolved_counts_and_no_nested_mining(self):
            line = '[good](a.md) [ref][key] ![image](x.png) [outer [inner](a.md)](b.md) [title](a.md "x") [short]'
            found, warnings = rm.extract_line_candidates(line, 7)
            self.assertEqual(len(found), 6)
            self.assertEqual([c.status for c in found], ['parseable'] + ['unresolved'] * 5)
            self.assertEqual([c.reason for c in found[1:]], ['reference_link', 'image', 'nested_syntax',
                                                           'nonliteral_or_titled_target', 'shortcut_or_nonlink_bracket'])
            self.assertEqual(warnings, ())
            self.assertTrue(all(c.line == 7 for c in found))

    def test_bracketed_target_is_unresolved_not_nested_link(self):
            for text in ['[outer]([inner])', '[a](b[0].md)', '[a]([b](c.md))']:
                with self.subTest(text=text):
                    found, _ = rm.extract_line_candidates(text, 1)
                    self.assertEqual(len(found), 1)
                    self.assertEqual((found[0].status, found[0].reason), ('unresolved', 'nested_syntax'))

    def test_unclosed_inline_masks_restline_and_reports(self):
            found, warnings = rm.extract_line_candidates('[yes](a.md) ` unclosed [no](b.md)', 2)
            self.assertEqual([c.href for c in found], ['a.md'])
            self.assertEqual(warnings[0].kind, 'unclosed_inline_code')
            found, _ = rm.extract_line_candidates('\\[no](a.md) [broken](nested(x))', 3)
            self.assertEqual([c.reason for c in found], ['escaped_syntax', 'nested_syntax'])

    def _resolve_one(self, href, extra=None):
            data = {('toy', 'src/guide/a.md'): '# A {#a}\n\n[x](' + href + ')\n'}
            data.update(extra or {})
            p, calls = make_parser(data)
            q = p.parse('toy', 'src/guide/a.md').parents[0]
            return p, calls, q, p.resolve(q, q.candidates[0])

    def test_mapping_rejections_never_load_targets(self):
            targets = ['https://vuejs.org/guide/a.html', '//vuejs.org/a', '/api/', '/api/.', '/api/x/..',
                       '/api/%2e', '/api/x/%2e%2e', '%2f%2fevil/a', '../../../a', '%252e%252e/a',
                       '/api/a?x=1', '/api/a?', '/api/a.md#missing', '/api/a.js', '/api/index',
                       '/api/a%00.md', '/api/a%3f.md', '/api/a%23.md', '/api/a%5c.md', '/api/%ZZ',
                       'file:///api/a', '/api/a.html/', '/api/a.html/.', '/api/a.html/x/..']
            for href in targets:
                with self.subTest(href=href):
                    _, calls, _, result = self._resolve_one(href)
                    self.assertEqual(result.status, 'unresolved')
                    self.assertEqual(calls, [('toy', 'src/guide/a.md')])

    def test_unicode_path_and_encoded_controls_rejected(self):
            for char in ['\u0080', '\u0085', '\u009f', '\u2028', '\u2029', '\u202e', '\u00a0']:
                with self.subTest(codepoint=ord(char)):
                    with self.assertRaises(ValueError):
                        make_parser({('toy', 'src/b' + char + '.md'): '# B\n'})
                    _, calls, _, result = self._resolve_one('/api/b' + quote(char) + '.md')
                    self.assertEqual(result.reason, 'invalid_decoded_path')
                    self.assertEqual(len(calls), 1)

    def test_source_and_parent_provenance(self):
            with self.assertRaises(ValueError):
                make_parser({('one', 'src/a.md'): '# A\n', ('two', 'src/b.md'): '# B\n'})
            p, _, q, _ = self._resolve_one('#a')
            with self.assertRaises(ValueError):
                p.resolve(replace(q, source='other'), q.candidates[0])
            with self.assertRaises(ValueError):
                p.to_mechanics([replace(q, path='src/other.md')])

    def test_no_case_fallback_or_implicit_anchor(self):
            extra = {('toy', 'src/api/B.md'): '# Natural Title {#Top}\n'}
            for href, status in [('/api/B.html#Top', 'resolved'), ('/api/b.html#Top', 'unresolved'),
                                 ('/api/B.html#top', 'unresolved'), ('/api/B.html#natural-title', 'unresolved')]:
                with self.subTest(href=href):
                    _, _, _, result = self._resolve_one(href, extra)
                    self.assertEqual(result.status, status)

    def test_empty_preamble_first_nonempty_and_no_final_newline(self):
            for body, count in [('', 0), ('\n\n', 0), ('\n# A\nText', 1), ('Preamble\n\n# A\nText', 2)]:
                with self.subTest(body=body):
                    p, _ = make_parser({('toy', 'src/a.md'): body})
                    d = p.parse('toy', 'src/a.md')
                    self.assertEqual(len(d.parents), count)
                    if count: self.assertEqual(''.join(q.text for q in d.parents), body)

    def test_deterministic_ids_and_commit_snapshot(self):
            body = '# A {#a}\n\nText.\n'
            p, _ = make_parser({('toy', 'src/a.md'): body})
            q = p.parse('toy', 'src/a.md').parents[0]
            other, _ = make_parser({('toy', 'src/a.md'): body})
            self.assertEqual(q, other.parse('toy', 'src/a.md').parents[0])
            for data, commit in [(body + '\n', ("0" * 40)), (body, 'a' * 40)]:
                other, _ = make_parser({('toy', 'src/a.md'): data}, commit=commit)
                self.assertNotEqual(q.id, other.parse('toy', 'src/a.md').parents[0].id)

    def test_pins_failures_cached_and_invalid_utf8(self):
            for mode in (False, True):
                p = rm.Parser([rm.Entry('toy', 'src/a.md', '0' * 40)], lambda *_: b'toy',
                              commit=("0" * 40), extract_links=mode)
                self.assertEqual(p.parse('toy', 'src/a.md').reason, 'pin_mismatch')
                p.parse('toy', 'src/a.md'); self.assertEqual(p.load_count, 1)
                p, _ = make_parser({('toy', 'src/a.md'): b'\xff'}, mode)
                self.assertEqual(p.parse('toy', 'src/a.md').reason, 'invalid_utf8')

    def test_input_limits_modes_equal_and_manifest_bounded(self):
            for body, reason in [('x' * (rm.MAX_BYTES + 1), 'byte_budget'), ('\n' * (rm.MAX_LINES + 1), 'line_budget'),
                                 ('# A\n' * (rm.MAX_SECTIONS + 1), 'section_budget')]:
                for mode in (False, True):
                    with self.subTest(reason=reason, mode=mode):
                        p, _ = make_parser({('toy', 'src/a.md'): body}, mode)
                        d = p.parse('toy', 'src/a.md')
                        self.assertEqual((d.reason, d.parents), (reason, ()))
            consumed = []
            def infinite():
                i = 0
                while True:
                    consumed.append(i)
                    yield rm.Entry('toy', 'src/' + str(i) + '.md', '0' * 40)
                    i += 1
            with self.assertRaises(ValueError):
                rm.Parser(infinite(), lambda *_: b'', commit=("0" * 40), extract_links=False)
            self.assertEqual(len(consumed), 33)
            with self.assertRaises(ValueError):
                make_parser({('toy', 'src/a.mdx'): '<A />'})

    def test_exact_8192_and_one_byte_over(self):
            doc = {'citation': 'c', 'title': 't', 'text': ''}
            overhead = len(rm.serialize_parent(doc).encode())
            doc['text'] = 'x' * (8192 - overhead)
            self.assertEqual(rm.pack_primary(['a'], {'a': doc})['bytes'], 8192)
            doc['text'] += 'x'
            self.assertEqual(rm.pack_primary(['a'], {'a': doc})['ids'], [])

