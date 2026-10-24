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
