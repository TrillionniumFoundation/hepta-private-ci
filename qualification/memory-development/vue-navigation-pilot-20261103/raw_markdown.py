"""Sanitized post-run derivative of a bounded raw-source extractor.

Standard library only. No rendering, input execution, fetching, or bundled corpus.
Source-locator mapping and parent identity formula are unchanged; citation
repository is parameterized. This file is not the original measured artifact.
"""
from dataclasses import dataclass
from itertools import islice
from types import MappingProxyType
from urllib.parse import quote, unquote, urlsplit
import hashlib
import re
import unicodedata

VERSION = 'rawMarkdown-v1'
MAX_FILES, MAX_BYTES, MAX_LINES, MAX_SECTIONS = 32, 131072, 8192, 1024
ANCHOR = r'[A-Za-z][A-Za-z0-9_.:-]*'


@dataclass(frozen=True)
class Entry:
    source: str
    path: str
    git_blob_sha1: str
    sha256: str = ''


@dataclass(frozen=True)
class Notice:
    line: int
    kind: str


@dataclass(frozen=True)
class Candidate:
    line: int
    column: int
    raw: str
    status: str
    reason: str = ''
    anchor: str = ''
    href: str = ''


@dataclass(frozen=True)
class Parent:
    id: str
    source: str
    path: str
    sha256: str
    start_line: int
    end_line: int
    title: str
    breadcrumb: tuple
    anchors: tuple
    text: str
    url: str
    citation: str
    candidates: tuple

    @property
    def links(self):
        return tuple(c for c in self.candidates if c.status == 'parseable')


@dataclass(frozen=True)
class Document:
    source: str
    path: str
    status: str
    reason: str = ''
    parents: tuple = ()
    warnings: tuple = ()
    links_extracted: bool = False


@dataclass(frozen=True)
class Resolution:
    status: str
    reason: str = ''
    target: str = ''
    mode: str = ''
    target_path: str = ''


class Unsupported(ValueError):
    pass


def git_blob_sha1(body):
    return hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()


def _unsafe(value, body=False):
    allowed = {'\n', '\r', '\t'} if body else set()
    return any(c not in allowed and (unicodedata.category(c) in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'}
               or (not body and c.isspace())) for c in value)


def _canonical(path):
    return (isinstance(path, str) and path.startswith('src/') and path.endswith('.md')
            and not _unsafe(path) and not re.search(r'[\\%:#?]', path)
            and all(p not in {'', '.', '..'} for p in path.split('/')))


def _balanced(line, start, opening, closing):
    depth, nested, escaped = 1, False, False
    i = start + 1
    while i < len(line):
        if line[i] == '\\':
            escaped = True
            i += 2
            continue
        if line[i] == opening:
            depth += 1
            nested = True
        elif line[i] == closing:
            depth -= 1
            if not depth:
                return i, nested, escaped
        i += 1
    return None, nested, escaped


def extract_line_candidates(line, number):
    """A bounded lexical scanner, not a Markdown AST. No state beyond this line."""
    out, warnings, i = [], [], 0
    while i < len(line):
        if line[i] == '`':
            run = re.match(r'`+', line[i:])[0]
            closing = next((m for m in re.finditer(r'`+', line[i + len(run):])
                            if len(m[0]) == len(run)), None)
            if closing is None:
                warnings.append(Notice(number, 'unclosed_inline_code'))
                break
            i += len(run) + closing.end()
            continue
        if line[i] != '[':
            i += 1
            continue
        start = i
        slash_count, k = 0, i - 1
        while k >= 0 and line[k] == '\\':
            slash_count += 1
            k -= 1
        escaped_open = slash_count % 2 == 1
        image = i > 0 and line[i - 1] == '!'
        close, nested_label, escaped_label = _balanced(line, i, '[', ']')
        reason, href, label = '', '', ''
        if close is None:
            end, reason = len(line), 'unclosed_bracket'
        else:
            label, end = line[i + 1:close], close + 1
            if end < len(line) and line[end] == '(':
                last, nested_target, escaped_target = _balanced(line, end, '(', ')')
                if last is None:
                    end, reason = len(line), 'unclosed_target'
                else:
                    href, end = line[end + 1:last], last + 1
                    if nested_label or nested_target or '[' in href or ']' in href:
                        reason = 'nested_syntax'
                    elif escaped_label or escaped_target or escaped_open:
                        reason = 'escaped_syntax'
                    elif not label or not href:
                        reason = 'empty_label_or_target'
                    elif _unsafe(href) or re.search(r'[{}<>`\\]', href):
                        reason = 'nonliteral_or_titled_target'
            elif end < len(line) and line[end] == '[':
                last, _, _ = _balanced(line, end, '[', ']')
                end = len(line) if last is None else last + 1
                reason = 'reference_link'
            elif end < len(line) and line[end] == ':':
                reason = 'reference_definition'
            else:
                reason = 'shortcut_or_nonlink_bracket'
        if image:
            reason = 'image'
        elif escaped_open:
            reason = 'escaped_syntax'
        out.append(Candidate(number, start + 1, line[start - int(image):end],
                             'unresolved' if reason else 'parseable', reason, label, href))
        i = end
    return tuple(out), tuple(warnings)


