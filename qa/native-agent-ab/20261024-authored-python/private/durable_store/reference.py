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
