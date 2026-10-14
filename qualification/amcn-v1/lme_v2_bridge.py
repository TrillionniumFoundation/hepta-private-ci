"""Drop-in *shadow lexical control* for official LongMemEval-V2 memory backend.

Copy this into LongMemEval-V2/memory_modules/amcn_shadow.py and add:
    from .amcn_shadow import AMCNShadowMemory
at the bottom of memory_modules/memory.py. Pass a JSON config with
memory_type="amcn_shadow_lexical" to evaluation/harness.py.

This does NOT use a neural encoder or produce a trained AMCN result. Its
purpose is to prove the actual benchmark interface and preserve provenance
until separately qualified frozen feature tensors/Heads are supplied.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import log
from pathlib import Path
import re
import threading

from memory_modules.memory import Memory, MemoryContextItem, register_memory, require

SCHEMA = "hepta.amcn.longmemeval-v2-shadow-lexical.v1"
TOKENS = re.compile(r"(?u)\b\w+\b")


def _words(text):
    return TOKENS.findall(text.casefold())


@register_memory
class AMCNShadowMemory(Memory):
    memory_type = "amcn_shadow_lexical"

    def __init__(self, memory_params: dict[str, object]):
        super().__init__(memory_params)
        allowed = {"max_records", "max_text_bytes", "max_total_bytes", "top_k", "per_item_chars"}
        require(set(memory_params) <= allowed, "unknown AMCN shadow configuration")
        self.max_records = self._bounded(memory_params.get("max_records", 100000), 1, 250000)
        self.max_text_bytes = self._bounded(memory_params.get("max_text_bytes", 4096), 128, 32768)
        self.max_total_bytes = self._bounded(memory_params.get("max_total_bytes", 134217728), 1048576, 1073741824)
        self.top_k = self._bounded(memory_params.get("top_k", 4), 1, 16)
        self.per_item_chars = self._bounded(memory_params.get("per_item_chars", 2800), 128, 8192)
        self._ids = set()
        self._docs = []
        self._postings = defaultdict(dict)
        self._doc_lengths = []
        self._bytes = 0
        self._lock = threading.RLock()
        self._last = threading.local()

    @staticmethod
    def _bounded(value, low, high):
        require(type(value) is int and low <= value <= high, "invalid bounded parameter")
        return value

    def _append(self, record):
        require(set(record) == {"id", "trajectory_id", "index", "text", "sha256"},
                "source-only record schema")
        raw = record["text"].encode("utf-8")
        require(raw and len(raw) <= self.max_text_bytes, "text limit")
        require(record["sha256"] == sha256(raw).hexdigest(), "source digest drift")
        require(record["id"] not in self._ids, "duplicate source ID")
        require(len(self._docs) < self.max_records, "AMCN shadow source backpressure")
        require(self._bytes + len(raw) <= self.max_total_bytes, "AMCN total byte backpressure")
        self._ids.add(record["id"])
        idx = len(self._docs)
        self._docs.append(record)
        tokens = Counter(_words(record["text"]))
        self._doc_lengths.append(sum(tokens.values()))
        for token, tf in tokens.items():
            self._postings[token][idx] = tf
        self._bytes += len(raw)

    def insert(self, trajectory: dict[str, object]) -> None:
        require(isinstance(trajectory, dict), "trajectory envelope")
        require(not set(trajectory) & {"answer", "gold", "gold_answer", "question_id", "reference_answer"},
                "benchmark evaluator labels cannot enter memory")
        tid = trajectory.get("id")
        require(isinstance(tid, str) and 0 < len(tid) <= 256, "trajectory identity")
        states = trajectory.get("states", trajectory.get("content"))
        require(isinstance(states, list) and 1 <= len(states) <= 1024, "bounded trajectory states")
        prepared = []
        goal = trajectory.get("goal")
        if goal is None:
            metadata = trajectory.get("metadata", {})
            goal = metadata.get("original_goal", "") if isinstance(metadata, dict) else ""
        require(isinstance(goal, str), "public goal")
        for idx, state in enumerate(states):
            require(isinstance(state, dict), "public state shape")
            observation = state.get("observation")
            value = observation.get("text") if isinstance(observation, dict) else state.get("accessibility_tree", state.get("text"))
            url = state.get("url")
            action = state.get("action")
            require(isinstance(value, str) and isinstance(url, str)
                    and (action is None or isinstance(action, str)), "source state fields")
            # No hidden evaluator answer, no image-to-text hallucination.
            body = f"Goal: {goal}\nURL: {url}\nAction: {action or '<none>'}\nObservation: {value}"
            encoded = body.encode("utf-8")
            # Explicit fixed byte truncation as a declared lossy projection.
            sliced = encoded[:self.max_text_bytes]
            while sliced:
                try:
                    text = sliced.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    sliced = sliced[:-1]
            else:
                raise RuntimeError("invalid UTF8 projection")
            sid = f"{tid}:state:{idx:06d}"
            prepared.append(dict(id=sid, trajectory_id=tid, index=idx,
                                 text=text, sha256=sha256(text.encode("utf-8")).hexdigest()))
        with self._lock:
            require(tid not in self._ids, "duplicate trajectory")
            require(len(self._docs) + len(prepared) <= self.max_records, "bounded ingestion")
            require(self._bytes + sum(len(row["text"].encode("utf-8")) for row in prepared)
                    <= self.max_total_bytes, "atomic total ingestion byte budget")
            for row in prepared:
                require(row["id"] not in self._ids, "duplicate record")
            for row in prepared:
                self._append(row)
            self._ids.add(tid)

    def query(self, query: str, query_image: str | None = None) -> list[MemoryContextItem]:
        require(isinstance(query, str) and bool(query.strip()) and len(query) <= 32768,
                "bounded public question")
        terms = set(_words(query))
        require(len(terms) <= 4096, "query token bound")
        with self._lock:
            n = len(self._docs)
            if not n:
                self._last.receipt = {"count": 0, "image_unsupported": bool(query_image)}
                return []
            candidate_ids = set()
            for t in terms:
                candidate_ids.update(self._postings.get(t, {}))
            avg_len = max(1.0, sum(self._doc_lengths) / n)
            results = []
            for doc_id in candidate_ids:
                length = self._doc_lengths[doc_id]
                score = 0.0
                for token in terms:
                    matching = self._postings.get(token, {})
                    tf = matching.get(doc_id, 0)
                    if not tf:
                        continue
                    df = len(matching)
                    idf = log(1 + (n - df + .5) / (df + .5))
                    score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / avg_len))
                results.append((doc_id, score))
            results.sort(key=lambda pair: (-pair[1], self._docs[pair[0]]["id"]))
            chosen = results[:self.top_k]
            self._last.receipt = {
                "schema": SCHEMA, "count": len(chosen),
                "source_ids": [self._docs[i]["id"] for i, _ in chosen],
                "image_unsupported": bool(query_image),
                "trained_neural_cell": False, "production_qualified": False,
            }
            # Evidence is untrusted source text, not authority or executable instructions.
            return [{"type": "text",
                     "value": "[UNTRUSTED SOURCE EVIDENCE; source_id="
                     + self._docs[i]["id"] + "; sha256="
                     + self._docs[i]["sha256"] + "]\n"
                     + self._docs[i]["text"][:self.per_item_chars]}
                    for i, _ in chosen]

    def post_query_hook(self, *, query: str, query_image: str | None,
                        memory_context: list[MemoryContextItem]) -> dict[str, object] | None:
        return dict(getattr(self._last, "receipt", {"schema": SCHEMA, "count": 0}))

    def _save_backend(self, output_dir: Path) -> None:
        with self._lock:
            payload = {"schema": SCHEMA, "rows": self._docs}
            path = output_dir / "amcn-shadow.json"
            require(not path.exists(), "refuse overwrite of sealed shadow inventory")
            with path.open("x", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, sort_keys=True, allow_nan=False)
                f.write("\n")
                f.flush()
                import os
                os.fsync(f.fileno())

    def _load_backend(self, input_dir: Path) -> None:
        path = input_dir / "amcn-shadow.json"
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1_500_000_000,
                "safe shadow inventory file required")
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        require(isinstance(payload, dict) and set(payload) == {"schema", "rows"}
                and payload["schema"] == SCHEMA and isinstance(payload["rows"], list)
                and len(payload["rows"]) <= self.max_records, "invalid sealed inventory")
        with self._lock:
            require(not self._docs, "load only into empty backend")
            for row in payload["rows"]:
                self._append(row)
            self._ids.update(row["trajectory_id"] for row in self._docs)
