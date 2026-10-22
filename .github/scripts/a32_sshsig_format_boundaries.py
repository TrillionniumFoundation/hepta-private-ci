"""Exact reviewed formatter boundary helpers, not the original executable main.

Source a32_native_rustfmt.py SHA256
266d391ef2a9f7ff7892307f2e278d558cf3f3263173e81ef99169ccb2b3b3cf.
The six function bodies below are byte-identical reviewed source extractions.
"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess

def blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def git(repo,*args):
    return subprocess.check_output(['git','--no-replace-objects',*args],cwd=repo)


def inventory(repo, expected_sha, expected_tree):
    assert git(repo,'rev-parse','HEAD').decode().strip()==expected_sha
    assert git(repo,'rev-parse','HEAD^{tree}').decode().strip()==expected_tree
    rows=git(repo,'ls-tree','-rz','--full-tree','HEAD').split(b'\0')
    result={}
    for row in rows:
        if not row:continue
        left,path=row.split(b'\t',1)
        mode,kind,digest=left.decode().split()
        assert kind=='blob' and mode in ('100644','100755','120000'),(mode,kind,path)
        result[os.fsdecode(path)]={'mode':mode,'blob':digest}
    return result


def snapshot(repo, entries):
    result={}
    for path,entry in entries.items():
        p=repo/path
        assert not any(parent.is_symlink() for parent in p.parents if parent!=repo and repo in parent.parents),f'symlink ancestor: {path}'
        if entry['mode']=='120000':
            assert p.is_symlink(),path
            data=os.fsencode(os.readlink(p)); mode='120000'
        else:
            assert p.is_file() and not p.is_symlink(),path
            data=p.read_bytes();mode='100755' if p.stat().st_mode&stat.S_IXUSR else '100644'
        result[path]={'mode':mode,'blob':blob(data),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    return result


def tree_hash(entries):
    root={}
    for path,item in entries.items():
        node=root;parts=path.split('/')
        for part in parts[:-1]:node=node.setdefault(part,{})
        node[parts[-1]]=(item['mode'],item['blob'])
    def visit(node):
        values=[]
        for name,value in node.items():
            mode,digest=('40000',visit(value)) if isinstance(value,dict) else value
            values.append((name.encode()+(b'/' if mode=='40000' else b''),mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(digest)))
        data=b''.join(v for _,v in sorted(values))
        return hashlib.sha1(b'tree '+str(len(data)).encode()+b'\0'+data).hexdigest()
    return visit(root)


def boundary(repo,sha,tree,entries):
    assert inventory(repo,sha,tree)==entries,'HEAD/tree changed'
    stage={}
    for row in git(repo,'ls-files','--stage','-z').split(b'\0'):
        if not row:continue
        left,path=row.split(b'\t',1);mode,digest,number=left.decode().split();path=os.fsdecode(path)
        assert number=='0' and path not in stage,'non-stage-0 or duplicate index entry'
        stage[path]={'mode':mode,'blob':digest}
    assert stage==entries,'index path/mode/blob inventory differs from HEAD'
    assert not git(repo,'diff','--cached','--name-only'),'index changed'
    assert not git(repo,'ls-files','--others','-z'),'untracked checkout additions'
    # Direct byte checks never trust an apparently clean hidden index.
    flags=git(repo,'ls-files','-v','-f','-z').split(b'\0')
    assert all(not r or (r[:1]==b'H') for r in flags),'hidden/unmerged index flags'
