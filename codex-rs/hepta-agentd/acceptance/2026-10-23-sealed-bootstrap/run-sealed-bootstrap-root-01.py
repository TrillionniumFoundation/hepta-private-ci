import tempfile,shutil
from pathlib import Path
base=Path('/home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-3')
exec((base/'work/run-five-lane-qualification-01.py').read_text().split('source=snapshot();')[0])
repo=base/'work/hepta-lease-pair-closure';cwd=repo/'codex-rs';source=snapshot()
assert source==json.loads((out/'sealed-bootstrap-source-before-01.json').read_text())
public=Path(tempfile.mkdtemp(prefix='hepta-sealed-bootstrap-peer-01.',dir='/data'));public.chmod(0o755)
client=public/'authority_host_peer_qualification';shutil.copyfile(target/'debug/examples/authority_host_peer_qualification',client);client.chmod(0o755)
test=target/'debug/deps/codex_hepta_agentd-376538b093a2091c'
artifacts={'source':source,'test_binary':str(test),'test_sha256':sha(test),'client_binary':str(client),'client_sha256':sha(client),'cli_binary':str(target/'debug/hepta-authority-host'),'cli_sha256':sha(target/'debug/hepta-authority-host'),'prewarmed_complete_bytes_before_authority_clock':True,'production_ready':False}
(out/'sealed-bootstrap-root-artifacts-01.json').write_text(json.dumps(artifacts,indent=2)+'\n')
common=['sudo','-n','env','HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=/var/lib/hepta-authority-os3-ssd-20261023','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=/var/lib/hepta-authority-private-os3-ssd-20261023','HEPTA_HOST_AUTHORITY_QUALIFICATION_CLIENT_BIN='+str(client),'HEPTA_SERVICE_WRITER_PROOF=1','HEPTA_SERVICE_CHECKPOINT=1','HEPTA_SERVICE_CONSUMERS=1']
service=[str(test),'--exact','authority_host_service::tests::root::root_data_service_three_lanes_use_original_wire_key_and_dedicated_peer','--ignored','--nocapture']
commands=[('custody',['sudo','-n',str(test),'--exact','authority_host_bootstrap_seal::tests::root_descriptor_is_unlinked_sealed_and_never_mutable','--ignored','--nocapture']),('positive',common+service),('expired-consumer',common+['HEPTA_SERVICE_EXPECT_EXPIRED_CONSUMER=1']+service)]
for label,command in commands:
 name='sealed-bootstrap-root-ssd-'+label+'-01';start=time.monotonic()
 with (out/(name+'.log')).open('w') as f:r=subprocess.run(command,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
 (out/(name+'.json')).write_text(json.dumps({'command':command,'exit':r.returncode,'seconds':time.monotonic()-start,'artifacts':artifacts,'production_loader_qualified':False,'stdin_fixture_copies_actual_sealed_bytes_only':True,'clock_horizon_ms':1000,'feed_max_age_ms':500},indent=2)+'\n');print(name,r.returncode,flush=True)
after=snapshot();(out/'sealed-bootstrap-source-after-root-01.json').write_text(json.dumps(after,indent=2)+'\n');assert source==after
