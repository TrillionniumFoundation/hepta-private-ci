"""Rebuild the authored task fixtures deterministically; never invokes a model.

Run only while preparing/reviewing the pack, before the registration is frozen.
All source strings and expected observations are authored here. No external
repository, network, host file, model output, or prior evaluation is consumed.
"""

import hashlib
import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parent


def source(text):
    return textwrap.dedent(text).lstrip("\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


COMMON = """Repair the library in repair_target.py to meet the specification below.
Keep the public names and call signatures. Use only Python 3.12's standard
library. Do not access the network, install dependencies, read outside this
workspace, or emit stdout/stderr from library calls. You may create your own
checks in the workspace; the submitted artifact is repair_target.py. Do not
change TASK.md. All evaluation inputs are bounded small in-memory values or
files in a temporary directory provided to the library. No production service
or external repository is involved. Explain the change and any checks you ran.

"""


TASKS = []


def add(slug, family, title, spec, initial, reference, cases):
    prompt = COMMON + spec.strip() + "\n"
    initial = source(initial)
    reference = source(reference)
    public_hash = sha(canonical({"repair_target.py": initial, "TASK.md": prompt}))
    task_id = f"{slug}.v1.{public_hash[:12]}"
    records = []
    for number, (label, payload, expected) in enumerate(cases, 1):
        input_hash = sha(canonical(payload))
        records.append({"case_id": f"{slug}-{number:02d}-{input_hash[:10]}",
                        "label": label, "input": payload,
                        "input_sha256": input_hash, "expected": expected})
    public = ROOT / "tasks" / slug
    private = ROOT / "private" / slug
    public.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    (public / "repair_target.py").write_text(initial, encoding="utf-8")
    (public / "TASK.md").write_text(prompt, encoding="utf-8")
    (private / "reference.py").write_text(reference, encoding="utf-8")
    tests = {"schema": "hepta.native-ab.hidden-cases.v1", "task_id": task_id,
             "slug": slug, "cases": records}
    (private / "cases.json").write_bytes(canonical(tests) + b"\n")
    TASKS.append({"task_id": task_id, "slug": slug, "family_id": family,
                  "title": title, "public_bundle_sha256": public_hash,
                  "initial_source_sha256": sha(initial.encode()),
                  "task_text_sha256": sha(prompt.encode()),
                  "reference_sha256": sha(reference.encode()),
                  "hidden_cases_sha256": sha(canonical(tests) + b"\n"),
                  "case_count": len(records),
                  "agent_visible_files": ["repair_target.py", "TASK.md"],
                  "allowed_submission_files": ["repair_target.py"]})


add("stream_frames", "authored.incremental-parsers.20261024", "Chunked binary frames", """
ByteFramer(max_payload=1024) parses concatenated frames. Each frame consists of
a two-byte unsigned big-endian payload length followed by exactly that many
bytes. max_payload is an integer in [0, 65535]. Empty frames are valid.

feed(chunk: bytes) returns a list of complete payload bytes in stream order.
Chunk boundaries may occur anywhere, including inside a header or payload.
Keep incomplete bytes for the next feed; empty chunks have no special meaning.
Reject a declared length above max_payload with ValueError as soon as its whole
header is available. After such a rejection no further operation is required.
finish() returns None if no incomplete frame remains, otherwise raises
ValueError. No further calls are required after finish().
""", '''
class ByteFramer:
    def __init__(self, max_payload=1024):
        if type(max_payload) is not int or not 0 <= max_payload <= 65535:
            raise ValueError("invalid maximum")
        self.max_payload = max_payload
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        result = []
        while len(self.buffer) >= 2:
            size = int.from_bytes(self.buffer[:2], "big")
            if size > self.max_payload:
                raise ValueError("frame too large")
            del self.buffer[:2]
            if len(self.buffer) < size:
                break
            if size:
                result.append(bytes(self.buffer[:size]))
            del self.buffer[:size]
        return result

    def finish(self):
        if self.buffer:
            raise ValueError("truncated frame")
''', '''
class ByteFramer:
    def __init__(self, max_payload=1024):
        if type(max_payload) is not int or not 0 <= max_payload <= 65535:
            raise ValueError("invalid maximum")
        self.max_payload = max_payload
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        result = []
        while len(self.buffer) >= 2:
            size = int.from_bytes(self.buffer[:2], "big")
            if size > self.max_payload:
                raise ValueError("frame too large")
            if len(self.buffer) < size + 2:
                break
            result.append(bytes(self.buffer[2:2 + size]))
            del self.buffer[:2 + size]
        return result

    def finish(self):
        if self.buffer:
            raise ValueError("truncated frame")
''', [
    ("complete_frames", {"max_payload": 8, "chunks": ["00026162000163"], "finish": True},
     {"feeds": [["6162", "63"]], "finish": None}),
    ("header_and_body_split", {"max_payload": 8, "chunks": ["00", "0361", "62", "63"], "finish": True},
     {"feeds": [[], [], [], ["616263"]], "finish": None}),
    ("empty_and_binary_frames", {"max_payload": 8, "chunks": ["0000000200ff0000"], "finish": True},
     {"feeds": [["", "00ff", ""]], "finish": None}),
    ("complete_then_partial", {"max_payload": 8, "chunks": ["000161000262", "63"], "finish": True},
     {"feeds": [["61"], ["6263"]], "finish": None}),
    ("declared_but_missing_body", {"max_payload": 8, "chunks": ["0002"], "finish": True},
     {"feeds": [[]], "finish": {"error": "ValueError"}}),
    ("incomplete_header", {"max_payload": 8, "chunks": ["00"], "finish": True},
     {"feeds": [[]], "finish": {"error": "ValueError"}}),
    ("oversize_detected_after_header", {"max_payload": 2, "chunks": ["00", "03"], "finish": False},
     {"feeds": [[], {"error": "ValueError"}]}),
    ("zero_limit_empty_chunks", {"max_payload": 0, "chunks": ["", "00", "00", ""], "finish": True},
     {"feeds": [[], [], [""], []], "finish": None}),
])


add("stream_lines", "authored.incremental-parsers.20261024", "Incremental UTF-8 lines", """
Utf8Lines() accepts a stream of UTF-8 bytes. feed(chunk: bytes) returns complete
text records terminated by LF. A CR immediately preceding that LF is part of
the line ending and is removed; other CR and all spaces/tabs are preserved.
Return an empty string for an empty terminated line. Arbitrary byte boundaries,
including inside a multibyte UTF-8 character or between CR and LF, are valid.

finish() validates any remaining UTF-8 sequence and returns the final
unterminated record if nonempty, otherwise []. A trailing CR on an unterminated
record is data. Invalid UTF-8 raises UnicodeError (including incomplete UTF-8
at finish). Calls to either method after a successful finish raise ValueError.
""", '''
class Utf8Lines:
    def __init__(self):
        self.pending = ""

    def feed(self, chunk):
        self.pending += chunk.decode("utf-8")
        parts = self.pending.split("\\n")
        self.pending = parts.pop()
        return [part.strip() for part in parts]

    def finish(self):
        last = self.pending.strip()
        self.pending = ""
        return [last] if last else []
''', '''
import codecs


class Utf8Lines:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.pending = ""
        self.closed = False

    def feed(self, chunk):
        if self.closed:
            raise ValueError("already finished")
        self.pending += self.decoder.decode(chunk, final=False)
        parts = self.pending.split("\\n")
        self.pending = parts.pop()
        return [part[:-1] if part.endswith("\\r") else part for part in parts]

    def finish(self):
        if self.closed:
            raise ValueError("already finished")
        self.pending += self.decoder.decode(b"", final=True)
        self.closed = True
        last = self.pending
        self.pending = ""
        return [last] if last else []
''', [
    ("ordinary_lines", {"chunks": ["610a620a"], "finish": True}, {"feeds": [["a", "b"]], "finish": []}),
    ("preserve_whitespace", {"chunks": ["202061200a092062090d0a"], "finish": True},
     {"feeds": [["  a ", "\t b\t"]], "finish": []}),
    ("utf8_boundary", {"chunks": ["e4", "b8ad0af0", "9f", "99820a"], "finish": True},
     {"feeds": [[], ["中"], [], ["🙂"]], "finish": []}),
    ("crlf_boundary_and_literal_cr", {"chunks": ["610d", "0a620d63", "0a"], "finish": True},
     {"feeds": [[], ["a"], ["b\rc"]], "finish": []}),
    ("empty_records_and_tail", {"chunks": ["0a0a207461696c200d"], "finish": True},
     {"feeds": [["", ""]], "finish": [" tail \r"]}),
    ("invalid_utf8", {"chunks": ["ff"], "finish": False}, {"feeds": [{"error": "UnicodeError"}]}),
    ("truncated_utf8", {"chunks": ["e282"], "finish": True},
     {"feeds": [[]], "finish": {"error": "UnicodeError"}}),
    ("finished_state", {"chunks": [""], "finish": True, "after_finish": True},
     {"feeds": [[]], "finish": [], "after_feed": {"error": "ValueError"}, "after_finish": {"error": "ValueError"}}),
])


add("state_schedule", "authored.temporal-state.20261024", "Reschedulable deadline queue", """
ScheduleQueue has schedule(key, value, deadline), cancel(key), and pop_due(now).
Keys are nonempty strings; deadlines and now are nonnegative integers. Calls
in this task use valid argument types. There is at most one live event per key.
Scheduling an existing key replaces it and creates a fresh insertion order.
cancel returns True only if a live event was removed. pop_due returns a list
of (key, value) tuples for all current events with deadline <= now, ordered by
deadline then the insertion order of their latest schedule call. Remove each
returned event. Stale heap entries from replacement or cancellation must never
fire or remove a newer event. Payload values may be any JSON value.
""", '''
import heapq


class ScheduleQueue:
    def __init__(self):
        self.heap = []
        self.pending = {}

    def schedule(self, key, value, deadline):
        self.pending[key] = value
        heapq.heappush(self.heap, (deadline, key))

    def cancel(self, key):
        if key in self.pending:
            del self.pending[key]
            return True
        return False

    def pop_due(self, now):
        result = []
        while self.heap and self.heap[0][0] <= now:
            _, key = heapq.heappop(self.heap)
            if key in self.pending:
                result.append((key, self.pending.pop(key)))
        return result
''', '''
import heapq


class ScheduleQueue:
    def __init__(self):
        self.heap = []
        self.pending = {}
        self.order = 0

    def schedule(self, key, value, deadline):
        self.order += 1
        event = (deadline, self.order, value)
        self.pending[key] = event
        heapq.heappush(self.heap, (deadline, self.order, key))

    def cancel(self, key):
        if key in self.pending:
            del self.pending[key]
            return True
        return False

    def pop_due(self, now):
        result = []
        while self.heap and self.heap[0][0] <= now:
            deadline, order, key = heapq.heappop(self.heap)
            current = self.pending.get(key)
            if current is not None and current[:2] == (deadline, order):
                del self.pending[key]
                result.append((key, current[2]))
        return result
''', [
    ("ordinary_schedule", {"ops": [["schedule", "a", 1, 4], ["pop_due", 3], ["pop_due", 4], ["pop_due", 9]]},
     [None, [], [["a", 1]], []]),
    ("stable_equal_deadlines", {"ops": [["schedule", "z", 0, 2], ["schedule", "a", False, 2], ["schedule", "m", None, 2], ["pop_due", 2]]},
     [None, None, None, [["z", 0], ["a", False], ["m", None]]]),
    ("replacement_later", {"ops": [["schedule", "a", "old", 1], ["schedule", "a", "new", 9], ["pop_due", 1], ["pop_due", 9]]},
     [None, None, [], [["a", "new"]]]),
    ("replacement_earlier", {"ops": [["schedule", "a", "old", 9], ["schedule", "a", "new", 1], ["pop_due", 1], ["pop_due", 9]]},
     [None, None, [["a", "new"]], []]),
    ("cancel_reuse_key", {"ops": [["schedule", "x", 1, 1], ["cancel", "x"], ["cancel", "x"], ["schedule", "x", 2, 3], ["pop_due", 1], ["pop_due", 3]]},
     [None, True, False, None, [], [["x", 2]]]),
    ("replacement_has_fresh_order", {"ops": [["schedule", "z", 1, 5], ["schedule", "a", 2, 5], ["schedule", "z", 3, 5], ["pop_due", 5]]},
     [None, None, None, [["a", 2], ["z", 3]]]),
    ("mixed_deadlines", {"ops": [["schedule", "b", [1], 8], ["schedule", "a", {"ok": True}, 0], ["pop_due", 0], ["cancel", "absent"], ["pop_due", 7], ["pop_due", 8]]},
     [None, None, [["a", {"ok": True}]], False, [], [["b", [1]]]]),
])


add("state_window", "authored.temporal-state.20261024", "Sliding-window admission", """
WindowLimiter(capacity, window) has allow(key, now) -> bool. capacity and window
must be positive integers (bool is not an integer for this API), otherwise the
constructor raises ValueError. key is a nonempty string, now a nonnegative
integer; allow calls in this task use those valid types. The time supplied
across all keys of an instance must never decrease; a decrease raises
ValueError without changing its state.

At time now, admit iff fewer than capacity previously admitted calls for this
key lie in (now - window, now]. Calls exactly window old have expired. A denied
call must not consume capacity or delay later admission. Keys are independent,
apart from the single nondecreasing supplied clock. Do not read the wall clock.
""", '''
from collections import deque


class WindowLimiter:
    def __init__(self, capacity, window):
        if type(capacity) is not int or capacity <= 0 or type(window) is not int or window <= 0:
            raise ValueError("invalid limits")
        self.capacity = capacity
        self.window = window
        self.events = {}
        self.last_now = None

    def allow(self, key, now):
        if self.last_now is not None and now < self.last_now:
            raise ValueError("time decreased")
        self.last_now = now
        queue = self.events.setdefault(key, deque())
        while queue and queue[0] < now - self.window:
            queue.popleft()
        queue.append(now)
        return len(queue) <= self.capacity
''', '''
from collections import deque


class WindowLimiter:
    def __init__(self, capacity, window):
        if type(capacity) is not int or capacity <= 0 or type(window) is not int or window <= 0:
            raise ValueError("invalid limits")
        self.capacity = capacity
        self.window = window
        self.events = {}
        self.last_now = None

    def allow(self, key, now):
        if self.last_now is not None and now < self.last_now:
            raise ValueError("time decreased")
        self.last_now = now
        queue = self.events.setdefault(key, deque())
        while queue and queue[0] <= now - self.window:
            queue.popleft()
        if len(queue) >= self.capacity:
            return False
        queue.append(now)
        return True
''', [
    ("ordinary_capacity", {"capacity": 2, "window": 10, "ops": [["a", 0], ["a", 1], ["a", 2]]}, [True, True, False]),
    ("exact_boundary", {"capacity": 1, "window": 10, "ops": [["a", 0], ["a", 10]]}, [True, True]),
    ("denials_do_not_accumulate", {"capacity": 2, "window": 10, "ops": [["a", 0], ["a", 2], ["a", 5], ["a", 6], ["a", 11], ["a", 12]]},
     [True, True, False, False, True, True]),
    ("independent_keys", {"capacity": 1, "window": 4, "ops": [["a", 0], ["b", 0], ["a", 1], ["b", 4], ["a", 4]]},
     [True, True, False, True, True]),
    ("decrease_leaves_state", {"capacity": 1, "window": 5, "ops": [["a", 10], ["b", 9], ["b", 10], ["a", 15]]},
     [True, {"error": "ValueError"}, True, True]),
    ("repeated_timestamp", {"capacity": 2, "window": 1, "ops": [["a", 0], ["a", 0], ["a", 0], ["a", 1], ["a", 1]]},
     [True, True, False, True, True]),
    ("invalid_capacity", {"capacity": True, "window": 1, "ops": []}, {"error": "ValueError"}),
    ("invalid_window", {"capacity": 1, "window": 0, "ops": []}, {"error": "ValueError"}),
])


add("transform_overlay", "authored.immutable-transforms.20261024", "Immutable recursive overlay", """
The module exports the unique sentinel DELETE and merge(base: dict,
override: dict) -> dict. Recursively merge dictionaries. Any override value
equal by identity to DELETE removes that key, even if it was absent. Other
values, including None, False, 0, empty strings, and empty lists, are ordinary
values and replace the old value. Lists replace rather than concatenate.
When an override dictionary replaces a non-dictionary, treat the old value as
an empty dictionary so nested DELETE entries still disappear.

Never mutate either input. The returned dictionary, including all nested
dictionaries and lists, must share no mutable container with either input.
Inputs contain JSON-like dict/list/scalar values with string keys. DELETE may
occur only as a dictionary value within override, never inside a list or base.
The grader may mutate the returned result after merge and verify the inputs
are unchanged.
""", '''
DELETE = object()


def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if value is DELETE:
            result.pop(key, None)
        elif not value:
            continue
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result
''', '''
from copy import deepcopy

DELETE = object()


def merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if value is DELETE:
            result.pop(key, None)
        elif isinstance(value, dict):
            old = result.get(key)
            result[key] = merge(old if isinstance(old, dict) else {}, value)
        else:
            result[key] = deepcopy(value)
    return result
''', [
    ("ordinary_replace", {"base": {"x": 1}, "override": {"x": 2, "y": "a"}},
     {"result": {"x": 2, "y": "a"}, "inputs_unchanged": True, "no_mutable_aliases": True}),
    ("falsy_values", {"base": {"a": 1, "b": True, "c": "x", "d": [1], "e": 9}, "override": {"a": 0, "b": False, "c": "", "d": [], "e": None}},
     {"result": {"a": 0, "b": False, "c": "", "d": [], "e": None}, "inputs_unchanged": True, "no_mutable_aliases": True}),
    ("recursive_delete", {"base": {"a": {"x": 1, "y": 2}, "b": 3}, "override": {"a": {"x": {"$delete": True}, "z": 4}, "b": {"$delete": True}, "missing": {"$delete": True}}},
     {"result": {"a": {"y": 2, "z": 4}}, "inputs_unchanged": True, "no_mutable_aliases": True}),
    ("dictionary_replaces_scalar", {"base": {"a": 8}, "override": {"a": {"x": {"$delete": True}, "y": [1]}}},
     {"result": {"a": {"y": [1]}}, "inputs_unchanged": True, "no_mutable_aliases": True}),
    ("preserved_base_detached", {"base": {"a": {"b": [1, {"c": 2}]}}, "override": {}},
     {"result": {"a": {"b": [1, {"c": 2}]}}, "inputs_unchanged": True, "no_mutable_aliases": True}),
    ("replacement_list_detached", {"base": {"a": [1]}, "override": {"a": [{"x": [2]}]}},
     {"result": {"a": [{"x": [2]}]}, "inputs_unchanged": True, "no_mutable_aliases": True}),
    ("nested_empty_mapping", {"base": {"a": {"x": 1}}, "override": {"a": {}, "b": {}}},
     {"result": {"a": {"x": 1}, "b": {}}, "inputs_unchanged": True, "no_mutable_aliases": True}),
])


add("transform_intervals", "authored.immutable-transforms.20261024", "Canonical interval union", """
normalize(intervals) returns the union of half-open integer intervals [start,
end) as a sorted list of (start, end) tuples. Overlapping OR touching intervals
coalesce. Drop empty intervals where start == end. Reject start > end with
ValueError. Do not mutate the input list or any input pair. Accept any finite
iterable of two-item tuple/list pairs of valid integers; negative endpoints are
valid. The output must be canonical, nonempty per interval, and non-touching.
""", '''
def normalize(intervals):
    intervals.sort()
    result = []
    for start, end in intervals:
        if start > end:
            raise ValueError("reversed interval")
        if start == end:
            continue
        if result and start < result[-1][1]:
            result[-1] = (result[-1][0], end)
        else:
            result.append((start, end))
    return result
''', '''
def normalize(intervals):
    pairs = []
    for start, end in intervals:
        if start > end:
            raise ValueError("reversed interval")
        if start != end:
            pairs.append((start, end))
    pairs.sort()
    result = []
    for start, end in pairs:
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result
''', [
    ("ordinary_disjoint", {"intervals": [[1, 2], [5, 9]]},
     {"result": [[1, 2], [5, 9]], "list_of_tuples": True, "input_unchanged": True}),
    ("touching_chain", {"intervals": [[1, 3], [3, 5], [5, 8]]},
     {"result": [[1, 8]], "list_of_tuples": True, "input_unchanged": True}),
    ("nested_must_not_shrink", {"intervals": [[0, 10], [2, 3], [7, 12]]},
     {"result": [[0, 12]], "list_of_tuples": True, "input_unchanged": True}),
    ("unsorted_not_mutated", {"intervals": [[5, 7], [-3, 0], [0, 6], [9, 9]]},
     {"result": [[-3, 7]], "list_of_tuples": True, "input_unchanged": True}),
    ("empty", {"intervals": []}, {"result": [], "list_of_tuples": True, "input_unchanged": True}),
    ("generator_input", {"intervals": [[3, 4], [0, 3]], "as_generator": True},
     {"result": [[0, 4]], "list_of_tuples": True, "input_unchanged": True}),
    ("invalid_interval", {"intervals": [[1, 4], [8, 2]]}, {"error": "ValueError"}),
    ("duplicates_and_empty", {"intervals": [[1, 4], [1, 4], [2, 2], [4, 4]]},
     {"result": [[1, 4]], "list_of_tuples": True, "input_unchanged": True}),
])


add("durable_store", "authored.local-durable-formats.20261024", "Atomic JSON compare-and-swap", """
JsonStore(path) stores a JSON object with exactly "revision" and "value" fields.
The parent directory already exists. load() returns (0, None) when the file
does not exist, otherwise (revision, value). A stored revision must be a
positive integer, not bool; malformed JSON or schema raises ValueError.

commit(value, expected_revision) performs a single-process compare-and-swap:
load the current record, raise ConflictError on a mismatch without changing
any bytes, otherwise atomically replace the file with revision+1 and the given
JSON value and return the new revision. Use a same-directory temporary file
and os.replace. If serialization, writing, or os.replace fails, preserve the
old committed file and remove the temporary file. The grader injects an
OSError at os.replace to exercise this documented failure boundary. It does
not test concurrent writers, power-loss durability, symlink attacks, or
outside-directory access. Only this path and its same-directory temporary
files may be touched. Preserve the public ConflictError exception class.
""", '''
import json
import os
from pathlib import Path


class ConflictError(Exception):
    pass


class JsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return 0, None
        record = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or set(record) != {"revision", "value"}
                or type(record["revision"]) is not int or record["revision"] < 1):
            raise ValueError("invalid record")
        return record["revision"], record["value"]

    def commit(self, value, expected_revision):
        revision, _ = self.load()
        record = {"revision": revision + 1, "value": value}
        self.path.write_text(json.dumps(record), encoding="utf-8")
        if revision != expected_revision:
            raise ConflictError("revision conflict")
        return revision + 1
''', '''
import json
import os
from pathlib import Path
import tempfile


class ConflictError(Exception):
    pass


class JsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return 0, None
        record = json.loads(raw)
        if (not isinstance(record, dict) or set(record) != {"revision", "value"}
                or type(record["revision"]) is not int or record["revision"] < 1):
            raise ValueError("invalid record")
        return record["revision"], record["value"]

    def commit(self, value, expected_revision):
        revision, _ = self.load()
        if revision != expected_revision:
            raise ConflictError("revision conflict")
        payload = json.dumps({"revision": revision + 1, "value": value})
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".jsonstore-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        return revision + 1
''', [
    ("initial_and_commit", {"ops": [["load"], ["commit", {"x": 1}, 0], ["load"]]},
     [[0, None], 1, [1, {"x": 1}]]),
    ("stale_revision_no_write", {"ops": [["commit", "old", 0], ["snapshot"], ["commit", "bad", 0], ["matches_snapshot"], ["load"], ["files"]]},
     [1, True, {"error": "ConflictError"}, True, [1, "old"], ["state.json"]]),
    ("replace_failure_keeps_committed", {"ops": [["commit", [1], 0], ["snapshot"], ["fail_replace", [2], 1], ["matches_snapshot"], ["load"], ["files"]]},
     [1, True, {"error": "OSError"}, True, [1, [1]], ["state.json"]]),
    ("replace_failure_on_new_store", {"ops": [["fail_replace", "x", 0], ["load"], ["files"]]},
     [{"error": "OSError"}, [0, None], []]),
    ("falsy_values_and_revisions", {"ops": [["commit", None, 0], ["commit", False, 1], ["commit", 0, 2], ["load"]]},
     [1, 2, 3, [3, 0]]),
    ("malformed_json", {"ops": [["corrupt", "{"], ["load"]]}, [None, {"error": "ValueError"}]),
    ("bool_revision_rejected", {"ops": [["corrupt", '{"revision":true,"value":0}'], ["load"]]},
     [None, {"error": "ValueError"}]),
    ("missing_fields_rejected", {"ops": [["corrupt", '{"revision":1}'], ["load"]]}, [None, {"error": "ValueError"}]),
])


add("durable_journal", "authored.local-durable-formats.20261024", "Committed JSONL recovery", """
read_journal(path) returns all committed records from a byte-oriented JSONL
journal, in order. A record is committed only when terminated by byte LF.
Ignore an unterminated tail completely, even if it is valid JSON, malformed
JSON, or incomplete UTF-8. Do not modify the file.

Every complete line must decode as strict UTF-8 and contain one JSON object
with exactly "seq" and "value". seq must be integer (not bool), starting at 1
and increasing by exactly 1. Blank complete lines, invalid JSON/UTF-8, wrong
schema, gaps, duplicates, or an out-of-order seq raise ValueError; never skip
committed corruption. value can be any JSON value. The empty file returns [].
Only the supplied file is read; all files are bounded and local fixtures.
""", '''
import json
from pathlib import Path


def read_journal(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows
''', '''
import json
from pathlib import Path


def read_journal(path):
    committed = Path(path).read_bytes().split(b"\\n")[:-1]
    rows = []
    for expected_seq, line in enumerate(committed, 1):
        try:
            record = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError) as error:
            raise ValueError("corrupt committed record") from error
        if (not isinstance(record, dict) or set(record) != {"seq", "value"}
                or type(record["seq"]) is not int or record["seq"] != expected_seq):
            raise ValueError("invalid sequence or schema")
        rows.append(record)
    return rows
''', [
    ("ordinary_committed", {"text": '{"seq":1,"value":"a"}\n{"seq":2,"value":[0,false]}\n'},
     {"records": [{"seq": 1, "value": "a"}, {"seq": 2, "value": [0, False]}], "bytes_unchanged": True}),
    ("valid_unterminated_tail_is_uncommitted", {"text": '{"seq":1,"value":0}\n{"seq":2,"value":1}'},
     {"records": [{"seq": 1, "value": 0}], "bytes_unchanged": True}),
    ("malformed_unterminated_tail", {"text": '{"seq":1,"value":null}\n{"seq":'},
     {"records": [{"seq": 1, "value": None}], "bytes_unchanged": True}),
    ("incomplete_utf8_tail", {"hex": '7b22736571223a312c2276616c7565223a307d0ae282'},
     {"records": [{"seq": 1, "value": 0}], "bytes_unchanged": True}),
    ("committed_corruption", {"text": '{"seq":1,"value":0}\nnot-json\n{"seq":2,"value":1}\n'},
     {"error": "ValueError"}),
    ("sequence_gap", {"text": '{"seq":1,"value":0}\n{"seq":3,"value":1}\n'}, {"error": "ValueError"}),
    ("duplicate_sequence", {"text": '{"seq":1,"value":0}\n{"seq":1,"value":1}\n'}, {"error": "ValueError"}),
    ("blank_committed_line", {"text": '\n'}, {"error": "ValueError"}),
    ("unicode_record", {"text": '{"seq":1,"value":"中🙂"}\n'},
     {"records": [{"seq": 1, "value": "中🙂"}], "bytes_unchanged": True}),
    ("bool_sequence", {"text": '{"seq":true,"value":0}\n'}, {"error": "ValueError"}),
    ("empty_journal", {"text": ''}, {"records": [], "bytes_unchanged": True}),
])

index = {"schema": "hepta.native-ab.task-index.v1", "task_pack_id": "authored-python-execution-20261024-v1",
         "origin": "New assistant-authored finite Python tasks; no external source corpus",
         "construction_date": "2026-10-24", "task_count": len(TASKS),
         "family_count": len({task["family_id"] for task in TASKS}),
         "families_independent_external_samples": False,
         "tasks": TASKS}
(ROOT / "operator" / "task-index.json").write_bytes(canonical(index) + b"\n")
print(json.dumps({"task_count": len(TASKS), "cases": sum(t["case_count"] for t in TASKS),
                  "task_index_sha256": sha(canonical(index) + b"\n")}, sort_keys=True))