def _common_sections(entry, body):
    text = body.decode('utf-8', errors='strict')
    if _unsafe(text, body=True):
        raise Unsupported('control_character')
    if '\r' in text.replace('\r\n', ''):
        raise Unsupported('bare_cr')
    lines = text.splitlines(keepends=True)
    if len(lines) > MAX_LINES:
        raise Unsupported('line_budget')
    raw = [line.removesuffix('\n').removesuffix('\r') for line in lines]
    events, anchor_names, notices, outside = [], set(), [], []
    fence = None
    for i, line in enumerate(raw):
        if fence:
            closing = re.fullmatch(r' {0,3}(' + re.escape(fence[0]) + r'{3,})[ \t]*', line)
            if closing and len(closing[1]) >= fence[1]:
                fence = None
            continue
        opening = re.fullmatch(r' {0,3}(`{3,}|~{3,})(.*)', line)
        if opening and not (opening[1][0] == '`' and '`' in opening[2]):
            fence = (opening[1][0], len(opening[1]))
            continue
        outside.append(i)
        if re.search(r'<[A-Za-z/!?]|\{\{|\{%|^\s*(?:import\s|export\s|:::|\.\.\s+include::|!INCLUDE\b)', line):
            notices.append(Notice(i + 1, 'raw_dynamic_or_html_syntax'))
        if re.match(r'^(?: {4,}|\t)', line) and line.strip():
            notices.append(Notice(i + 1, 'raw_indentation_not_interpreted'))
        heading = re.fullmatch(r'(#{1,6})(?:[ \t]+(.*)|$)', line)
        if not heading:
            continue
        title = heading[2] if heading[2] is not None else ''
        anchor = ''
        attr = re.search(r'(?:^|[ \t])\{#(' + ANCHOR + r')\}[ \t]*$', title)
        if attr:
            anchor, title = attr[1], title[:attr.start()].rstrip(' \t')
            if anchor in anchor_names:
                raise Unsupported('duplicate_explicit_anchor')
            anchor_names.add(anchor)
        elif '{#' in title:
            notices.append(Notice(i + 1, 'unparsed_anchor_attribute'))
        events.append((i, len(heading[1]), title, anchor))
    if fence:
        raise Unsupported('unclosed_fence')
    if not text.strip():
        return lines, raw, (), tuple(notices), tuple(outside)
    if not events:
        events = [(0, 0, '', '')]
    elif events[0][0]:
        if any(line.strip() for line in raw[:events[0][0]]):
            events.insert(0, (0, 0, '', ''))
        else:
            events[0] = (0, *events[0][1:])
    if len(events) > MAX_SECTIONS:
        raise Unsupported('section_budget')
    return lines, raw, tuple(events), tuple(notices), tuple(outside)


