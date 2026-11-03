"""Create immutable-ish local delivery receipt. No remote verification implied."""
import hashlib,json,platform,re,sys,zipfile
from pathlib import Path
from datetime import datetime, timezone
import numpy,scipy,mpmath

ROOT=Path(__file__).resolve().parent
OUT=Path('/mnt/data')
TEST_LOG=ROOT/'full_20261031_unittest.log'
text=TEST_LOG.read_text()
m=re.search(r'Ran (\d+) tests in ([0-9.]+)s\s+OK',text)
if not m or int(m.group(1))!=117 or 'FAILED' in text.splitlines()[-1]:
    raise RuntimeError('test log does not certify 117 local successes')
patch=OUT/'HCSN_P0_QVI_HX_20261031_ADD_ONLY.patch'

files={}
paths=[
 'experiments/hcsn_hx_unified_v3/perpetual_put_qvi_reference.py',
 'experiments/hcsn_hx_unified_v3/test_perpetual_put_qvi_reference.py',
 'experiments/hcsn_hx_unified_v3/hx_curvature_necessary.py',
 'experiments/hcsn_hx_unified_v3/test_hx_curvature_necessary.py',
 'docs/research/HCSN_P0_QVI_SUBSET_CERTIFICATE_20261031.md',
 'README.zh-CN.md',
 'P0_NEW_REFERENCE_EVIDENCE_20261031.json',
 'full_20261031_unittest.log',
 'gatebook_20261031.log',
]
sha=lambda b:hashlib.sha256(b).hexdigest()
for f in paths:
    files[f]=sha((ROOT/f).read_bytes())
receipt={
 'schema':'hcsn-offline-research-20261031-v1',
 'target_repository':'TrillionniumFoundation/hepta-private-ci',
 'remote_status':{'github':'403 Sorry. Your account was suspended',
   'current_main_head_verified':False,'current_pr_head_verified':False,
   'remote_commits':0,'remote_prs_created':0,'production_deployed':False},
 'local_execution':{'command':'python -m unittest discover -v -s .',
   'executed_tests':117,'passed':117,'skipped':0,'failed':0,
   'prior_recorded_local_tests':100,'new_p0_tests':17,
   'observed_seconds':float(m.group(2)),
   'python':sys.version.split()[0],'numpy':numpy.__version__,
   'scipy':scipy.__version__,'mpmath':mpmath.__version__},
 'math_scope':{'simplified_global_gbm_put_qvi_proof':True,
   'hx_local_necessary_negative_curvature_rejection':True,
   'hx_full_bond_equity_coupled_fixed_point_proof':False,
   'full_domain_native_low_precision_certification':False},
 'other_phases':{'P1':'only offline statistical tooling, prior results failed',
   'P2':'only local two-state CTMC/causality tooling',
   'P3':'only real asset integrity/full-video decode tests',
   'P4':'no Rust/GPU/Joule benchmark',
   'P5':'no large-scale matched-quality net-benefit result'},
 'admission':{'all_blockers_closed':False,'production_activation_allowed':False,
   'decision':'DENY_ALL_LOCAL_ONLY'},
 'file_sha256':files,
 'add_only_patch_sha256':sha(patch.read_bytes()),
 'add_only_patch_application_tested':True,
}
(ROOT/'EVIDENCE_20261031.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')

archive=OUT/'HCSN_P0_P5_Offline_Research_20261031.zip'
exclude={'build_delivery.py'}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for f in sorted(ROOT.rglob('*')):
        if not f.is_file(): continue
        if '.git' in f.parts or '__pycache__' in f.parts or f.name in exclude:
            continue
        rel=f.relative_to(ROOT)
        info=zipfile.ZipInfo('hcsn_research_20261031/'+rel.as_posix(),date_time=(2026,10,31,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr=(0o644 << 16)
        z.writestr(info,f.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)

with zipfile.ZipFile(archive) as z:
    bad=z.testzip()
    assert bad is None
    assert 'hcsn_research_20261031/EVIDENCE_20261031.json' in z.namelist()
    assert 'hcsn_research_20261031/full_20261031_unittest.log' in z.namelist()
    assert len(z.namelist())>50

summary={
    'archive':str(archive), 'archive_bytes':archive.stat().st_size,
    'archive_sha256':sha(archive.read_bytes()),
    'patch':str(patch),'patch_sha256':sha(patch.read_bytes()),
    'test_count':117, 'new_tests':17,
    'archive_members':len(z.namelist()),
}
(OUT/'HCSN_P0_P5_Offline_Research_20261031_MANIFEST.json').write_text(
    json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
