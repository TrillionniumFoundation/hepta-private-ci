"""Stream committed blobs by object ID; never read worktree or filtered bytes."""

from pathlib import Path
import re
import subprocess
import tempfile


class GitTree:
    """One exact tree and one bounded-lifetime Git object-reading process."""

    def __init__(self, root: Path, revision: str):
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError("revision must be an exact Git SHA")
        self.command = ["git", "--no-replace-objects", "-C", str(root)]
        listing = subprocess.check_output(
            [*self.command, "ls-tree", "-r", "-t", "-z", "--full-tree", revision],
            stderr=subprocess.PIPE,
        )
        self.objects = {}
        seen = set()
        for record in listing.split(b"\0"):
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            _mode, kind, oid = metadata.split()
            if re.fullmatch(rb"[0-9a-f]{40}", oid) is None:
                raise ValueError("invalid tree object identity")
            name = path.decode("utf-8")
            if name in seen:
                raise ValueError("duplicate exact-tree path")
            seen.add(name)
            if kind != b"tree":
                self.objects[name] = (kind, oid)

    def __enter__(self):
        # Lazy object fetches in partial clones can produce many diagnostics.
        # Spool them rather than letting an unread stderr pipe block the reader.
        self.errors = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(
                [*self.command, "cat-file", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.errors,
            )
        except BaseException:
            self.errors.close()
            raise
        return self

    def read(self, path: str) -> bytes:
        """Read one raw blob, checking identity and byte framing before return."""
        entry = self.objects.get(path)
        if entry is None or entry[0] != b"blob":
            raise subprocess.CalledProcessError(
                128, self.command, stderr=b"exact tree path is not a blob"
            )
        _, oid = entry
        # Only tree-derived hexadecimal IDs enter the line-based protocol.
        # Paths may contain spaces, tabs or newlines without becoming requests.
        self.process.stdin.write(oid + b"\n")
        self.process.stdin.flush()
        header = self.process.stdout.readline()
        match = re.fullmatch(rb"([0-9a-f]{40}) blob ([0-9]+)\n", header)
        if match is None or match[1] != oid:
            raise ValueError("unexpected Git blob identity or type")
        size = int(match[2])
        contents = self.process.stdout.read(size)
        if len(contents) != size or self.process.stdout.read(1) != b"\n":
            raise ValueError("truncated Git blob response")
        return contents

    def __exit__(self, exception_type, exception, traceback):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        self.process.stdout.close()
        timeout = None
        try:
            try:
                status = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                timeout = error
                self.process.terminate()
                try:
                    status = self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    status = self.process.wait(timeout=5)
            self.errors.seek(0)
            errors = self.errors.read(65536)
        finally:
            self.errors.close()
        if exception_type is None and timeout is not None:
            raise timeout
        if exception_type is None and status:
            raise subprocess.CalledProcessError(
                status, self.process.args, stderr=errors
            )
