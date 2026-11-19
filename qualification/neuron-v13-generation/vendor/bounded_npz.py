"""Preflight ZIP and NPY structure before allowing NumPy to allocate arrays."""

import ast
import io
import stat
import struct
import zipfile

import numpy as np

from closure_common import ClosureError


def _directory(raw, members):
    # Bound the central directory before ZipFile constructs a ZipInfo per entry.
    end = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if end < 0 or end + 22 > len(raw):
        raise ClosureError("Missing ZIP end record")
    _, disk, start_disk, disk_count, count, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", raw, end
    )
    if (
        disk
        or start_disk
        or disk_count != count
        or count != len(members)
        or count > 14
        or size > count * 1024
        or offset + size != end
        or end + 22 + comment != len(raw)
        or comment > 1024
        or not raw.startswith(b"PK\x03\x04")
    ):
        raise ClosureError("Unsupported or oversized ZIP directory")


def _header(stream, member_size, limits):
    prefix = stream.read(8)
    if len(prefix) != 8 or prefix[:6] != b"\x93NUMPY":
        raise ClosureError("Invalid NPY signature")
    version = tuple(prefix[6:])
    width = 2 if version == (1, 0) else 4 if version == (2, 0) else 0
    if not width:
        raise ClosureError("Unsupported NPY version")
    length = stream.read(width)
    if len(length) != width:
        raise ClosureError("Truncated NPY header length")
    length = int.from_bytes(length, "little")
    if not 1 <= length <= limits.max_npy_header_bytes:
        raise ClosureError("Oversized NPY header")
    encoded = stream.read(length)
    if len(encoded) != length:
        raise ClosureError("Truncated NPY header")
    try:
        header = ast.literal_eval(encoded.decode("latin1").strip())
    except (ValueError, SyntaxError, UnicodeError, RecursionError) as error:
        raise ClosureError("Invalid NPY header literal") from error
    if (
        not isinstance(header, dict)
        or set(header) != {"descr", "fortran_order", "shape"}
        or not isinstance(header["descr"], str)
        or type(header["fortran_order"]) is not bool
        or not isinstance(header["shape"], tuple)
        or len(header["shape"]) > 4
    ):
        raise ClosureError("Unsupported NPY header fields")
    try:
        dtype = np.dtype(header["descr"])
    except (TypeError, ValueError) as error:
        raise ClosureError("Invalid NPY dtype") from error
    if (
        dtype.hasobject
        or dtype.fields
        or dtype.subdtype
        or dtype.kind not in "iuf"
        or dtype.itemsize not in {1, 2, 4, 8}
    ):
        raise ClosureError("Object or unsupported NPY dtype")
    count = 1
    for dimension in header["shape"]:
        if type(dimension) is not int or not 0 <= dimension <= limits.max_examples:
            raise ClosureError("Unbounded NPY dimension")
        count *= dimension
        if count * dtype.itemsize > limits.max_array_bytes:
            raise ClosureError("Unbounded NPY shape product")
    offset = 8 + width + length
    if member_size - offset != count * dtype.itemsize:
        raise ClosureError("NPY shape does not match exact member payload")
    return {
        "dtype": dtype,
        "shape": header["shape"],
        "offset": offset,
        "payload_bytes": count * dtype.itemsize,
        "fortran_order": header["fortran_order"],
    }


def inspect_npz(raw, names, limits):
    """Return small headers and metadata only; never allocate declared arrays."""
    expected = {name + ".npy" for name in names}
    _directory(raw, expected)
    headers = {}
    metadata = None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != len(expected)
                or {entry.filename for entry in entries} != expected
            ):
                raise ClosureError("Duplicate, missing or unexpected ZIP member")
            total = 0
            for entry in entries:
                if (
                    entry.is_dir()
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.flag_bits & 1
                    or entry.compress_type
                    not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or entry.compress_size > len(raw)
                    or entry.file_size
                    > limits.max_array_bytes + limits.max_npy_header_bytes + 12
                ):
                    raise ClosureError("Unsupported ZIP member or size")
                total += entry.file_size
                if total > limits.max_zip_uncompressed_bytes:
                    raise ClosureError("ZIP declared expansion exceeds bound")
                with archive.open(entry) as stream:
                    header = _header(stream, entry.file_size, limits)
                    name = entry.filename[:-4]
                    headers[name] = header
                    if name == "metadata":
                        if (
                            header["dtype"] != np.dtype("u1")
                            or len(header["shape"]) != 1
                            or header["payload_bytes"] > limits.max_metadata_bytes
                        ):
                            raise ClosureError("Invalid metadata array")
                        metadata = stream.read(limits.max_metadata_bytes + 1)
                        consumed = len(metadata)
                    else:
                        consumed = 0
                        while block := stream.read(1024 * 1024):
                            consumed += len(block)
                            if consumed > header["payload_bytes"]:
                                raise ClosureError(
                                    "ZIP member exceeded declared NPY payload"
                                )
                    if consumed != header["payload_bytes"]:
                        raise ClosureError("Truncated NPY payload")
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError) as error:
        raise ClosureError("Invalid or corrupt bounded NPZ") from error
    return headers, metadata
