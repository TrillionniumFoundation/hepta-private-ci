import argparse, copy, importlib.util, json, pathlib, sys, uuid
sys.dont_write_bytecode = True
p=pathlib.Path(__file__).with_name('run-native-owner-history.py')
s=importlib.util.spec_from_file_location('history_oracle',p)
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
owner={'bytes':100,'entry':4096}
old=list(uuid.UUID('12345678-1234-4567-8123-123456789abc').bytes)
new=list(uuid.UUID('22345678-1234-4567-8123-123456789abc').bytes)
other=list(uuid.UUID('32345678-1234-4567-8123-123456789abc').bytes)
cut={'profile':'hepta:cognitive:exact-current-cut:v1','owner_agent_id':m.OWNER,'schema_digest':'1'*64,'state_digest':'2'*64}
payload={'schema_version':1,'delivery':{'boot_id':old,'space_id':[1]*16,'sequence':'0000000000000001'},'manage_slot':2,'manage_generation':1,'expected_revision':2,'period_ns':100000000,'cap_ns':25000000}
head={'schema_version':1,'owner_agent_id':m.OWNER,'phase':'current','proposal':None,'counter':2,'publisher_epoch':1,'last_mutation_sequence':9,'last_current':cut,'peer_lifetime':{'pid':3,'uid':60002,'boot_id':str(uuid.UUID(bytes=bytes(old))),'process_start_ticks':1}}
receipt={'head':head,'candidate':{'current':cut,'payload':json.dumps(payload,separators=(',',':')),'dispatch_count':1,'original_daemon_joined':True,'agent_independent_history':{'state':'applied','previous_revision':2,'revision':3}},'root_resource_observation':{'boot_id':old,'revision':3,'active_cap_ns':25000000,'active_period_ns':100000000},'root_queried_delivery_history':False,'stopped_thread_ids':[3,4]}
prefix=[]
for role in range(1,4):
 prefix += ['[hepta-g2] trusted initial image committed: bytes=100 entry=0x1000',f'[hepta-g1d] trusted role committed: role={role} pid={role}']
prefix += ['[hepta-g1d] initial control activated: manager=1 workload=2 recovery=3 cap_ns=50000000 period_ns=100000000 lease_ns=300000000000 hepta_durability=false']
prefix += [f'HEPTA_NATIVE_BOOT role={role} pid={role} original_owner=true production_ready=false' for role in range(1,4)]
first=['HEPTA_NATIVE_GENESIS_BEGIN original_sqlite=true','HEPTA_NATIVE_GENESIS_COMPLETE original_sqlite=true','HEPTA_NATIVE_AGENT_CREDENTIALS uid=60002 capabilities=0 no_new_privs=true same_image=true','HEPTA_NATIVE_ROOT_SERVICE_BEGIN peer_uid=60002 production_ready=false','HEPTA_NATIVE_ORIGINAL_DAEMON_READY original_app_server=true original_sqlite=true','HEPTA_NATIVE_REPLY_WITHHELD actual_kernel_install=true replay=false']
def raw(item): return ('\n'.join(prefix+first+[m.READY+json.dumps(item)])+'\n').encode()
assert m.crash_receipt(raw(receipt),owner)==receipt
count=1
for label,edit in [
 ('dirty',lambda x:x['head'].update(phase='dirty')),
 ('uncertain publication',lambda x:x['head'].update(proposal={})),
 ('different cut',lambda x:x['candidate'].update(current={})),
 ('duplicate dispatch',lambda x:x['candidate'].update(dispatch_count=2)),
 ('Root history overclaim',lambda x:x.update(root_queried_delivery_history=True)),
 ('missing stopped leader',lambda x:x.update(stopped_thread_ids=[4])),
 ('no applied native history',lambda x:x['candidate']['agent_independent_history'].update(state='history_lost')),
 ('wrong previous revision',lambda x:x['candidate']['agent_independent_history'].update(previous_revision=1)),
 ('wrong applied revision',lambda x:x['candidate']['agent_independent_history'].update(revision=4)),
 ('float previous revision',lambda x:x['candidate']['agent_independent_history'].update(previous_revision=2.0)),
 ('float applied revision',lambda x:x['candidate']['agent_independent_history'].update(revision=3.0)),
 ('wrong resource revision',lambda x:x['root_resource_observation'].update(revision=2)),
 ('float resource revision',lambda x:x['root_resource_observation'].update(revision=3.0)),
 ('foreign old resource boot',lambda x:x['root_resource_observation'].update(boot_id=other))]:
 value=copy.deepcopy(receipt);edit(value)
 try: m.crash_receipt(raw(value),owner)
 except ValueError: count+=1
 else: raise AssertionError(label)
def set_expected_revision(item, revision):
 request=json.loads(item['candidate']['payload']);request['expected_revision']=revision
 item['candidate']['payload']=json.dumps(request,separators=(',',':'))
 successor=revision+1 if isinstance(revision,(int,float)) else 3
 item['candidate']['agent_independent_history'].update(previous_revision=revision,revision=successor)
 item['root_resource_observation']['revision']=successor
for revision in (1,37,2**64-2):
 value=copy.deepcopy(receipt);set_expected_revision(value,revision)
 assert m.crash_receipt(raw(value),owner)==value;count+=1