class Parser:
    def __init__(self, entries, loader, *, commit, extract_links, repository="example/synthetic-docs"):
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid_citation_repository")
        self.repository = repository
        if not isinstance(extract_links, bool):
            raise ValueError('explicit_boolean_extract_links_required')
        if not re.fullmatch(r'[a-f0-9]{40}', commit):
            raise ValueError('invalid_commit')
        entries = tuple(islice(iter(entries), MAX_FILES + 1))
        if len(entries) > MAX_FILES:
            raise ValueError('manifest_budget')
        manifest = {}
        for entry in entries:
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', entry.source) or not _canonical(entry.path):
                raise ValueError('invalid_manifest_identity')
            if not re.fullmatch(r'[a-f0-9]{40}', entry.git_blob_sha1):
                raise ValueError('invalid_blob_pin')
            if entry.sha256 and not re.fullmatch(r'[a-f0-9]{64}', entry.sha256):
                raise ValueError('invalid_sha256_pin')
            key = (entry.source, entry.path)
            if key in manifest:
                raise ValueError('duplicate_manifest_key')
            manifest[key] = entry
        if len({e.source for e in entries}) > 1:
            raise ValueError('cross_source_manifest')
        self.manifest = MappingProxyType(manifest)
        self.commit, self.extract_links = commit, extract_links
        self._loader, self._cache = loader, {}
        self.load_count = self.bytes_loaded = self.lexical_scan_calls = self.graph_resolutions = 0

    def parse(self, source, path):
        key = (source, path)
        if key in self._cache:
            return self._cache[key]
        if key not in self.manifest:
            return Document(source, path, 'rejected', 'missing_manifest_target', links_extracted=self.extract_links)
        entry = self.manifest[key]
        try:
            self.load_count += 1
            body = self._loader(source, path)
            if not isinstance(body, bytes):
                raise TypeError('loader_must_return_bytes')
            self.bytes_loaded += len(body)
        except Exception as error:
            result = Document(source, path, 'rejected', 'loader_error:' + type(error).__name__, links_extracted=self.extract_links)
            self._cache[key] = result
            return result
        sha = hashlib.sha256(body).hexdigest()
        if len(body) > MAX_BYTES:
            result = Document(source, path, 'unsupported', 'byte_budget', links_extracted=self.extract_links)
        elif git_blob_sha1(body) != entry.git_blob_sha1 or (entry.sha256 and sha != entry.sha256):
            result = Document(source, path, 'rejected', 'pin_mismatch', links_extracted=self.extract_links)
        else:
            try:
                lines, raw, events, warnings, outside = _common_sections(entry, body)
            except (Unsupported, UnicodeDecodeError) as error:
                result = Document(source, path, 'unsupported', str(error) if isinstance(error, Unsupported) else 'invalid_utf8', links_extracted=self.extract_links)
            else:
                candidates, notices = [], list(warnings)
                if self.extract_links:
                    for index in outside:
                        self.lexical_scan_calls += 1
                        found, extra = extract_line_candidates(raw[index], index + 1)
                        candidates.extend(found)
                        notices.extend(extra)
                parents, stack = [], []
                url = f'https://github.com/{self.repository}/blob/{self.commit}/{quote(path, safe="/")}'
                for pos, (start, level, title, anchor) in enumerate(events):
                    end = events[pos + 1][0] if pos + 1 < len(events) else len(lines)
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    if level:
                        stack.append((level, title))
                    identity = '\0'.join((VERSION, source, self.commit, path, sha, f'{start + 1}:{end}'))
                    parents.append(Parent(hashlib.sha256(identity.encode()).hexdigest(), source, path, sha,
                        start + 1, end, title, tuple(t for _, t in stack), (anchor,) if anchor else (),
                        ''.join(lines[start:end]), url, f'{url}#L{start + 1}-L{end}',
                        tuple(c for c in candidates if start < c.line <= end)))
                result = Document(source, path, 'supported', parents=tuple(parents),
                                  warnings=tuple(notices), links_extracted=self.extract_links)
        self._cache[key] = result
        return result

    def _verify_parent(self, parent):
        doc = self._cache.get((parent.source, parent.path))
        if doc is None or parent not in doc.parents:
            raise ValueError('parent_not_from_this_parser')

    def resolve(self, parent, candidate):
        if not self.extract_links:
            raise RuntimeError('link_extraction_disabled')
        self._verify_parent(parent)
        if candidate not in parent.candidates:
            raise ValueError('candidate_not_from_parent')
        return self._resolve(parent, candidate, load=True)

    def _resolve(self, parent, candidate, load):
        self.graph_resolutions += 1
        if candidate.status != 'parseable':
            return Resolution('unresolved', 'syntax:' + candidate.reason)
        href = candidate.href
        if not href or _unsafe(href) or '\\' in href:
            return Resolution('unresolved', 'invalid_href')
        try:
            if re.search(r'%(?![a-fA-F0-9]{2})', href):
                return Resolution('unresolved', 'invalid_percent_encoding')
            url = urlsplit(href)
            if url.scheme or url.netloc or href.startswith('//'):
                return Resolution('unresolved', 'external_or_absolute_url')
            if '?' in href:
                return Resolution('unresolved', 'query')
            path, anchor = unquote(url.path, errors='strict'), unquote(url.fragment, errors='strict')
        except (UnicodeError, ValueError):
            return Resolution('unresolved', 'invalid_url')
        if _unsafe(path) or re.search(r'[%\\:#?]', path):
            return Resolution('unresolved', 'invalid_decoded_path')
        if path.startswith('//'):
            return Resolution('unresolved', 'external_or_absolute_url')
        if path and path.split('/')[-1] in {'', '.', '..'}:
            return Resolution('unresolved', 'directory_like_target')
        if anchor and not re.fullmatch(ANCHOR, anchor):
            return Resolution('unresolved', 'invalid_anchor')
        if not path:
            target_path = parent.path
        else:
            parts = ['src'] if path.startswith('/') else parent.path.split('/')[:-1]
            for piece in path.lstrip('/').split('/'):
                if piece in {'', '.'}:
                    continue
                if piece == '..':
                    if len(parts) <= 1:
                        return Resolution('unresolved', 'source_root_escape')
                    parts.pop()
                else:
                    parts.append(piece)
            leaf = parts[-1]
            if leaf.endswith('.html'):
                parts[-1] = leaf[:-5] + '.md'
            elif not leaf.endswith('.md'):
                if '.' not in leaf:
                    parts[-1] = leaf + '.md'
                else:
                    return Resolution('unresolved', 'unsupported_suffix')
            target_path = '/'.join(parts)
        key = (parent.source, target_path)
        if key not in self.manifest:
            return Resolution('unresolved', 'missing_manifest_target', target_path=target_path)
        if not load and key not in self._cache:
            return Resolution('unresolved', 'target_not_loaded', target_path=target_path)
        doc = self.parse(*key) if load else self._cache[key]
        if doc.status != 'supported':
            return Resolution('unresolved', 'target_' + doc.status + ':' + doc.reason, target_path=target_path)
        if anchor:
            target = next((p for p in doc.parents if anchor in p.anchors), None)
            mode = 'explicit_anchor'
        else:
            target = next((p for p in doc.parents if p.text.strip()), None)
            mode = 'document-root-first-parent'
        if target is None:
            return Resolution('unresolved', 'missing_anchor' if anchor else 'empty_target', target_path=target_path)
        return Resolution('resolved', target=target.id, mode=mode, target_path=target_path)

    def to_mechanics(self, parents):
        selected = {p.id: p for p in parents}
        docs, audit = {}, {}
        for ident, parent in sorted(selected.items()):
            self._verify_parent(parent)
            edges, outcomes = [], []
            if self.extract_links:
                for candidate in parent.candidates:
                    result = self._resolve(parent, candidate, load=False)
                    if result.status == 'resolved' and result.target not in selected:
                        result = Resolution('unresolved', 'target_parent_not_selected', target_path=result.target_path)
                    if result.status == 'resolved':
                        edges.append({'target': result.target, 'anchor': candidate.anchor})
                    outcomes.append({'line': candidate.line, 'column': candidate.column, 'raw': candidate.raw,
                                     'status': result.status, 'reason': result.reason, 'mode': result.mode,
                                     'target': result.target, 'target_path': result.target_path})
            docs[ident] = {'source': parent.source, 'url': parent.url, 'citation': parent.citation,
                           'title': parent.title, 'text': parent.text, 'links': edges}
            counts = None if not self.extract_links else {
                'candidates': len(parent.candidates),
                'parseable': sum(c.status == 'parseable' for c in parent.candidates),
                'syntax_unresolved': sum(c.status != 'parseable' for c in parent.candidates),
                'resolved': sum(o['status'] == 'resolved' for o in outcomes),
                'unresolved': sum(o['status'] != 'resolved' for o in outcomes)}
            audit[ident] = {'path': parent.path, 'source_sha256': parent.sha256,
                'start_line': parent.start_line, 'end_line': parent.end_line,
                'breadcrumb': parent.breadcrumb, 'explicit_anchors': parent.anchors,
                'links_extracted': self.extract_links, 'link_counts': counts, 'link_outcomes': outcomes}
        return docs, audit


def serialize_parent(document):
    return document['citation'] + '\n' + document['title'] + '\n' + document['text'] + '\n'


def pack_primary(order, documents):
    """Only four whole sections / 8192 UTF-8 bytes; no caller budget override."""
    selected, payloads, seen, used = [], [], set(), 0
    for ident in order:
        if ident in seen:
            continue
        seen.add(ident)
        payload = serialize_parent(documents[ident])
        size = len(payload.encode('utf-8'))
        if used + size > 8192:
            continue
        selected.append(ident)
        payloads.append(payload)
        used += size
        if len(selected) == 4:
            break
    return {'ids': selected, 'bytes': used, 'payloads': payloads}
