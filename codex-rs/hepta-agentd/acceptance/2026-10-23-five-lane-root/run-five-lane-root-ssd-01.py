import hashlib,json,os,pathlib,shutil,subprocess,tempfile,time
base=pathlib.Path('/home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-3')
exec((base/'work/run-five-lane-qualification-01.py').read_text().split('source=snapshot();')[0])
source=snapshot(); expected=json.loads((out/'five-lane-source-before-01.json').read_text()); assert source==expected
public=pathlib.Path(tempfile.mkdtemp(prefix='hepta-five-lane-peer-01.',dir='/data')); public.chmod(0o755)
client=public/'authority_host_peer_qualification'; shutil.copyfile(target/'debug/examples/authority_host_peer_qualification',client);client.chmod(0o755)
test=target/'debug/deps/codex_hepta_agentd-376538b093a2091c'
artifacts={'source':source,'test_binary':str(test),'test_sha256':sha(test),'client_binary':str(client),'client_sha256':sha(client),'cli_binary':str(target/'debug/hepta-authority-host'),'cli_sha256':sha(target/'debug/hepta-authority-host'),'prewarmed_complete_bytes_before_authority_clock':True,'source_counter':1,'scope':'Actual original two FinalUse consumers and fixed five lanes, no-effect qualification; controlled stdin public bootstrap is not production sealed loader','production_ready':False}
(out/'five-lane-root-ssd-artifacts-01.json').write_text(json.dumps(artifacts,indent=2)+'\n')
common=['sudo','-n','env','HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=/var/lib/hepta-authority-os3-ssd-20261023','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=/var/lib/hepta-authority-private-os3-ssd-20261023','HEPTA_HOST_AUTHORITY_QUALIFICATION_CLIENT_BIN='+str(client),'HEPTA_SERVICE_WRITER_PROOF=1','HEPTA_SERVICE_CHECKPOINT=1','HEPTA_SERVICE_CONSUMERS=1']
tail=[str(test),'--exact','authority_host_service::tests::root::root_data_service_three_lanes_use_original_wire_key_and_dedicated_peer','--ignored','--nocapture']
for label,extra in [('positive',[]),('expired-consumer',['HEPTA_SERVICE_EXPECT_EXPIRED_CONSUMER=1'])]:
 name='five-lane-root-ssd-'+label+'-01'; bundle=out/(name+'-public-bundle.json'); assert not bundle.exists()
 command=common+extra+['HEPTA_SERVICE_PUBLIC_BUNDLE_OUT='+str(bundle)]+tail
 start=time.monotonic()
 with (out/(name+'.log')).open('w') as f:r=subprocess.run(command,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
 receipt={'command':command,'exit':r.returncode,'seconds':time.monotonic()-start,'artifacts':artifacts,'storage':json.loads((base/'work/root-authority-system-ssd-storage-01.json').read_text()),'production_loader_qualified':False,'clock_horizon_ms':1000,'feed_max_age_ms':500}
 if bundle.exists():
  data=subprocess.check_output(['sudo','-n','cat',str(bundle)]);receipt['public_bundle_sha256']=hashlib.sha256(data).hexdigest();receipt['public_bundle_bytes']=len(data)
 (out/(name+'.json')).write_text(json.dumps(receipt,indent=2)+'\n');print(name,r.returncode,flush=True)
after=snapshot();(out/'five-lane-source-after-root-ssd-01.json').write_text(json.dumps(after,indent=2)+'\n');assert source==after
