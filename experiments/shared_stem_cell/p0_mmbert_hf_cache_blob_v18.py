#!/usr/bin/env python3
"""Resolve only an EXACT original HF snapshot symlink to its SHA256-named blob.

Neither a publisher signature nor model-parameter qualification. The existing
pinned SHA/LFS source preflight and whole tensor-by-tensor byte verifiers remain
mandatory and independent. Research-only; no authority/promotion side effects.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import stat

REPO_CACHE_SLUG='models--jhu-clsp--mmBERT-small'
REVISION='0eb3d056ec1d6333cf4e19b0966dfde342a41a3a'
HEX64=re.compile(r'[0-9a-f]{64}\Z')
MAX_ORIGINAL_BYTES=2_000_000_000

class Invalid(ValueError):
    pass


def resolve_pinned_hf_cache_blob(path, revision):
    """Return the regular original LFS blob, rejecting foreign/unsafe links.

    hf_hub_download(..., revision=SHA, local_files_only=True) normally returns
    snapshots/SHA/model.safetensors, a symlink to ../../blobs/<sha256>.
    The original source-only verifier forbids symlinks, so this function
    establishes their immutable snapshot/blob relationship and streams the
    true underlying SHA256 before the original unswerving tensor verifiers.
    A non-HF/foreign/changed/corrupted symlink or unsupported repository SHA
    remains a strict error. Does NOT open any held human labels.
    """
    if revision != REVISION or not isinstance(path, (str, Path)):
        raise Invalid('unregistered original pretrained revision/cache path')
    source=Path(path)
    repo=source.parent.parent.parent
    if (source.name!='model.safetensors' or
        source.parent.name!=REVISION or
        source.parent.parent.name!='snapshots' or
        repo.name!=REPO_CACHE_SLUG):
        raise Invalid('checkpoint is not registered immutable HF cache snapshot')
    if source.is_symlink():
        link=os.readlink(source)
        if os.path.isabs(link):
            raise Invalid('absolute pretrained cache symlink not admissible')
        target=source.resolve(strict=True)
        target_root=repo.resolve(strict=True)/'blobs'
        if (target.parent!=target_root or not HEX64.fullmatch(target.name)
                or target.is_symlink()):
            raise Invalid('non-content-addressed original cache link')
        link_parts=Path(link).parts
        if (len(link_parts)!=4 or link_parts[:3]!=('..','..','blobs') or
                link_parts[3]!=target.name):
            raise Invalid('unexpected original HF cache symlink structure')
        cache_file=target
    else:
        # A regular SHA-pinned local snapshot was already accepted by the
        # original byte checker; retain that strictly bounded behavior.
        cache_file=source
    if not cache_file.is_file() or cache_file.is_symlink():
        raise Invalid('original resolved checkpoint not a regular source file')
    meta=cache_file.stat()
    if not stat.S_ISREG(meta.st_mode) or not 1024<=meta.st_size<=MAX_ORIGINAL_BYTES:
        raise Invalid('missing or oversized original safetensors file')
    if source.is_symlink():
        hasher=hashlib.sha256()
        with cache_file.open('rb') as f:
            while block:=f.read(8*1024*1024):
                hasher.update(block)
        if hasher.hexdigest()!=cache_file.name:
            raise Invalid('original content-addressed LFS cache blob differs from its SHA256')
    return cache_file
