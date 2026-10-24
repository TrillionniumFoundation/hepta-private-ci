import unittest,copy,json
from boundary import export_first_query,make_audit_sidecar,BoundaryError,PIN

def fixture():return {'messages':[{'role':'user','content':'Read the named file.'}],'tools':[{'type':'function','function':{'name':'cat','description':'Read a file','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}],'model':'fixture-only','temperature':0,'store':False}
def export(r,**kw):return export_first_query(r,turn_index=kw.get('turn',0),step_index=kw.get('step',0),handler_pin=kw.get('pin',PIN))
class BoundaryTests(unittest.TestCase):
 def test_allowlist_config_removed(self):
  r=fixture();p=export(r);self.assertEqual(set(p),{'messages','tools'});self.assertEqual(p['messages'],r['messages']);self.assertEqual(p['tools'],r['tools'])
 def test_all_privileged_envelopes_rejected(self):
  for k in ['path','missed_function','initial_config','ground_truth','question','id','base_group','state_info','inference_input_log','possible_answer']:
   with self.subTest(k=k):
    r=fixture();r[k]='SECRET_CANARY';self.assertRaises(BoundaryError,export,r)
 def test_nested_message_metadata_rejected(self):
  r=fixture();r['messages'][0]['initial_config']='SECRET_CANARY';self.assertRaises(BoundaryError,export,r)
 def test_nested_tool_metadata_rejected(self):
  for target in ['tool','function','schema']:
   r=fixture();d=r['tools'][0] if target=='tool' else r['tools'][0]['function'] if target=='function' else r['tools'][0]['function']['parameters'];d['ground_truth']='SECRET_CANARY';self.assertRaises(BoundaryError,export,r)
 def test_real_property_named_path_is_retained(self):self.assertIn('path',export(fixture())['tools'][0]['function']['parameters']['properties'])
 def test_dynamic_or_other_handler_rejected(self):
  for kw in [{'turn':1},{'step':1},{'pin':'other'},{'turn':False}]:self.assertRaises(BoundaryError,export,fixture(),**kw)
 def test_non_user_roles_rejected(self):
  for role in ['system','assistant','tool','state_info']:
   r=fixture();r['messages'][0]['role']=role;self.assertRaises(BoundaryError,export,r)
 def test_alias_free(self):
  r=fixture();old=copy.deepcopy(r);p=export(r);p['tools'][0]['function']['name']='changed';self.assertEqual(r,old)
 def test_sidecar_not_payload(self):
  p=export(fixture());side=make_audit_sidecar(source_id='fixture-only',base_group=0,payload_sha256='not-real');self.assertNotIn('source_id',p);self.assertNotIn('base_group',p);self.assertNotEqual(set(p),set(side))
 def test_empty_tools_matches_omission(self):
  r=fixture();r['tools']=[];self.assertNotIn('tools',export(r))
 def test_nonfinite_duplicate_and_unknown_schema(self):
  r=fixture();r['temperature']=float('nan');self.assertRaises(BoundaryError,export,r)
  r=fixture();r['tools']*=2;self.assertRaises(BoundaryError,export,r)
  r=fixture();r['tools'][0]['function']['parameters']['unreviewed']='value';self.assertRaises(BoundaryError,export,r)
 def test_schema_keyword_container_bypasses_rejected(self):
  for key in ['minimum','maximum','exclusiveMinimum','exclusiveMaximum','minItems','maxItems','minLength','maxLength','type','description','format','pattern','title','nullable','optional','enum']:
   with self.subTest(key=key):
    r=fixture();r['tools'][0]['function']['parameters'][key]={'initial_config':'SECRET_CANARY'};self.assertRaises(BoundaryError,export,r)
 def test_schema_keyword_scalar_types(self):
  for key,value in [('minimum',True),('type',['string']),('nullable','true'),('additionalProperties',[]),('enum',[]),('minItems',-1),('maxLength',1.5)]:
   r=fixture();r['tools'][0]['function']['parameters'][key]=value;self.assertRaises(BoundaryError,export,r)
 def test_unhandled_official_response_field_rejects(self):
  r=fixture();r['tools'][0]['function']['response']={'type':'dict','properties':{}};self.assertRaises(BoundaryError,export,r)
 def test_literal_values_are_not_schema_nodes(self):
  for key in ['default','const','enum']:
   r=fixture();value={'initial_config':'ALREADY_VISIBLE_LITERAL'};r['tools'][0]['function']['parameters'][key]=[value] if key=='enum' else value;p=export(r);self.assertIn('ALREADY_VISIBLE_LITERAL',json.dumps(p))
 def test_not_a_semantic_leak_detector(self):
  r=fixture();r['messages'][0]['content']='An upstream leak could be text: SECRET_CANARY';self.assertIn('SECRET_CANARY',export(r)['messages'][0]['content'])
if __name__=='__main__':unittest.main()
