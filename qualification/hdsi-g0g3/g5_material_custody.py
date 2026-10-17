"""Read-only historical source/model extraction with strict prelabel separation.

Source owner and independent postseal reviewer reacquire the full pinned archive;
model runner only receives the four Encoder files plus label-free source JSON.
No GitHub credentials are sent to the archive ZIP's signed redirect host.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from g5_original_evidence import read_publisher, source_packet, write_new
from g5_batched_encoder import verified_encoder_only
from real_minilm_reference import CHECKSUMS

ARCHIVE_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
SOURCE_URL='https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/11586991191/zip'
MAX_ARCHIVE_BYTES=420_000_000
MODEL_PARTS=('encoder/model.safetensors','encoder/config.json',
             'encoder/tokenizer.json','encoder/vocab.txt')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_original(dest: Path) -> None:
    if dest.exists() or dest.is_symlink():
        raise ValueError('refuse overwrite / symlink original archive')
    token=os.environ.get('GH_TOKEN','')
    if not token or any(c in token for c in '\r\n'):
        raise ValueError('missing bounded Actions read credential')
    opener=urllib.request.build_opener(NoRedirect)
    request=urllib.request.Request(SOURCE_URL,headers={'Accept':'application/vnd.github+json',
                              'Authorization':'Bearer '+token,'User-Agent':'hepta-hdsi-g5-pin-v1'})
    try:
        opener.open(request,timeout=45)
        raise ValueError('unanticipated unredirected GitHub artifact response')
    except urllib.error.HTTPError as error:
        if error.code not in (302,303,307):
            raise
        signed=error.headers.get('Location','')
    url=urllib.parse.urlparse(signed)
    host=url.hostname or ''
    if url.scheme!='https' or not (host.endswith('.blob.core.windows.net')
            or host.endswith('.githubusercontent.com') or host.endswith('.actions.githubusercontent.com')):
        raise ValueError('untrusted GitHub artifact redirect host')
    if url.username is not None or url.password is not None:
        raise ValueError('unexpected credentials in redirect')
    h=hashlib.sha256()
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY
    fd=os.open(dest,flags,0o600)
    try:
        with os.fdopen(fd,'wb') as out, urllib.request.urlopen(urllib.request.Request(signed,headers={'User-Agent':'hepta-hdsi-g5-signed-download'}),timeout=90) as source:
            total=0
            while chunk:=source.read(1<<20):
                total+=len(chunk)
                if total>MAX_ARCHIVE_BYTES:
                    raise ValueError('bounded archived model download')
                h.update(chunk);out.write(chunk)
            out.flush();os.fsync(out.fileno())
        if h.hexdigest()!=ARCHIVE_SHA:
            raise ValueError('original historical artifact ZIP SHA mismatched')
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def extract_pinned(archive: Path, root: Path, *, mode: str) -> None:
    """Only requested original byte-pinned regular files, no paths/symlinks."""
    if mode not in ('source_owner','reviewer'):
        raise ValueError('unrecognized custody scope')
    required=set(MODEL_PARTS)|{'locomo.json'} if mode=='source_owner' else {'locomo.json'}
    if root.exists():
        raise ValueError('no replacement of a preexisting custody stage')
    root.mkdir(mode=0o700,parents=True)
    try:
        if archive.stat().st_size>MAX_ARCHIVE_BYTES or archive.is_symlink():
            raise ValueError('unexpected original archive')
        outer=hashlib.sha256()
        with archive.open('rb') as raw:
            for part in iter(lambda:raw.read(1<<20),b''):
                outer.update(part)
        if outer.hexdigest()!=ARCHIVE_SHA:
            raise ValueError('historical original archive not SHA pinned')
        with zipfile.ZipFile(archive) as z:
            if z.namelist()!=['memory-inputs.tar.gz']:
                raise ValueError('unreviewed outer ZIP inventory')
            with z.open('memory-inputs.tar.gz') as compressed:
                with tarfile.open(fileobj=compressed,mode='r|gz') as tf:
                    found=set()
                    for member in tf:
                        rel=member.name.removeprefix('memory-inputs/')
                        if rel not in required:
                            continue
                        if not member.name.startswith('memory-inputs/') or not member.isfile() \
                           or rel in found or member.size>120_000_000:
                            raise ValueError('non-unique/unsafe tar original member')
                        found.add(rel)
                        path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
                        with path.open('xb') as out:
                            source=tf.extractfile(member)
                            if source is None:
                                raise ValueError('unreadable original content')
                            h=hashlib.sha256();length=0
                            while data:=source.read(1<<20):
                                length+=len(data)
                                if length>member.size:
                                    raise ValueError('original media overread')
                                h.update(data);out.write(data)
                            out.flush();os.fsync(out.fileno())
                        if length!=member.size or h.hexdigest()!=CHECKSUMS[rel]:
                            raise ValueError('original model/source interior SHA drift')
        if found!=required:
            raise ValueError('missing original model/source material')
    except BaseException:
        import shutil
        shutil.rmtree(root,ignore_errors=True)
        raise


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['source_owner','reviewer'],required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    download_original(args.archive)
    extract_pinned(args.archive,args.root,mode=args.mode)
    if args.mode=='source_owner':
        if args.source is None:
            raise ValueError('source owner must seal unlabelled packet')
        verified_encoder_only(args.root)
        raw=(args.root/'locomo.json').read_bytes()
        read_publisher(raw)
        packet=source_packet(raw)
        write_new(args.source,packet)
        (args.root/'locomo.json').unlink()  # No raw held labels in any exported material.
        print('source packet prepared; 4-file pinned model material staged; original QA gold EXCLUDED')
    else:
        print('independent later reviewer obtained source only; no model weights installed')

if __name__=='__main__':
    main()
