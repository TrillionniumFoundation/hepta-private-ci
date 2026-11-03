"""One bounded, actually consumed qualification UI stream for every lane."""

import json
import time

OWNER_SCOPE = "hepta.qualification.turn-owner.v2"
UI_SCHEMA = "hepta.qualification.streamed-ui.v1"
UI_CONTRACT = {"schema": UI_SCHEMA,
    "delivery": "text_delta_then_same_item_completion", "max_delta_bytes": 32768,
    "max_item_bytes": 65536, "max_items": 1024, "max_total_bytes": 4194304,
    "max_events": 8192, "production_core_ui": False}


class UiCollector:
    def __init__(self, path=None):
        self.items = {}
        self.events = 0
        self.deltas = 0
        self.total_bytes = 0
        self.first_delta_ns = None
        self.last_completion_ns = None
        self.log = path.open("x", encoding="utf-8") if path is not None else None

    def _item(self, item_id):
        if not isinstance(item_id, str) or not item_id or len(item_id.encode()) > 256:
            raise ValueError("UI item identity is missing or unbounded")
        if item_id not in self.items:
            if len(self.items) >= UI_CONTRACT["max_items"]:
                raise ValueError("UI item count exceeds bound")
            self.items[item_id] = {"parts": {}, "bytes": 0, "delta_count": 0,
                                   "completed": False, "text": None}
        return self.items[item_id]

    def _record(self, value):
        if self.events >= UI_CONTRACT["max_events"]:
            raise ValueError("UI event count exceeds bound")
        value = {"observed_ns": time.time_ns(), **value}
        if self.log is not None:
            self.log.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.log.flush()
        self.events += 1

    def delta(self, item_id, text, content_index=0):
        if (not isinstance(text, str) or type(content_index) is not int
                or not 0 <= content_index < 1024):
            raise ValueError("invalid streamed UI text coordinates")
        size = len(text.encode())
        if size > UI_CONTRACT["max_delta_bytes"]:
            raise ValueError("UI delta exceeds UTF-8 byte bound")
        item = self._item(item_id)
        if item["completed"]:
            raise ValueError("UI delta arrived after the same item completed")
        if item["bytes"] + size > UI_CONTRACT["max_item_bytes"] or self.total_bytes + size > UI_CONTRACT["max_total_bytes"]:
            raise ValueError("streamed UI text exceeds retained byte bound")
        self._record({"event": "text_delta", "item_id": item_id,
                      "content_index": content_index, "delta": text})
        item["parts"][content_index] = item["parts"].get(content_index, "") + text
        item["bytes"] += size
        item["delta_count"] += 1
        self.total_bytes += size
        self.deltas += 1
        if self.first_delta_ns is None:
            self.first_delta_ns = time.time_ns()

    def completed(self, item_id, text):
        if not isinstance(text, str) or len(text.encode()) > UI_CONTRACT["max_item_bytes"]:
            raise ValueError("UI completion text exceeds bound")
        item = self._item(item_id)
        if item["completed"]:
            raise ValueError("duplicate UI item completion")
        if item["delta_count"]:
            streamed = "".join(item["parts"][index] for index in sorted(item["parts"]))
            if streamed != text:
                raise ValueError("UI completion differs from the same item's actual streamed text")
        else:
            size = len(text.encode())
            if self.total_bytes + size > UI_CONTRACT["max_total_bytes"]:
                raise ValueError("UI completion exceeds retained total byte bound")
            self.total_bytes += size
            item["bytes"] = size
        self._record({"event": "item_completed", "item_id": item_id, "text": text})
        item["completed"], item["text"] = True, text
        self.last_completion_ns = time.time_ns()

    def native_event(self, value, session):
        if value.get("schema") != UI_SCHEMA or value.get("session") != session:
            raise ValueError("native UI event belongs to another session/schema")
        if value.get("event") == "ui/text_delta":
            self.delta(value.get("item_id"), value.get("delta"), value.get("content_index"))
        elif value.get("event") == "ui/item_completed":
            self.completed(value.get("item_id"), value.get("text"))
        else:
            raise ValueError("unknown native UI event")

    def require_completed(self, answer):
        if not self.deltas or any(not item["completed"] for item in self.items.values()):
            raise ValueError("completed task lacks actual streamed-and-completed UI evidence")
        if not any(item["completed"] and item["delta_count"] and item["text"] == answer
                   for item in self.items.values()):
            raise ValueError("final answer was not actually streamed and completed under the same UI item")

    def snapshot(self):
        return {"contract": dict(UI_CONTRACT), "events": self.events,
            "actual_text_deltas": self.deltas, "retained_text_bytes": self.total_bytes,
            "first_delta_ns": self.first_delta_ns, "last_completion_ns": self.last_completion_ns,
            "items": {key: {field: item[field] for field in ("delta_count", "bytes", "completed")}
                      for key, item in self.items.items()},
            "production_core_ui_parity": False}

    def close(self):
        if self.log is not None:
            self.log.close()
            self.log = None


def receive_native_turn(backend, session, deadline, ui):
    while True:
        value = backend.receive(deadline)
        if "event" in value:
            ui.native_event(value, session)
            continue
        if value.get("session") != session:
            raise ValueError("native result session mismatch")
        return value
