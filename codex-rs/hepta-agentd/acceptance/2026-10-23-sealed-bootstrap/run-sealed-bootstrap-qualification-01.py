from pathlib import Path
base=Path('/home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-3')
exec((base/'work/run-five-lane-qualification-01.py').read_text().split('source=snapshot();')[0])
repo=base/'work/hepta-lease-pair-closure';cwd=repo/'codex-rs'
source=snapshot();(out/'sealed-bootstrap-source-before-01.json').write_text(json.dumps(source,indent=2)+'\n')
def run(name,command):
 start=time.monotonic()
 with (out/(name+'.log')).open('w') as f:r=subprocess.run(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
 (out/(name+'.json')).write_text(json.dumps({'command':command,'exit':r.returncode,'seconds':time.monotonic()-start,'source_before':source,'cache_reused':True,'toolchain':'1.96.0'},indent=2)+'\n');print(name,r.returncode,flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('sealed-bootstrap-scope-tests-01',['/home/qian-qi/.cargo/bin/just','test','-p','codex-hepta-agentd','--lib','--locked','-E','test(deployment_) | test(authority_host_service) | test(authority_host_consumer_frontier) | test(authority_host_wire) | test(root_writer_proof) | test(authority_host_bootstrap_seal) | test(production_composition::objective_sender_tests)','--test-threads','2'])
run('sealed-bootstrap-cli-thin-build-01',[str(tool/'cargo'),'build','-p','codex-hepta-agentd','--bin','hepta-authority-host','--example','authority_host_peer_qualification','--locked'])
after=snapshot();(out/'sealed-bootstrap-source-after-build-01.json').write_text(json.dumps(after,indent=2)+'\n');assert after==source
print('sealed bootstrap scope+build complete; actual Root qualifications separate',flush=True)