for label,revision in [('zero',0),('negative',-1),('true',True),('false',False),('float',2.0),('string','2'),('exhausted',2**64-1),('overflow',2**64)]:
 value=copy.deepcopy(receipt);set_expected_revision(value,revision)
 try:m.crash_receipt(raw(value),owner)
 except ValueError:count+=1
 else:raise AssertionError('invalid payload revision '+label)
report={'qualification':'original_retained_current_native_vm_crash_history','production_ready':False,'state':'indeterminate','observation':'unknown','adapter_error':'native boot changed; the old D remains unknown','old_boot_ioctl_issued':False,'dispatch_count_previous_boot':1,'dispatch_count_this_boot':0,'issuer_connected':False,'writer_opened':False,'retirement_attempted':False,'physical_power_loss':False,'current_cut':cut,'exact_payload':receipt['candidate']['payload'],'old_delivery':payload['delivery'],'new_boot_id':new,'new_boot_resource_observation':{'boot_id':new,'revision':7,'active_cap_ns':50000000,'active_period_ns':100000000}}
def second(item,root_head=head,extra=(),root_baseline=None):
 baseline=item['new_boot_resource_observation'] if root_baseline is None else root_baseline
 return ('\n'.join(prefix+list(extra)+['HEPTA_NATIVE_HISTORY_OWNER_REPORT '+json.dumps(item),'HEPTA_NATIVE_HISTORY_COMPLETE '+json.dumps({'root_protected_head':root_head,'owner_report':item,'new_boot_resource_observation':baseline})])+'\n').encode()
assert m.observe_receipt(second(report),owner,receipt)==report;count+=1
for revision in (1,2,2**64-2):
 value=copy.deepcopy(report);value['new_boot_resource_observation']['revision']=revision
 assert m.observe_receipt(second(value),owner,receipt)==value;count+=1
for label,edit in [
 ('same boot',lambda x:x.update(new_boot_id=old)),
 ('new dispatch',lambda x:x.update(dispatch_count_this_boot=1)),
 ('new issuer',lambda x:x.update(issuer_connected=True)),
 ('altered payload',lambda x:x.update(exact_payload='{}')),
 ('kernel HistoryLost overclaim',lambda x:x.update(old_boot_ioctl_issued=True)),
 ('foreign baseline boot',lambda x:x['new_boot_resource_observation'].update(boot_id=other)),
 ('previous boot baseline',lambda x:x.update(new_boot_resource_observation=copy.deepcopy(receipt['root_resource_observation']))),
 ('wrong baseline cap',lambda x:x['new_boot_resource_observation'].update(active_cap_ns=25000000)),
 ('wrong baseline period',lambda x:x['new_boot_resource_observation'].update(active_period_ns=99999999)),
 ('float baseline cap',lambda x:x['new_boot_resource_observation'].update(active_cap_ns=50000000.0)),
 ('float baseline period',lambda x:x['new_boot_resource_observation'].update(active_period_ns=100000000.0)),
 ('extra baseline field',lambda x:x['new_boot_resource_observation'].update(unverified=True))]:
 value=copy.deepcopy(report);edit(value)
 try:m.observe_receipt(second(value),owner,receipt)
 except ValueError:count+=1
 else:raise AssertionError(label)
for label,revision in [('zero',0),('negative',-1),('true',True),('false',False),('float',7.0),('string','7'),('exhausted',2**64-1),('overflow',2**64)]:
 value=copy.deepcopy(report);value['new_boot_resource_observation']['revision']=revision
 try:m.observe_receipt(second(value),owner,receipt)
 except ValueError:count+=1
 else:raise AssertionError('invalid new baseline revision '+label)
for label,edit in [
 ('Root Agent revision disagreement',lambda x:x.update(revision=8)),
 ('Root Agent boot disagreement',lambda x:x.update(boot_id=other)),
 ('Root float baseline revision',lambda x:x.update(revision=7.0)),
 ('Root float baseline cap',lambda x:x.update(active_cap_ns=50000000.0)),
 ('Root extra baseline field',lambda x:x.update(unverified=True))]:
 baseline=copy.deepcopy(report['new_boot_resource_observation']);edit(baseline)
 try:m.observe_receipt(second(report,root_baseline=baseline),owner,receipt)
 except ValueError:count+=1
 else:raise AssertionError(label)
for value in [second(report,{}),second(report,extra=['HEPTA_NATIVE_GENESIS_BEGIN original_sqlite=true']),second(report,root_baseline={})]:
 try:m.observe_receipt(value,owner,receipt)
 except ValueError:count+=1
 else:raise AssertionError('head/genesis negative')
result={'schema':'native-history-oracle-host-check.v1','passed':True,'checks':count,'synthetic_parser_inputs':True,'qemu_executed':False,'native_guest_qualified':False,'runner_sha256':m.common.file_digest(p),'test_sha256':m.common.file_digest(pathlib.Path(__file__)),'fixture_expected_revision':2,'fixture_applied_revision':3,'fixture_new_boot_baseline_revision':7}
parser=argparse.ArgumentParser(description='Synthetic parser regression only; no native guest.')
parser.add_argument('--output',type=pathlib.Path)
args=parser.parse_args()
if args.output:
 with args.output.open('x') as stream: stream.write(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
