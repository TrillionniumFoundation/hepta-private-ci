"""Audit named editors in recorded repository candidate paths and available HCSN research sources."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def main(scope,git,out):
    named=re.compile(rb'(?<![A-Za-z])(?:Alpha[-_ ]?Edit|Crisp[-_ ]?Edit|Steer[-_ ]?2[-_ ]?Edit|MEMIT|EMMET)(?![A-Za-z])',re.I)
    cohort=re.compile(r'hcsn|spiking|model[_-]?edit|weight[_-]?edit|forward[_-]?projection|knowledge[_-]?edit',re.I)
    paths={};named_paths=[];all_rows=0
    for row in scope.open():
        oid,_,path=row.rstrip('\n').split('\t',2);all_rows+=1
        if named.search(path.encode()):named_paths.append((oid,path))
        if cohort.search(path) and Path(path).suffix.lower() in ('.md','.py','.rs','.cc','.cpp','.toml','.yaml','.yml','.txt','.sh','.ipynb'):
            paths[oid]=path
    cmd=['git','--git-dir='+str(git),'cat-file'];env=dict(os.environ,GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    objects=subprocess.run(cmd+['--batch-check'],input='\n'.join(paths)+'\n',capture_output=True,env=env,text=True,check=True)
    screened=0;missing=0;oversize=0;hits=[];byte_count=0
    with subprocess.Popen(cmd+['--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,env=env) as p:
        for line in objects.stdout.splitlines():
            bits=line.split()
            if bits[-1]=='missing':missing+=1;continue
            h,kind,n=bits
            if kind!='blob' or int(n)>2_000_000:oversize+=1;continue
            p.stdin.write((h+'\n').encode());p.stdin.flush()
            _,_,size=p.stdout.readline().split();value=p.stdout.read(int(size));assert p.stdout.read(1)==b'\n'
            matches=sorted({v.decode(errors='replace') for v in named.findall(value)})
            if matches:hits.append(dict(sha=h,path=paths[h],mentions=matches))
            screened+=1;byte_count+=len(value)
        p.stdin.close()
    out.write_text(json.dumps(dict(scope=str(scope),historical_candidates=all_rows,named_paths=named_paths,
        eligible_research_text=len(paths),available_screened=screened,research_text_bytes=byte_count,missing=missing,
        oversized=oversize,name_matches=hits,pattern=named.pattern.decode(),cohort=cohort.pattern),indent=1)+'\n')
    print(all_rows,len(paths),screened,missing,oversize,len(hits),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('scope','git','out'):p.add_argument(n,type=Path)
    a=p.parse_args();main(a.scope,a.git,a.out)
