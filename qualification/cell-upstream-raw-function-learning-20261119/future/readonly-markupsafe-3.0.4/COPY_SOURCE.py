import importlib.metadata,pathlib,json,hashlib,base64,csv,io,time
started=time.perf_counter();cpu=time.process_time();root=pathlib.Path('/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b/future-dependencies-markupsafe-1');root.mkdir(exist_ok=False)
d=importlib.metadata.distribution('MarkupSafe');assert d.version=='3.0.4';site=pathlib.Path(d.locate_file('')).resolve()
assert str(site)=='/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/lib/python3.12/site-packages'
record=d.read_text('RECORD');entries={r[0]:(r[1],r[2]) for r in csv.reader(io.StringIO(record))}
selected=[p for p in entries if p.startswith('markupsafe/') or p in ['markupsafe-3.0.4.dist-info/METADATA','markupsafe-3.0.4.dist-info/RECORD','markupsafe-3.0.4.dist-info/WHEEL','markupsafe-3.0.4.dist-info/top_level.txt','markupsafe-3.0.4.dist-info/licenses/LICENSE.txt']]
out=root/'site';out.mkdir();rows=[]
for name in sorted(selected):
 rel=pathlib.Path(name);assert not rel.is_absolute() and '..' not in rel.parts
 source=site/rel;assert source.resolve().is_relative_to(site) and not source.is_symlink()
 b=source.read_bytes();h,size=entries[name]
 if h:
  algorithm,value=h.split('=',1);assert algorithm=='sha256';assert base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b'=').decode()==value and len(b)==int(size)
 else:assert name.endswith('/RECORD')
 target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
 rows.append({'path':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'original_installed_path':str(source),'installed_RECORD_verified':bool(h)})
license_path=out/'markupsafe-3.0.4.dist-info/licenses/LICENSE.txt';license_text=license_path.read_text();assert 'Redistribution and use in source and binary forms' in license_text and 'Neither the name' in license_text
value={'schema':'hepta.readonly-existing-distribution-dependency.v1','name':'MarkupSafe','version':'3.0.4','directory':str(out),'files':rows,'source_site_directory':str(site),'source_installed_RECORD_sha256':hashlib.sha256(record.encode()).hexdigest(),'source_is_existing_configured_runtime':True,'source_pypi_wheel_identity_verified':False,'installed_runtime_package_bytes_copied_exactly':True,'excluded_installation_metadata_without_reading_contents':['INSTALLER','REQUESTED','direct_url.json'],'license_expression':'BSD-3-Clause','license_sha256':hashlib.sha256(license_path.read_bytes()).hexdigest(),'new_network_bytes':0,'package_imports_or_install_hooks_executed':False,'model_venv_modified':False,'native_venv_modified':False,'model_calls':0,'native_children':0,'wall_seconds':time.perf_counter()-started,'self_cpu_seconds':time.process_time()-cpu,'purpose':'Original Jinja MarkupSafe>=2.0 dependency only; not a replacement task or training source.'}
p=root/'BUNDLE.json';p.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');print(json.dumps({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'file_count':len(rows),'total_bytes':sum(r['bytes'] for r in rows),'license':license_text}),flush=True)
