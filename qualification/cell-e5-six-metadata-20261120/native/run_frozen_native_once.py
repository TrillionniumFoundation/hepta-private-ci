"""Bind the prepared source and identical dependency files around one original replay."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

def main(source_commit, expected_freeze):
    root=Path(__file__).resolve().parent
    path=root/'NATIVE_EXECUTION_FREEZE.json'
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(path)==expected_freeze
    frozen=json.loads(path.read_bytes())
    def check():
        for row in frozen['execution_files']:
            p=root/row['path'];assert p.is_file() and not p.is_symlink() and p.stat().st_size==row['bytes'] and digest(p)==row['sha256'],row['path']
    check()
    with (root/'NATIVE_BINDING_OWNER_LOCK.json').open('x') as stream:
        stream.write(json.dumps({'source_commit':source_commit,'freeze_sha256':expected_freeze,'pid':os.getpid(),'started_at_ns':time.time_ns()})+'\n')
    began=time.perf_counter()
    result=subprocess.run([sys.executable,'-u',str(root/'run_native_once.py'),'--source-commit',source_commit])
    check()
    with (root/'NATIVE_BINDING_RECEIPT.json').open('x') as stream:
        stream.write(json.dumps({'source_commit':source_commit,'freeze_sha256':expected_freeze,'exit_code':result.returncode,'all_frozen_source_and_dependency_files_unchanged':True,'wall_seconds':time.perf_counter()-began,'new_model_calls':0,'new_training_updates':0},indent=2)+'\n')
    return result.returncode

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-commit',required=True);p.add_argument('--expected-freeze-sha256',required=True);a=p.parse_args();raise SystemExit(main(a.source_commit,a.expected_freeze_sha256))
