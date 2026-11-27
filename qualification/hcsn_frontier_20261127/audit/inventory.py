"""Inventory all branch-head trees once per distinct (tree, path), independent of topic names."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

def inventory(repo, refs, output):
    started = time.monotonic()
    git = ['git', '--git-dir=' + str(repo)]
    env = {**os.environ, 'GIT_NO_LAZY_FETCH': '1'}
    pipe = subprocess.Popen(git + ['cat-file', '--batch'], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    def read(sha):
        pipe.stdin.write(sha + b'\n')
        pipe.stdin.flush()
        head = pipe.stdout.readline().split()
        if len(head) != 3:
            raise RuntimeError('missing object ' + sha.decode())
        payload = pipe.stdout.read(int(head[-1]))
        assert pipe.stdout.read(1) == b'\n'
        return payload
    def tree(payload):
        pos = 0
        while pos < len(payload):
            sp = payload.index(b' ', pos)
            z = payload.index(b'\0', sp)
            yield payload[pos:sp], payload[sp+1:z], payload[z+1:z+21].hex().encode()
            pos = z + 21
    refs_bytes = refs.read_bytes()
    tips = {row.split()[0] for row in refs_bytes.splitlines()}
    roots = {read(tip).split(b'\n',1)[0].split()[1] for tip in tips}
    tree_cache = {}
    stack = [(root,b'') for root in roots]
    seen = set()
    examples = {}
    by_ext = collections.defaultdict(set)
    gitlinks = set()
    while stack:
        key = sha, path = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        if sha not in tree_cache:
            tree_cache[sha] = list(tree(read(sha)))
        for mode, name, child in tree_cache[sha]:
            full = path + b'/' + name if path else name
            if mode == b'40000':
                stack.append((child, full))
            elif mode == b'160000':
                gitlinks.add(child)
            else:
                old = examples.get(child)
                if old is None or (len(full),full) < (len(old),old):
                    examples[child] = full
                suffix = name.rsplit(b'.', 1)[-1].lower() if b'.' in name else b''
                by_ext[suffix].add(child)
    pipe.stdin.close()
    pipe.wait()
    output.mkdir(exist_ok=True, parents=True)
    extensions = {x:len(v) for x,v in sorted(by_ext.items(),key=lambda q:(-len(q[1]),q[0]))}
    text = {b'py',b'pyi',b'rs',b'hia',b'c',b'cc',b'cpp',b'h',b'hpp',b'cu',b'cuh',b'jl',
            b'ipynb',b'ts',b'tsx',b'js',b'mjs',b'jsx',b'sh',b'bash',b'zsh',b'md',b'tex',
            b'txt',b'rst',b'toml',b'yml',b'yaml',b'go',b'proto',b'swift',b'java',b'kt',b'kts',
            b'html',b'jl',b'r',b'ps1',b'sql',b'bzl',b'bazel',b'csv',b'tsv',b'json',b'jsonl'}
    primary = {b'py',b'pyi',b'rs',b'hia',b'c',b'cc',b'cpp',b'h',b'hpp',b'cu',b'cuh',b'jl',
               b'ipynb',b'ts',b'tsx',b'js',b'mjs',b'jsx',b'sh',b'bash',b'md',b'tex',b'txt',
               b'rst',b'toml',b'yml',b'yaml',b'go',b'proto',b'swift',b'java',b'kt',b'kts',
               b'html',b'r',b'ps1',b'sql',b'bzl',b'bazel'}
    ids = sorted(set().union(*(by_ext[k] for k in text)))
    primary_ids = set().union(*(by_ext[k] for k in primary))
    with (output/'files.tsv').open('wb') as f:
        for sha in ids:
            f.write(b'\t'.join([sha,b'1' if sha in primary_ids else b'0',examples[sha]])+b'\n')
    info = dict(branches=len(refs_bytes.splitlines()),tips=len(tips),roots=len(roots),
                reference_table_sha256=hashlib.sha256(refs_bytes).hexdigest(),
                unique_trees=len(tree_cache),tree_path_pairs=len(seen),unique_blobs=len(examples),
                distinct_gitlinks=len(gitlinks),primary_source_docs=len(primary_ids),data_like_including_primary=len(ids),
                elapsed_s=time.monotonic()-started,
                ext={k.decode('utf8','replace'):v for k,v in extensions.items()})
    (output/'inventory.json').write_text(json.dumps(info,ensure_ascii=False,indent=1)+'\n')
    print({k:v for k,v in info.items() if k!='ext'},flush=True)
    print(list(info['ext'].items())[:35],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('repo','refs','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    inventory(a.repo,a.refs,a.output)
