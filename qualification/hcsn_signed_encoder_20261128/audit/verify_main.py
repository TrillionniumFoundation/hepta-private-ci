"""Stream every distinct main-tree blob, verify its Git ID and screen for the research topic."""
import gzip,hashlib,json,os,re,subprocess,sys
from pathlib import Path
repo=Path(sys.argv[1])
out=Path(sys.argv[2])
commit='732e934ba496d90fbe042b8d41d479ef901643e5'
def git(*args,**kwargs):
    return subprocess.check_output(['git','-C',str(repo),*args],**kwargs)
raw=git('ls-tree','-r','-z',commit)
ids={line.split(b'\t',1)[0].split()[2] for line in raw.split(b'\0') if line}
terms={
 'HCSN':rb'\bhcsn\b', 'Hepta Continuous Spiking':rb'hepta[\s_-]+continuous[\s_-]+spik',
 'rollover risk and credit risk':rb'rollover[\s_-]+risk[\s_-]+and[\s_-]+credit[\s_-]+risk',
 'free boundary':rb'free[\s_-]+boundar', 'He Xiong':rb'he[\s_\-]+(?:(?:and|&)[\s_\-]+)?xiong',
 'Chinese HCSN research terms':'连续脉冲网络|自由边界|光滑贴合'.encode()
}
patterns={t:re.compile(reg,re.I) for t,reg in terms.items()}
proc=subprocess.Popen(['git','-C',str(repo),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,env={**os.environ,'GIT_NO_LAZY_FETCH':'1'})
table=bytearray();matches={k:[] for k in patterns};nbytes=0;binary=0
for oid in sorted(ids):
    proc.stdin.write(oid+b'\n');proc.stdin.flush();h=proc.stdout.readline().split()
    assert len(h)==3 and h[:2]==[oid,b'blob']
    b=proc.stdout.read(int(h[2]))
    assert proc.stdout.read(1)==b'\n'
    assert hashlib.sha1(b'blob '+h[2]+b'\0'+b).hexdigest().encode()==oid
    nbytes+=len(b);binary+=int(b'\0' in b)
    table.extend(oid+b'\t'+h[2]+b'\t'+hashlib.sha256(b).hexdigest().encode()+b'\n')
    for t,rg in patterns.items():
        if rg.search(b):matches[t].append(oid.decode())
proc.stdin.close();assert proc.wait()==0
out.mkdir(exist_ok=True)
(out/'main_content_rows.tsv.gz').write_bytes(gzip.compress(bytes(table),mtime=0))
summary={'commit':commit,'blob_paths':len(raw.split(b'\0'))-1,'distinct_blobs':len(ids),'all_payload_bytes_verified':nbytes,'nul_containing_blobs':binary,'per_object_table_sha256':hashlib.sha256(table).hexdigest(),'matched_blob_ids':matches,'patterns':{k:v.decode() for k,v in terms.items()}}
(out/'main_content_receipt.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='patterns'}))
