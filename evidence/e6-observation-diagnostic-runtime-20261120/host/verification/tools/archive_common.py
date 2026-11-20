"""Shared local archive path, identity and exclusion primitives. No side effects."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath

ROOT = Path('/workspace/scratch/e9e051ab0825')
MAX_PART_BYTES = 480000
MAX_ORIGINAL_BYTES = 64 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def json_bytes(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode()


def safe_member(name: str) -> bool:
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and str(p)==name and '..' not in p.parts and '\\' not in name


def metadata(path: Path) -> dict:
    st=path.lstat()
    return {'path':str(path),'bytes':st.st_size,'mode':stat.S_IMODE(st.st_mode),
            'device':st.st_dev,'inode':st.st_ino,'mtime_ns':st.st_mtime_ns,
            'ctime_ns':st.st_ctime_ns,'regular':stat.S_ISREG(st.st_mode),
            'symlink':stat.S_ISLNK(st.st_mode)}


def excluded_name(path: Path) -> str | None:
    name=path.name.lower()
    if '__pycache__' in path.parts or name.endswith(('.pyc','.pyo')):
        return 'generated Python bytecode; metadata only'
    if name.endswith(('.key','.pem','.p12','.pfx','.jks')) or name in {'id_rsa','id_dsa','id_ed25519','id_ecdsa'}:
        return 'key/container filename; body must not be opened'
    return None


def stable_read(path: Path) -> tuple[bytes,dict]:
    assert path.is_absolute() and path.is_relative_to(ROOT)
    before=metadata(path)
    assert before['regular'] and not before['symlink'],str(path)
    assert before['bytes']<=MAX_ORIGINAL_BYTES,str(path)
    assert excluded_name(path) is None,str(path)
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        opened=os.fstat(fd)
        assert opened.st_ino==before['inode'] and opened.st_dev==before['device']
        with os.fdopen(fd,'rb',closefd=False) as stream:
            data=stream.read(MAX_ORIGINAL_BYTES+1)
    finally:
        os.close(fd)
    after=metadata(path)
    assert before==after and len(data)==before['bytes'],('input changed while read',str(path))
    return data,before


def is_elf_header(path: Path) -> bool:
    """Type probe only; a key-name exclusion must already have been applied."""
    assert excluded_name(path) is None
    before=metadata(path)
    assert before['regular'] and not before['symlink']
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        opened=os.fstat(fd)
        assert opened.st_ino==before['inode'] and opened.st_dev==before['device']
        header=os.read(fd,4)
    finally:
        os.close(fd)
    assert metadata(path)==before
    return header==b'\x7fELF'


def is_rpc_object(obj: object) -> bool:
    if isinstance(obj,list):
        return any(is_rpc_object(v) for v in obj)
    if not isinstance(obj,dict):
        return False
    if 'content' in obj and ('isError' in obj or 'structuredContent' in obj):
        return True
    return any(is_rpc_object(v) for v in obj.values() if isinstance(v,(dict,list)))


def content_role(path: Path,data: bytes) -> str:
    if path.suffix.lower()=='.json':
        try:
            if is_rpc_object(json.loads(data)):
                return 'original_rpc_envelope_verbatim'
        except (json.JSONDecodeError,UnicodeDecodeError):
            pass
    return 'retained_original'
