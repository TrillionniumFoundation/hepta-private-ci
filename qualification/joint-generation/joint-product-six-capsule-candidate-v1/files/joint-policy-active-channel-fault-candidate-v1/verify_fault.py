"""Joint current-live midpoint+fault audit; marker alone is not a checkpoint."""
import json
from common import *
from verify_control import verify

def verify_fault(ready,manifest,clock,before):
 midpoint=verify(ready,manifest['root_instance'],clock)
 ns=midpoint['namespace'];path=SESSION/ns/'control-fault.json'
 raw=path.read_bytes()
 if not 0<len(raw)<=65536:raise ValueError('bounded fault')
 value=json.loads(raw)
 if canonical(value)!=raw or set(value)!={'identity','manifest_sha256','observed_ns','error','disposition'}:raise ValueError('fault schema')
 old=json.loads((SESSION/ns/'piece-01-ack.json').read_bytes())['payload']
 expected={'identity':old['identity'],'manifest_sha256':clock.pin,'observed_ns':value['observed_ns'],'error':'ChannelEOF: EOF before control frame','disposition':'unknown_no_automatic_replay'}
 if type(value['observed_ns'])is not int or not old['observed_ns']<=value['observed_ns']<=clock.live()or value!=expected:raise ValueError('precise active EOF evidence')
 after=inventory();key=ns+'/control-fault.json'
 if key in before or set(after)!=set(before)|{key} or any(after[n]!=v for n,v in before.items()):raise ValueError('only fault journal append allowed')
 if any((SESSION/ns/n).exists()for n in ['piece-02-intent.json','control-observed.json','cancel-intent.json','cancelled.json','control-ack.json']):raise ValueError('no publication or cancellation on EOF')
 return {'schema':'known-result-unknown-control-audit-v1','midpoint':midpoint,'fault':value,'fault_ref':file_ref(path),'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock'),'known_prefix_bytes':8227,'known_generator_result':True,'confirmed_cancel':False,'control_disposition':'unknown_no_automatic_replay'}
