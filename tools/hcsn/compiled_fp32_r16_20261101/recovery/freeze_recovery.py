"""Prepare new independently seeded cases and source/runner seals; no evaluation."""
import argparse,hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import scipy
from build import SOURCES,FLAGS
ROOT=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run():
    manifest_path=ROOT/'RECOVERY_CASES_V1.json';protocol_path=ROOT/'RECOVERY_PROTOCOL_V1.json'
    if manifest_path.exists() or protocol_path.exists():raise ValueError('Freeze files are create-only')
    lower=np.asarray([.04,.01,.08,0,0,1e-4,.01,.5,20]);upper=np.asarray([.15,.2,.8,1,.6,.1,20,10,100])
    seed,n=2026110127,128;rng=np.random.default_rng(seed);u=np.column_stack([(rng.permutation(n)+rng.random(n))/n for _ in range(9)])
    values=lower+(upper-lower)*u
    for col in (5,6):values[:,col]=np.exp(np.log(lower[col])+(np.log(upper[col])-np.log(lower[col]))*u[:,col])
    manifest={'schema':'hcsn.recovery-independent-inputs.v1','seed':seed,'rows':[{'id':f'recovery_{i:03d}','theta':t.tolist()} for i,t in enumerate(values.astype(np.float32))]}
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    names=[*SOURCES,'build.py','recovery_eval.py','recovery_check.py','freeze_recovery.py','frozen_input/frozen_reference.py']
    protocol={'schema':'hcsn.recovered-compiled-independent-protocol.v1','frozen_utc':datetime.now(timezone.utc).isoformat(),
              'source_checkpoint':'4e97fd84fa1d78e96a96b408b0698f40f362ce88','source_branch':'research/hcsn-compiled-r16-recovery-20261101',
              'source_sha256':{name:sha(ROOT/name) for name in names},'binary_sha256':sha(ROOT/'recovered.so'),
              'build_receipt_sha256':sha(ROOT/'RECOVERED_BUILD.json'),'manifest_sha256':sha(manifest_path),
              'compiler_flags':FLAGS,'compiler_version':json.loads((ROOT/'RECOVERED_BUILD.json').read_text())['compiler_version'],
              'generation':{'seed':seed,'points':n,'algorithm':'Independent PCG64 jittered Latin hypercube; quantize once to binary32',
                            'lower':lower.tolist(),'upper':upper.tolist(),'log_scaled_columns':[5,6]},
              'states':['log_distance0: continuation-side right derivative','log_distance.75*min(.002,.02*sigma*sqrt(m),.05/(1+abs(a)+zt))',
                        'log_distance1','asset b_mp*(1-1e-6)','asset b_mp*(1+1e-6)','asset100'],
              'validity':'Independent literal MP80 boundary finite and positive; flow < -64*eps32*max(1,scale). All128 points and all768 rows must be resolvable for full admission. Any rejection/error remains explicit and prevents full pass.',
              'gates':{'float64':{'value_scaled':2e-8,'jacobian_scaled':2e-5},'float32':{'value_scaled':8e-7,'jacobian_scaled':2e-5},'compensated32':{'value_scaled':8e-7,'jacobian_scaled':2e-5}},
              'reference':{'digits':80,'steps':['1e-18','5e-19'],'halving_scaled_gate':1e-12,'encoding':'Archived decimal-roundtrip convention for quantized FP32 inputs'},
              'checker':'Independent second MP80 evaluation of every5-output/5x10 Jacobian, exact stored-reference consistency, branch-neighbor and right-derivative checks. Strict identity/count/shape/finite/status and source/binary/input/reference seals. Never trusts writer pass/error summaries.',
              'required_modes':['float64','compensated32'],'ordinary_float32_failures':'Retain complete identities/status and numerical failures; never count a rejection as a numerical pass or silently remove it. Does not confer ordinary-FP32 admission.',
              'precision':'Financial candidate uses two float32 words per primal/tangent; extended significand, not ordinary FP32. Native-double baseline, fixed constants, independent reference and exact output transport may use double.',
              'loss_disclosure':'Original pre-reset768 raw rows,36 timing batches and full protocol bytes were lost before upload. Executable was reconstructed byte-exactly but original independent admission is not inherited. This is a new protocol/new sample.',
              'recovery_binary_matches_pre_reset':sha(ROOT/'recovered.so')=='a96fbe8ee36be2fdaa2a5894462f415f9724acf199ae31745c471092c26f6615',
              'retuning':'No retuning on opened new outcomes. Changes require another version and newly frozen independent cases; opened sets become regression only.',
              'environment':{'python':sys.version.split()[0],'numpy':np.__version__,'scipy':scipy.__version__,'oracle_package':'mpmath==1.3.0'},
              'claim_scope':'Finite CPU numerical validation only; no global C1 for F/G/debt, no uniform box theorem, no ordinary-FP32, GPU, energy or network-task/training admission.'}
    protocol_path.write_text(json.dumps(protocol,indent=2)+'\n')
    print(json.dumps({'protocol_sha256':sha(protocol_path),'manifest_sha256':sha(manifest_path),'binary_sha256':protocol['binary_sha256']}))
if __name__=='__main__':run()
