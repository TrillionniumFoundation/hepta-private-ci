"""Read primitive/tensor Torch ZIP checkpoints without importing Torch.

Only OrderedDict, typed-storage tokens and one local tensor reconstruction
function are permitted. Unknown pickle globals or persistent IDs are rejected.
This is an inspection reader for the frozen CPU fixture, not a general loader.
"""

import collections
import io
import math
import pickle
import zipfile
from dataclasses import dataclass

import numpy as np

_DTYPES = {
    "DoubleStorage": np.dtype("<f8"),
    "FloatStorage": np.dtype("<f4"),
    "LongStorage": np.dtype("<i8"),
    "IntStorage": np.dtype("<i4"),
    "ByteStorage": np.dtype("u1"),
    "BoolStorage": np.dtype("?"),
}


@dataclass(frozen=True)
class Tensor:
    array: np.ndarray
    shape: tuple
    stride: tuple
    offset: int
    dtype: str
    requires_grad: bool
    device: str = "cpu"
    layout: str = "torch.strided"


@dataclass(frozen=True)
class Storage:
    raw: bytes
    dtype: np.dtype
    count: int


def _rebuild(storage, offset, shape, stride, requires_grad, hooks, metadata=None):
    if not isinstance(storage, Storage):
        raise TypeError("local typed storage required")
    shape, stride = tuple(shape), tuple(stride)
    if (
        type(offset) is not int
        or offset < 0
        or len(shape) != len(stride)
        or len(shape) > 8
        or any(type(n) is not int or n < 0 for n in shape + stride)
        or type(requires_grad) is not bool
        or hooks not in (None, {})
        or metadata not in (None, {})
    ):
        raise ValueError("unsupported tensor metadata")
    count = math.prod(shape)
    last = offset + sum((size - 1) * step for size, step in zip(shape, stride))
    if count and last >= storage.count:
        raise ValueError("tensor exceeds underlying storage")
    if not count and offset > storage.count:
        raise ValueError("empty tensor offset exceeds storage")
    array = np.ndarray(
        shape,
        dtype=storage.dtype,
        buffer=storage.raw,
        offset=offset * storage.dtype.itemsize,
        strides=tuple(step * storage.dtype.itemsize for step in stride),
    )
    names = {
        "float64": "torch.float64",
        "float32": "torch.float32",
        "int64": "torch.int64",
        "int32": "torch.int32",
        "uint8": "torch.uint8",
        "bool": "torch.bool",
    }
    return Tensor(
        array,
        shape,
        stride,
        offset,
        names[storage.dtype.name],
        requires_grad,
    )


def load_checkpoint(raw):
    if not 0 < len(raw) <= 1048576:
        raise ValueError("frozen checkpoint byte budget exceeded")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or len(names) > 128:
            raise ValueError("duplicate or excessive checkpoint entries")
        if any(name.startswith("/") or ".." in name.split("/") for name in names):
            raise ValueError("unsafe checkpoint member path")
        if sum(item.file_size for item in infos) > 2097152:
            raise ValueError("uncompressed checkpoint byte budget exceeded")
        data_members = [name for name in names if name.endswith("/data.pkl")]
        if len(data_members) != 1 or archive.testzip() is not None:
            raise ValueError("checkpoint pickle member/CRC mismatch")
        root = data_members[0].removesuffix("data.pkl")
        if (
            root + "byteorder" not in names
            or archive.read(root + "byteorder") != b"little"
        ):
            raise ValueError("explicit little-endian checkpoint required")
        cache = {}

        class Reader(pickle.Unpickler):
            def find_class(self, module, name):
                if (module, name) == ("collections", "OrderedDict"):
                    return collections.OrderedDict
                if (module, name) == ("torch._utils", "_rebuild_tensor_v2"):
                    return _rebuild
                if module == "torch" and name in _DTYPES:
                    return name
                raise ValueError("disallowed checkpoint global: " + module + "." + name)

            def persistent_load(self, identity):
                if (
                    not isinstance(identity, tuple)
                    or len(identity) != 5
                    or identity[0] != "storage"
                    or identity[1] not in _DTYPES
                    or not isinstance(identity[2], str)
                    or not identity[2].isdigit()
                    or identity[3] != "cpu"
                    or type(identity[4]) is not int
                    or not 0 <= identity[4] <= 1048576
                ):
                    raise ValueError("disallowed storage persistent identity")
                _, token, key, _, count = identity
                dtype = _DTYPES[token]
                if key not in cache:
                    storage_bytes = archive.read(root + "data/" + key)
                    if len(storage_bytes) != count * dtype.itemsize:
                        raise ValueError("storage byte count differs")
                    cache[key] = Storage(storage_bytes, dtype, count)
                storage = cache[key]
                if storage.dtype != dtype or storage.count != count:
                    raise ValueError("shared storage identity differs")
                return storage

        return Reader(io.BytesIO(archive.read(data_members[0]))).load()
