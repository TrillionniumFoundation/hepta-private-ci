"""Explicit registered persistence hooks for unchanged scientific serializers.

Only write opens inside the registered raw root are wrapped. Every payload is
checked under the same cross-process lock, flushed and fsynced. Closed immutable
artifacts are uniformly byte-deduplicated; locks and mutable logs are excluded.
The hooks are restored in finally and are declared in the v2 source freeze.
"""

import builtins
from contextlib import contextmanager
import io
import os
from pathlib import Path

from .resource_v2 import StorageBudget


class CheckedFile:
    def __init__(self, wrapped, storage, path, mode):
        self._wrapped, self._storage, self._path = wrapped, storage, path
        self._mode, self._closed = mode, False
        self._text, self._text_bytes = [], 0

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.close()
        return False

    def _physical_write(self, data):
        size = len(data.encode(self._wrapped.encoding or "utf-8")) if isinstance(data, str) else memoryview(data).nbytes
        with self._storage.writer_lock():
            position = self._wrapped.tell()
            current = os.fstat(self._wrapped.fileno()).st_size
            if "a" in self._mode:
                position = current
            additional = max(0, position + size - current)
            relative = self._path.relative_to(self._storage.root)
            c_training = relative.parts[0] == "stage_C" and "endpoint_evaluation" not in relative.parts
            emergency = ("FAIL" in self._path.name.upper() and self._path.name.endswith(".json")
                         and position + size <= 64 * 1024)
            self._storage.check(additional, c_training=c_training, check_memory=not emergency)
            result = self._wrapped.write(data)
            self._wrapped.flush()
            os.fsync(self._wrapped.fileno())
            return result

    def write(self, data):
        if not isinstance(data, str):
            self.flush()
            return self._physical_write(data)
        size = len(data.encode(self._wrapped.encoding or "utf-8"))
        if self._text_bytes + size > 64 * 1024:
            self.flush()
        if size >= 64 * 1024:
            return self._physical_write(data)
        self._text.append(data)
        self._text_bytes += size
        return len(data)

    def flush(self):
        if self._text:
            text = "".join(self._text)
            self._physical_write(text)
            self._text, self._text_bytes = [], 0
        self._wrapped.flush()

    def tell(self):
        self.flush()
        return self._wrapped.tell()

    def seek(self, offset, whence=0):
        self.flush()
        return self._wrapped.seek(offset, whence)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def truncate(self, size=None):
        self.flush()
        target = self._wrapped.tell() if size is None else size
        current = os.fstat(self._wrapped.fileno()).st_size
        if target < current:
            raise RuntimeError("Registered raw artifacts cannot be silently truncated")
        with self._storage.writer_lock():
            self._storage.check(target - current)
            result = self._wrapped.truncate(target)
            self._wrapped.flush()
            os.fsync(self._wrapped.fileno())
            return result

    def close(self):
        if self._closed:
            return
        try:
            self.flush()
        finally:
            self._closed = True
            self._wrapped.close()
        # Appendable records remain mutable until explicit final-stage sealing.
        if "a" not in self._mode and not self._path.name.endswith((".log", ".jsonl")):
            self._storage.deduplicate_closed(self._path)


@contextmanager
def guarded_writes(root, registration=None):
    storage = root if isinstance(root, StorageBudget) else StorageBudget(root, registration)
    old_builtin, old_io = builtins.open, io.open
    old_rename, old_replace = os.rename, os.replace

    def guard(original):
        def open_file(file, mode="r", *args, **kwargs):
            if not isinstance(file, (str, bytes, os.PathLike)) or not any(flag in mode for flag in "wax+"):
                return original(file, mode, *args, **kwargs)
            target = Path(os.fsdecode(file)).resolve()
            if (not target.is_relative_to(storage.root) or target.suffix == ".lock"
                    or target.name.startswith(".ops-") or target.name == "ACTIVE_WORKERS.json"):
                return original(file, mode, *args, **kwargs)
            with storage.writer_lock():
                # Existing artifacts are immutable. A restarted attempt uses a new root.
                if target.exists() and ("w" in mode or "x" in mode or "+" in mode):
                    raise FileExistsError("Refusing to replace a persisted scientific artifact: " + str(target))
                if target.exists() and "a" in mode and target.stat().st_nlink > 1:
                    raise RuntimeError("Cannot append to an already content-addressed artifact")
                emergency = "FAIL" in target.name.upper() and target.name.endswith(".json")
                storage.check(check_memory=not emergency)
                wrapped = original(file, mode, *args, **kwargs)
                return CheckedFile(wrapped, storage, target, mode)
        return open_file

    def rename_guard(original):
        def perform(source, destination, *args, **kwargs):
            left, right = Path(os.fsdecode(source)).resolve(), Path(os.fsdecode(destination)).resolve()
            source_inside, destination_inside = left.is_relative_to(storage.root), right.is_relative_to(storage.root)
            if not source_inside and not destination_inside:
                return original(source, destination, *args, **kwargs)
            if not source_inside or not destination_inside or args or kwargs:
                raise ValueError("Unregistered cross-root or descriptor-relative raw rename")
            with storage.writer_lock():
                declared_replacement = left.name.endswith((".cas-link", ".ops-pending"))
                if right.exists() and not declared_replacement:
                    raise FileExistsError("Refusing to overwrite a persisted scientific artifact")
                return original(source, destination)
        return perform

    builtins.open, io.open = guard(old_builtin), guard(old_io)
    os.rename, os.replace = rename_guard(old_rename), rename_guard(old_replace)
    try:
        yield storage
    finally:
        builtins.open, io.open = old_builtin, old_io
        os.rename, os.replace = old_rename, old_replace
