"""Receive one already-returned GitHub RPC through bounded local PTY stdin.

No network/Git/desktop operation. Preserve original raw bytes before parsing;
only publish one exact transport payload and a verified reconstruction receipt.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
import tty

MAX_RPC_BYTES=8*1024*1024
MAX_PART_BYTES=4*1024*1024
MAX_JSON_BYTES=1024*1024
SHA=re.compile(r'[0-9a-f]{64}\Z')
GIT=re.compile(r'[0-9a-f]{40}\Z')


def require(value,message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def encoded(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def read_regular(path,maximum):
    require(path.absolute()==path and path.parent.resolve(strict=True)==path.parent,
            'canonical input path required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        before=os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=maximum,
                'bounded regular single-link input required')
        raw=stream.read(maximum+1);after=os.fstat(stream.fileno())
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) and
            len(raw)==before.st_size,'actual file changed during read')
    return raw


def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def write_fresh(path,raw):
    require(not path.exists() and not path.is_symlink(),'refuse existing output')
    with path.open('xb') as stream:
        require(stream.write(raw)==len(raw),'short output write')
        stream.flush();os.fsync(stream.fileno())


def validate_metadata(metadata):
    required={'schema','kind','repository','immutable_commit','immutable_tree','transport_path',
              'transport_bytes','transport_sha256','transport_git_blob_sha','request'}
    require(isinstance(metadata,dict) and required<=set(metadata),'metadata fields missing')
    require(metadata['schema']=='github-blob-readback-metadata-v1' and
            metadata['kind'] in ('base64-original-part','json-utf8'),'unsupported metadata kind')
    require(isinstance(metadata['repository'],str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',metadata['repository']) and
            GIT.fullmatch(metadata['immutable_commit']) and GIT.fullmatch(metadata['immutable_tree']) and
            SHA.fullmatch(metadata['transport_sha256']) and GIT.fullmatch(metadata['transport_git_blob_sha']),
            'exact immutable metadata identities required')
    relative=PurePosixPath(metadata['transport_path'])
    require(not relative.is_absolute() and relative.parts and '..' not in relative.parts and
            relative.as_posix()==metadata['transport_path'],'safe exact transport path required')
    require(metadata['request']=={'repository_full_name':metadata['repository'],
                                 'blob_sha':metadata['transport_git_blob_sha']},
            'declared fetch_blob arguments differ from expected object')
    require(type(metadata['transport_bytes']) is int and metadata['transport_bytes']>0,'exact payload bytes required')
    if metadata['kind']=='base64-original-part':
        require({'original_bytes','original_sha256'}<=set(metadata) and
                type(metadata['original_bytes']) is int and 0<metadata['original_bytes']<=MAX_PART_BYTES and
                SHA.fullmatch(metadata['original_sha256']) and
                metadata['transport_bytes']==4*((metadata['original_bytes']+2)//3) and
                metadata['transport_path'].endswith('.b64'),'exact bounded original part required')
    else:
        require(metadata['transport_bytes']<=MAX_JSON_BYTES and metadata['transport_path'].endswith('.json'),
                'bounded plain UTF8 JSON payload required')


def payload_and_reconstruction(raw,metadata):
    result=json.loads(raw)
    require(isinstance(result,dict) and result.get('isError',False) is False,'actual GitHub response is an error')
    content=result['structuredContent']['content']
    require(isinstance(content,str),'actual UTF8 blob content missing')
    payload=content.encode('utf-8')
    require(len(payload)==metadata['transport_bytes'] and sha(payload)==metadata['transport_sha256'] and
            git_blob(payload)==metadata['transport_git_blob_sha'],'actual transport bytes/SHA/Git blob differ')
    original=None
    if metadata['kind']=='base64-original-part':
        ascii_payload=content.encode('ascii')
        require(ascii_payload==payload and len(content)==len(payload),'base64 ASCII character/byte extent differs')
        original=base64.b64decode(payload,validate=True)
        require(base64.b64encode(original)==payload and b'\n' not in payload and b'\r' not in payload and
                len(original)==metadata['original_bytes'] and sha(original)==metadata['original_sha256'],
                'canonical actual original part bytes differ')
        token=payload;codec='literal-ascii-base64'
        require(raw.count(token)==1,'literal base64 payload is not unique in original RPC')
    else:
        require(isinstance(json.loads(payload),dict),'plain metadata payload must be a JSON object')
        candidates={}
        for ensure_ascii in (False,True):
            token=json.dumps(content,ensure_ascii=ensure_ascii,separators=(',',':')).encode('utf-8')
            candidates.setdefault(token,'json-string-literal-ensure-ascii-'+str(ensure_ascii).lower())
        matching=[(token,codec) for token,codec in candidates.items() if raw.count(token)==1]
        require(len(matching)==1,'unsupported or ambiguous exact JSON-string representation')
        token,codec=matching[0]
    at=raw.index(token);prefix,suffix=raw[:at],raw[at+len(token):]
    require(prefix+encode_payload(payload,codec)+suffix==raw,'original RPC reconstruction differs')
    return payload,original,prefix,suffix,codec


def encode_payload(payload,codec):
    if codec=='literal-ascii-base64':
        require(payload.decode('ascii').encode('ascii')==payload,'ASCII payload changed')
        return payload
    require(codec in ('json-string-literal-ensure-ascii-false','json-string-literal-ensure-ascii-true'),
            'unknown reconstruction codec')
    return json.dumps(payload.decode('utf-8'),ensure_ascii=codec.endswith('-true'),separators=(',',':')).encode('utf-8')


def verify_output(metadata,raw_rpc,payload_path,output,codec):
    actual_payload=read_regular(payload_path,metadata['transport_bytes'])
    prefix=read_regular(output/'rpc-prefix.bin',MAX_RPC_BYTES)
    suffix=read_regular(output/'rpc-suffix.bin',MAX_RPC_BYTES)
    reconstructed=prefix+encode_payload(actual_payload,codec)+suffix
    require(reconstructed==raw_rpc and sha(reconstructed)==sha(raw_rpc),'persisted prefix/payload/suffix do not reproduce raw RPC')
    payload,original,prefix2,suffix2,codec2=payload_and_reconstruction(reconstructed,metadata)
    require(payload==actual_payload and prefix2==prefix and suffix2==suffix and codec2==codec,
            'reopened response identity differs')
    if original is not None:
        persisted=read_regular(output/'actual-part.bin',MAX_PART_BYTES)
        require(persisted==original,'persisted actual original part differs')
    require(read_regular(output/'rpc-original.raw.json',MAX_RPC_BYTES)==raw_rpc,
            'persisted complete original raw RPC differs')
    return dict(payload_bytes=len(payload),payload_sha256=sha(payload),rpc_bytes=len(reconstructed),
                rpc_sha256=sha(reconstructed),original_bytes=None if original is None else len(original),
                original_sha256=None if original is None else sha(original))


def receive(args):
    require(type(args.rpc_bytes) is int and 0<args.rpc_bytes<=MAX_RPC_BYTES,'bounded RPC byte length required')
    metadata_path=Path(args.metadata).absolute()
    data_root=Path(args.data_root).absolute();payload_path=Path(args.payload_path).absolute()
    output=Path(args.output).absolute()
    require(output.parent.resolve(strict=True)==output.parent and not output.is_relative_to(data_root) and
            not output.exists() and not output.is_symlink(),'fresh receipt directory outside data tree required')
    output.mkdir(mode=0o700);sync_dir(output.parent)
    partial=output/'rpc-original.raw.json.partial';raw_path=output/'rpc-original.raw.json'
    metadata_raw=None;received=0;started=time.monotonic()
    try:
        if os.isatty(0):
            tty.setraw(0)
        with partial.open('xb') as capture:
            print('READY',flush=True)
            remaining=args.rpc_bytes
            while remaining:
                block=os.read(0,min(1024*1024,remaining))
                if not block:
                    raise ValueError('truncated actual RPC stdin')
                require(capture.write(block)==len(block),'short raw RPC capture write')
                capture.flush();os.fsync(capture.fileno())
                received+=len(block);remaining-=len(block)
        os.link(partial,raw_path,follow_symlinks=False);partial.unlink();sync_dir(output)
        raw=read_regular(raw_path,MAX_RPC_BYTES)
        require(len(raw)==args.rpc_bytes==received,'captured raw RPC byte length differs')
        # Preserve every received RPC before validating metadata or publishing payloads.
        metadata_raw=read_regular(metadata_path,1024*1024)
        write_fresh(output/'metadata.json',metadata_raw)
        require(sha(metadata_raw)==args.expected_metadata_sha256,'frozen metadata SHA differs')
        metadata=json.loads(metadata_raw);validate_metadata(metadata)
        write_fresh(output/'declared-request.json',encoded(metadata['request']))
        require(data_root.resolve(strict=True)==data_root and
                payload_path==data_root.joinpath(*PurePosixPath(metadata['transport_path']).parts),
                'payload destination differs from data root plus exact Git path')
        require(not payload_path.exists() and not payload_path.is_symlink(),'refuse existing payload destination')
        payload,original,prefix,suffix,codec=payload_and_reconstruction(raw,metadata)
        payload_path.parent.mkdir(parents=True,exist_ok=True)
        require(payload_path.parent.resolve(strict=True)==payload_path.parent,'payload parent is not canonical')
        write_fresh(payload_path,payload)
        if original is not None:
            write_fresh(output/'actual-part.bin',original)
        write_fresh(output/'rpc-prefix.bin',prefix);write_fresh(output/'rpc-suffix.bin',suffix)
        reopened=verify_output(metadata,raw,payload_path,output,codec)
        require(read_regular(output/'metadata.json',1024*1024)==metadata_raw,'persisted metadata changed')
        receipt=dict(schema='lossless-github-blob-readback-receipt-v1',status='VERIFIED_ACTUAL_RPC_AND_PAYLOAD_BYTES',
            kind=metadata['kind'],metadata_sha256=sha(metadata_raw),repository=metadata['repository'],
            declared_immutable_commit=metadata['immutable_commit'],declared_immutable_tree=metadata['immutable_tree'],
            transport_path=metadata['transport_path'],payload_path=str(payload_path),
            transport_bytes=len(payload),transport_sha256=sha(payload),transport_git_blob_sha=git_blob(payload),
            payload_characters=len(payload.decode('utf-8')),payload_ascii=payload.isascii(),
            rpc_bytes=len(raw),rpc_sha256=sha(raw),prefix_bytes=len(prefix),prefix_sha256=sha(prefix),
            suffix_bytes=len(suffix),suffix_sha256=sha(suffix),reconstruction_codec=codec,
            actual_original_part_bytes=None if original is None else len(original),
            actual_original_part_sha256=None if original is None else sha(original),
            complete_original_rpc_retained=True,original_rpc_byte_equality_verified=True,
            independently_reopened=reopened,elapsed_seconds=time.monotonic()-started,
            scope='Actual returned blob bytes and exact locally saved RPC reconstruction only. Immutable Git provenance remains independently checked by the caller. No native/archive/source or missing-process credit.',
            network_calls=0,native_execution=False,old_downloader_state_changed=False)
        sync_dir(payload_path.parent);sync_dir(output)
        write_fresh(output/'receipt.json',encoded(receipt));sync_dir(output)
        print(json.dumps({'result':'PASS_ACTUAL_BYTES','output':str(output),'payload_path':str(payload_path),
                          'payload_bytes':len(payload),'payload_sha256':sha(payload),'rpc_sha256':sha(raw),
                          'receipt_sha256':sha(encoded(receipt))},sort_keys=True),flush=True)
        return 0
    except Exception as error:
        failure=dict(schema='failed-github-blob-receiver-v1',status='FAILED_NO_COMPLETION_CREDIT',
            metadata_sha256=None if metadata_raw is None else sha(metadata_raw),
            expected_metadata_sha256=args.expected_metadata_sha256,metadata_path=str(metadata_path),
            declared_rpc_bytes=args.rpc_bytes,received_rpc_bytes=received,
            raw_capture=str(raw_path if raw_path.exists() else partial),
            complete_raw_capture=raw_path.exists(),error_type=type(error).__name__,error=str(error),
            payload_may_have_been_published=payload_path.exists(),
            publication_scope='No multi-file atomicity claim. Any published files without a successful receipt are incomplete.',
            native_execution=False,network_calls=0)
        write_fresh(output/'failure.json',encoded(failure));sync_dir(output)
        print(json.dumps({'result':'FAILED_PRESERVED_RAW','output':str(output),
                          'received_rpc_bytes':received,'error_type':type(error).__name__},sort_keys=True),flush=True)
        return 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('metadata','expected-metadata-sha256','output','data-root','payload-path'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--rpc-bytes',required=True,type=int)
    return receive(parser.parse_args())


if __name__=='__main__':
    raise SystemExit(main())
