"""Bind offline teacher media evidence to bytes consumed by its processor.

The original validator hashes local files before HF preprocessing. A file
could change in between, making an old source digest describe a different
model input. This guard makes bounded owner-private copies, revalidates their
ordered digest, and keeps them alive until preprocessing completes.

Local byte integrity is NOT publisher, checkpoint, licensing, or data
provenance attestation, and grants no model or runtime authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
from typing import Callable, Iterator

MEDIA = ("image", "audio", "video")
MAX_MEDIA_FILE_BYTES = 128 * 1024 * 1024
MAX_MEDIA_BATCH_BYTES = 512 * 1024 * 1024
COPY_CHUNK = 1024 * 1024


class TeacherMediaSealError(ValueError):
    pass


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def sealed_media_inputs(*, records: list, media_root: str | Path,
                        candidate: str, expected_source_digest: str,
                        original_conversations: list,
                        validate_records: Callable) -> Iterator[list]:
    """Give processors private byte-frozen media, not caller-owned paths.

    The source validator continues to own modality ordering and digest
    construction. It must compute the same digest for each sealed copy.
    Text-only requests reuse already materialized immutable strings.
    """
    if not any(isinstance(row, dict) and any(m in row for m in MEDIA)
               for row in records):
        yield original_conversations
        return
    root = Path(media_root).absolute()
    if not root.is_dir() or root.is_symlink():
        raise TeacherMediaSealError("source root must be a real local directory")
    resolved_root = root.resolve(strict=True)
    total_bytes = 0
    with TemporaryDirectory(prefix="hepta-teacher-media-") as private_dir:
        sealed_rows: list[dict] = []
        for index, row in enumerate(records):
            if not isinstance(row, dict):
                raise TeacherMediaSealError("source row changed after validation")
            sealed = dict(row)
            for modality in MEDIA:
                if modality not in row:
                    continue
                relative = row[modality]
                if (not isinstance(relative, str) or not relative
                        or "\x00" in relative or Path(relative).is_absolute()
                        or ".." in Path(relative).parts):
                    raise TeacherMediaSealError("invalid local media path after validation")
                source = root / relative
                if (source.is_symlink() or not source.is_file()
                        or any(parent.is_symlink() for parent in source.parents
                               if parent != root and root in parent.parents)
                        or not source.resolve(strict=True).is_relative_to(resolved_root)):
                    raise TeacherMediaSealError("media path changed or escaped source root")
                suffix = source.suffix
                if re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix) is None:
                    suffix = ".bin"
                name = f"{index:02d}_{modality}{suffix}"
                target = Path(private_dir) / name
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                try:
                    descriptor = os.open(source, flags)
                    with os.fdopen(descriptor, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                                or not 0 < before.st_size <= MAX_MEDIA_FILE_BYTES):
                            raise TeacherMediaSealError("source media not a bounded single-link file")
                        if total_bytes + before.st_size > MAX_MEDIA_BATCH_BYTES:
                            raise TeacherMediaSealError("teacher media batch exceeds byte limit")
                        copied = 0
                        with target.open("xb") as output:
                            while chunk := stream.read(COPY_CHUNK):
                                copied += len(chunk)
                                if (copied > MAX_MEDIA_FILE_BYTES
                                        or total_bytes + copied > MAX_MEDIA_BATCH_BYTES):
                                    raise TeacherMediaSealError("media grew beyond copy budget")
                                output.write(chunk)
                        after = os.fstat(stream.fileno())
                        if copied != before.st_size or _identity(before) != _identity(after):
                            raise TeacherMediaSealError("source media changed while sealing")
                    target.chmod(0o600)
                except OSError as error:
                    raise TeacherMediaSealError("could not freeze local teacher media") from error
                total_bytes += copied
                sealed[modality] = name
            sealed_rows.append(sealed)
        frozen_conversations, frozen_digest = validate_records(sealed_rows, private_dir, candidate)
        if frozen_digest != expected_source_digest:
            raise TeacherMediaSealError("teacher source bytes changed after digest preflight")
        yield frozen_conversations
