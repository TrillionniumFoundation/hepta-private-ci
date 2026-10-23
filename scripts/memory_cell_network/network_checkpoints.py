"""Transfer actual immutable checkpoint bytes, with retained manifest pins."""

import base64
import os
from pathlib import Path
import shutil
import tempfile

from parametric_owner import _checkpoint, _digest, _name
from tensor_contract import bounded_read
from network_wire import fields

FILES = {
    "lineage.json": 256 * 1024,
    "adapter_config.json": 64 * 1024,
    "adapter_model.safetensors": 64 * 1024 * 1024,
}


def pack(directory, manifest_sha256, scope):
    _checkpoint(directory, manifest_sha256, scope)
    return dict(
        manifest_sha256=manifest_sha256,
        scope=scope,
        files={
            name: base64.b64encode(bounded_read(Path(directory) / name, limit)).decode(
                "ascii"
            )
            for name, limit in FILES.items()
        },
    )


def install(root, package, retained_pin):
    fields(package, ("manifest_sha256", "scope", "files"))
    if (
        not _digest(retained_pin)
        or package["manifest_sha256"] != retained_pin
        or not _name(package["scope"])
    ):
        raise ValueError("independently retained transfer pin and scope required")
    fields(package["files"], FILES)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("real checkpoint store required")
    target = root / retained_pin
    temporary = Path(tempfile.mkdtemp(prefix=".stage-", dir=root))
    try:
        for name, limit in FILES.items():
            encoded = package["files"][name]
            if type(encoded) is not str or len(encoded) > 4 * ((limit + 2) // 3):
                raise ValueError("checkpoint transfer file byte bound")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, UnicodeEncodeError) as error:
                raise ValueError("invalid checkpoint base64") from error
            if not 0 < len(raw) <= limit:
                raise ValueError("checkpoint transfer file byte bound")
            with (temporary / name).open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        roots, base = _checkpoint(temporary, retained_pin, package["scope"])
        if target.exists():
            _checkpoint(target, retained_pin, package["scope"])
        else:
            if os.name != "nt":
                descriptor = os.open(temporary, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            temporary.rename(target)
            if os.name != "nt":
                descriptor = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        return dict(manifest_sha256=retained_pin, roots=list(roots), base_identity=base)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
