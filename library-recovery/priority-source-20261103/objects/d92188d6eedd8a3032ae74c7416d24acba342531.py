import subprocess, pathlib, json, concurrent.futures, time
base=pathlib.Path('/mnt/data/hcsn_fullspeed_20261030')
jobs=[
 ('P0_slope_enclosure','/mnt/data/hcsn_work',['experiments.hcsn_hx_unified_v3.test_piecewise_boundary_certificate']),
 ('P1_matched_slope','/mnt/data/hcsn_p1_reconcile',['experiments.hcsn_hx_unified_v3.test_matched_slope','experiments.hcsn_hx_unified_v3.test_slope_alias_gate','experiments.hcsn_hx_unified_v3.test_slope_roundoff_gate','experiments.hcsn_hx_unified_v3.test_slope_guard_composition']),
 ('P2_renewal_check','/mnt/data/hcsn_p2_parent',['experiments.hcsn_distributional_v2.test_renewal_subset_local_ulp_gate','experiments.hcsn_distributional_v2.test_renewal_initial_checkpoint_gate']),
 ('P3_fourmodal_integrity','/mnt/data/hcsn_p3_full_video_20261031',['experiments.hcsn_fourmodal_admission_v1.test_manifest_gate','experiments.hcsn_fourmodal_admission_v1.test_video_full_decode_gate']),
]
def run(job):
 name,cwd,mods=job; cmd=['python','-m','unittest','-v']+mods
 start=time.monotonic()
 try:
  a=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,timeout=70)
  result={'status':'PASS' if a.returncode==0 else 'FAIL','exit_code':a.returncode,'seconds':round(time.monotonic()-start,3),'command':' '.join(cmd),'scope':cwd,'output_tail':(a.stdout+a.stderr)[-1500:]}
 except subprocess.TimeoutExpired as exc:
  result={'status':'TIMEOUT','seconds':round(time.monotonic()-start,3),'command':' '.join(cmd)}
 (base/f'{name}.log').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
 return name,result
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 out=dict(pool.map(run,jobs))
(base/'baseline_results.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
for k,v in out.items():print(k,v['status'],v['seconds'],v.get('output_tail','')[-160:])
