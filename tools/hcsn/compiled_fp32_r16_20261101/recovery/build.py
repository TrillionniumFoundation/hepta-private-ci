"""Create-only reproducible compiler invocation; never accepts fast-math flags."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parent
SOURCES=('kernel.cpp','arithmetic.hpp','constants.hpp','compiled.py','generate_constants.py','DEVELOPMENT_PROTOCOL.json')
FLAGS=['-std=c++20','-O3','-fvisibility=hidden','-fno-semantic-interposition','-fno-fast-math','-ffp-contract=off','-fno-associative-math','-fno-reciprocal-math',
       '-Wall','-Wextra','-Werror','-pedantic','-fPIC','-shared']


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def run(output,receipt):
    output,receipt=output.resolve(),receipt.resolve()
    if output.exists() or receipt.exists() or output==receipt:raise ValueError('Build outputs must be create-only')
    compiler=shutil.which('g++')
    if compiler is None:raise ValueError('g++ is required')
    before=hashes();command=[compiler,*FLAGS,str(ROOT/'kernel.cpp'),'-o',str(output)]
    start=time.perf_counter();result=subprocess.run(command,capture_output=True,text=True,check=False);seconds=time.perf_counter()-start
    after=hashes();version=subprocess.run([compiler,'--version'],capture_output=True,text=True,check=True).stdout
    data={'schema':'hcsn.compiled-financial-build.v1','command':command,'compiler_version':version,
          'compiler_sha256':hashlib.sha256(Path(compiler).read_bytes()).hexdigest(),'source_sha256_before':before,
          'source_sha256_after':after,'source_unchanged':before==after,'returncode':result.returncode,
          'stdout':result.stdout,'stderr':result.stderr,'wall_seconds':seconds,
          'binary_sha256':hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None,
          'arithmetic_contract':'No fast-math, reassociation, reciprocal substitution or fused contraction; FLT_EVAL_METHOD must equal zero.'}
    with receipt.open('x') as handle:json.dump(data,handle,indent=2);handle.write('\n')
    print(json.dumps({k:data[k] for k in ['returncode','source_unchanged','binary_sha256','wall_seconds']}))
    if result.returncode or before!=after:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args();run(args.output,args.receipt)
