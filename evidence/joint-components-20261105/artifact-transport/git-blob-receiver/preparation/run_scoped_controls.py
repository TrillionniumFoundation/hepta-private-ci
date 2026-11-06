"""Local PTY checks for new payload persistence, JSON encoding, and failure retention.

Uses one already captured actual GitHub RPC; other inputs are explicitly local
fixtures. No remote operation, Git publication, archive qualification, or native
execution. Each output path is fresh and retained for review.
"""
import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parents[1]
RECEIVER=ROOT/'receive_git_blob.py'
OUT=ROOT/'scoped-controls'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def metadata(payload,path,kind,original=None):
    value=dict(schema='github-blob-readback-metadata-v1',kind=kind,
        repository='TrillionniumFoundation/hepta-private-ci',immutable_commit='0'*40,
        immutable_tree='0'*40,transport_path=path,transport_bytes=len(payload),
        transport_sha256=sha(payload),transport_git_blob_sha=blob(payload),
        request=dict(repository_full_name='TrillionniumFoundation/hepta-private-ci',blob_sha=blob(payload)),
        control_provenance='Local byte-persistence control. Zero commit/tree are explicit fixture labels, not actual Git membership or source attribution.')
    if original is not None:value.update(original_bytes=len(original),original_sha256=sha(original))
    return value


def run(name,meta,raw,expected_exit):
    meta_path=OUT/(name+'.metadata.json');meta_raw=enc(meta);meta_path.write_bytes(meta_raw)
    output=OUT/'receipts'/name;payload=OUT/'data'/meta['transport_path']
    argv=[sys.executable,'-B',str(RECEIVER),'--metadata',str(meta_path),
          '--expected-metadata-sha256',sha(meta_raw),'--rpc-bytes',str(len(raw)),
          '--output',str(output),'--data-root',str(OUT/'data'),'--payload-path',str(payload)]
    master,slave=pty.openpty()
    started=time.monotonic();transcript=bytearray();ready=False;written=0
    process=subprocess.Popen(argv,stdin=slave,stdout=slave,stderr=slave,close_fds=True)
    os.close(slave)
    try:
        deadline=time.monotonic()+45
        while process.poll() is None:
            if time.monotonic()>deadline:
                raise RuntimeError('local scoped receiver exceeded its bounded 45-second control')
            readable,writable,_=select.select([master],[master] if ready and written<len(raw) else [],[],0.1)
            if readable:
                try:block=os.read(master,65536)
                except OSError as error:
                    if error.errno!=errno.EIO:raise
                    block=b''
                transcript.extend(block)
                if b'READY\n' in transcript or b'READY\r\n' in transcript:ready=True
            if writable:
                written+=os.write(master,raw[written:written+65536])
        while True:
            readable,_,_=select.select([master],[],[],0)
            if not readable:break
            try:block=os.read(master,65536)
            except OSError as error:
                if error.errno!=errno.EIO:raise
                break
            if not block:break
            transcript.extend(block)
        process.wait(timeout=2)
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate();process.wait(timeout=5)
    (OUT/(name+'.pty.log')).write_bytes(transcript)
    assert ready and written==len(raw)
    assert process.returncode==expected_exit,(name,process.returncode,bytes(transcript)[-1000:])
    assert (output/'rpc-original.raw.json').read_bytes()==raw
    if expected_exit==0:
        receipt=json.loads((output/'receipt.json').read_bytes())
        actual=payload.read_bytes()
        codec=receipt['reconstruction_codec']
        token=actual if codec=='literal-ascii-base64' else json.dumps(actual.decode(),ensure_ascii=codec.endswith('-true'),separators=(',',':')).encode()
        restored=(output/'rpc-prefix.bin').read_bytes()+token+(output/'rpc-suffix.bin').read_bytes()
        assert restored==raw and sha(restored)==receipt['rpc_sha256']
        assert sha(actual)==meta['transport_sha256'] and not (output/'failure.json').exists()
        if meta['kind']=='base64-original-part':
            assert (output/'actual-part.bin').read_bytes()==base64.b64decode(actual,validate=True)
    else:
        failure=json.loads((output/'failure.json').read_bytes())
        assert failure['complete_raw_capture'] and failure['received_rpc_bytes']==len(raw)
        assert not (output/'receipt.json').exists()
    return dict(name=name,exit_code=process.returncode,elapsed_seconds=time.monotonic()-started,
                sent_rpc_bytes=written,original_rpc_sha256=sha(raw),raw_reopened_equal=True,
                pty_log_sha256=sha(bytes(transcript)),output=str(output))


def main():
    OUT.mkdir(exist_ok=False);(OUT/'data').mkdir();(OUT/'receipts').mkdir()
    source=WORKSPACE/'transport-route-probe/large-text-fetch-blob.raw.json'
    actual_raw=source.read_bytes()
    assert len(actual_raw)==5592515 and sha(actual_raw)=='83dd9c92111ee27f957dcb0c4c85b2a0dc3a0c52ea04903289586c79ffb45dfe'
    source_before=sha(actual_raw)
    payload=json.loads(actual_raw)['structuredContent']['content'].encode('ascii')
    original=base64.b64decode(payload,validate=True)
    results=[run('actual_saved_4mib_part',metadata(payload,'archives/H2/parts/control-original-part.b64','base64-original-part',original),actual_raw,0)]
    content=enc({'description':'本地 JSON 控制：é、换行\n与引号 " 保持原 UTF8 字节','value':7})
    raw=json.dumps({'content':[{'type':'text','text':'Action completed.'}],
                    'structuredContent':{'content':content.decode()},'isError':False},ensure_ascii=False,separators=(',',':')).encode()
    meta=metadata(content,'transport-index.json','json-utf8')
    results.append(run('plain_json_payload_and_escape',meta,raw,0))
    bad=metadata(content,'invalid-payload.json','json-utf8');bad['transport_sha256']='0'*64
    results.append(run('wrong_payload_hash_preserves_raw',bad,raw,1))
    assert not (OUT/'data/invalid-payload.json').exists()
    original_saved=(OUT/'data/transport-index.json').read_bytes()
    results.append(run('existing_payload_rejected_and_raw_preserved',meta,raw,1))
    assert (OUT/'data/transport-index.json').read_bytes()==original_saved
    assert sha(source.read_bytes())==source_before
    report=dict(schema='scoped-github-receiver-controls-v1',status='PASS',controls=results,
        receiver_bytes=RECEIVER.stat().st_size,receiver_sha256=sha(RECEIVER.read_bytes()),
        original_saved_actual_rpc=dict(path=str(source),bytes=len(actual_raw),sha256=source_before,unchanged=True),
        scope='Four local PTY controls for new output/error behavior only. The first replays an existing actual tool response; other RPCs and zero commit/tree labels are local fixtures. No new remote/Git read or actual archive membership credit.',
        remote_calls=0,native_executions=0,old_downloaders_touched=False)
    (OUT/'report.json').write_bytes(enc(report));print(json.dumps(report,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
