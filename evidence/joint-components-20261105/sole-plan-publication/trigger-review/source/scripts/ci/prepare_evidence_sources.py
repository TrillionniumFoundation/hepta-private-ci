#!/usr/bin/env python3
"""Fetch only missing declared Git objects; never move branches or accept evidence.

A squash merge does not make measured implementation commits ancestors of main.
Object presence is necessary for later byte/tree validation, not a passing result.
"""
from pathlib import Path
import json,re,subprocess
ROOT=Path(__file__).resolve().parents[2]
REMOTE='https://github.com/TrillionniumFoundation/Trillionnium-Chain.git'
BASE_PACKAGES=('pon-v3','pon-v4','pon-evaluation-bundle-v1')
OPTIONAL_PACKAGES=('pon-contract-authority-v1','pon-client-confirmation-v1',
                   'pon-native-session-v1','pon-native-node-v1','pon-closed-round-v1',
                   'pon-public-readiness-v1')
COST_PACKAGES=('pon-contract-authority-v1','pon-native-session-v1',
               'pon-native-node-v1','pon-closed-round-v1','pon-four-priority-audit-v1')
HISTORICAL_COST_MANIFESTS={
    'pon-four-priority-audit-v1':'pon-four-priority-audit-local-observations-v1',
}

def identity(value):
    if not isinstance(value,str) or re.fullmatch('[0-9a-f]{40}',value)is None:
        raise ValueError('invalid measured Git identity')
    return value

def declarations(root, *, source=None):
    """Read fixed root declarations from current files or one exact Git snapshot."""
    root=Path(root).resolve()
    paths=['evidence/'+name+'/'+file for name in BASE_PACKAGES+OPTIONAL_PACKAGES
           for file in ('manifest.json','qualification.json')]
    paths += ['evidence/'+name+'/work-cost/execution.json' for name in COST_PACKAGES]
    paths += ['evidence/'+name+'/manifest.json' for name in HISTORICAL_COST_MANIFESTS]
    objects={}
    if source is not None:
        source=identity(source)
        kind=subprocess.run(['git','cat-file','-t',source],cwd=root,capture_output=True,text=True)
        if kind.returncode or kind.stdout.strip()!='commit':
            raise ValueError('measured source is not a Git commit')
        rows=subprocess.check_output(['git','ls-tree','-r',source,'--',*paths],cwd=root,text=True)
        for row in rows.splitlines():
            metadata,path=row.split('\t',1)
            mode,kind,oid=metadata.split()
            if path in paths:
                if mode not in ('100644','100755') or kind!='blob':
                    raise ValueError('unsafe measured declaration file')
                objects[path]=oid
    def read(relative, *, required=False):
        if source is None:
            path=root/relative
            if path.is_file():return json.loads(path.read_text())
        elif relative in objects:
            return json.loads(subprocess.check_output(['git','cat-file','blob',objects[relative]],cwd=root))
        if required:raise ValueError('missing source declaration: '+relative)
        return None
    # v1 source bytes are also bound by the independently retained mainline archive.
    values={'5d59b9540268914794a62e8fa237caf999499314':'30ee65c0752693f4eecc90f924972279f00c0c73'}
    manifests={}
    # The collector's original commit must remain retrievable after squash publication.
    for name in BASE_PACKAGES+OPTIONAL_PACKAGES:
        data=read('evidence/'+name+'/manifest.json',required=name in BASE_PACKAGES)
        if data is not None:manifests[name]=data
    for data in manifests.values():
        commit=identity(data['implementation_commit']);tree=identity(data['implementation_tree'])
        if commit in values and values[commit]!=tree:raise ValueError('conflicting source tree')
        values[commit]=tree
    # These fixed historical declarations use measured_source_*, not the
    # implementation_* identity of a runtime qualification. Never discover them
    # by scanning arbitrary JSON or promote them to current-source evidence.
    historical_cost_sources={}
    for name,schema in HISTORICAL_COST_MANIFESTS.items():
        data=read('evidence/'+name+'/manifest.json')
        if data is None:continue
        if not isinstance(data,dict) or data.get('schema')!=schema:
            raise ValueError('invalid historical cost manifest schema')
        if not {'measured_source_commit','measured_source_tree'}<=data.keys():
            raise ValueError('incomplete historical cost source pair')
        commit,tree=identity(data['measured_source_commit']),identity(data['measured_source_tree'])
        if commit in values and values[commit]!=tree:raise ValueError('conflicting source tree')
        values[commit]=tree
        historical_cost_sources[name]=(commit,tree)
    # Corpus snapshots are separately declared by these packages' root qualification.
    # Do not infer sources from arbitrary JSON, nested failed runs, or branch names.
    for name in manifests:
        data=read('evidence/'+name+'/qualification.json')
        if data is None:continue
        if not isinstance(data,dict):raise ValueError('invalid source qualification')
        has_commit='input_source_commit' in data;has_tree='input_source_tree' in data
        if not (has_commit or has_tree):continue
        if not (has_commit and has_tree):raise ValueError('incomplete input source pair')
        commit,tree=identity(data['input_source_commit']),identity(data['input_source_tree'])
        if commit in values and values[commit]!=tree:raise ValueError('conflicting source tree')
        values[commit]=tree
    # Cost collections may be newer than the enclosing runtime qualification.
    for package in COST_PACKAGES:
        data=read('evidence/'+package+'/work-cost/execution.json')
        if data is None:continue
        if not isinstance(data,dict) or data.get('schema') != 'pon-native-cost-execution-v1':
            raise ValueError('invalid cost execution schema')
        if not {'source_commit','source_tree'}<=data.keys():
            raise ValueError('incomplete cost source pair')
        commit, tree = identity(data['source_commit']), identity(data['source_tree'])
        if package in historical_cost_sources and historical_cost_sources[package]!=(commit,tree):
            raise ValueError('conflicting historical cost source pair')
        if commit in values and values[commit] != tree:
            raise ValueError('conflicting source tree')
        values[commit] = tree
    return values

def prepare(root=ROOT,run=subprocess.run):
    root=Path(root).resolve();fetched=[]
    declarations_map=declarations(root)
    for commit,tree in declarations_map.items():
        identity(commit);identity(tree)
        found=run(['git','cat-file','-e',commit+'^{commit}'],cwd=root,capture_output=True,text=True)
        if found.returncode:
            fetch=run(['git','fetch','--no-tags','--no-write-fetch-head',REMOTE,commit],cwd=root,capture_output=True,text=True,timeout=90)
            if fetch.returncode:raise ValueError('declared source fetch failed: '+commit)
            fetched.append(commit)
        actual=run(['git','rev-parse',commit+'^{tree}'],cwd=root,capture_output=True,text=True)
        if actual.returncode or actual.stdout.strip()!=tree:raise ValueError('measured tree unavailable or mismatched: '+commit)
    return {'verified_object_trees':declarations_map,'fetched':fetched,'branch_refs_changed':False,'acceptance_granted':False}
if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
