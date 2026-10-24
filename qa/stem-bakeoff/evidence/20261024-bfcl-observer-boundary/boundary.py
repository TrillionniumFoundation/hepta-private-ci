"""Conservative first-query payload boundary, not a raw BFCL task projector.
No provenance authentication, environment capture, model call, or semantic DLP.
"""
import copy,json,math
PIN='6ea57973c7a6097fd7c5915698c54c17c5b1b6c8'
class BoundaryError(ValueError):pass
def require(ok,msg):
 if not ok:raise BoundaryError(msg)
def plain(value,depth=0):
 require(depth<=30,'JSON nesting limit')
 if value is None or type(value) in (str,bool,int):return
 if type(value) is float:require(math.isfinite(value),'nonfinite JSON');return
 if type(value) is list:
  for v in value:plain(v,depth+1)
  return
 if type(value) is dict:
  require(all(type(k) is str for k in value),'nonstring JSON key')
  for v in value.values():plain(v,depth+1)
  return
 raise BoundaryError('non-JSON object')
SCHEMA_KEYS={'type','description','properties','required','items','enum','default','format','additionalProperties','minimum','maximum','exclusiveMinimum','exclusiveMaximum','minItems','maxItems','minLength','maxLength','pattern','nullable','optional','anyOf','oneOf','allOf','title','const'}
def schema(node,depth=0):
 require(type(node) is dict and depth<=20,'invalid schema node')
 require(set(node)<=SCHEMA_KEYS,'unsupported schema keyword')
 for k in ['description','format','pattern','title']:
  if k in node:require(type(node[k]) is str,'invalid string schema keyword')
 if 'type' in node:require(type(node['type']) is str and node['type'] in {'object','array','string','number','integer','boolean','null'},'unsupported schema type')
 for k in ['minimum','maximum','exclusiveMinimum','exclusiveMaximum']:
  if k in node:require(type(node[k]) in (int,float) and (type(node[k]) is int or math.isfinite(node[k])),'invalid numeric schema keyword')
 for k in ['minItems','maxItems','minLength','maxLength']:
  if k in node:require(type(node[k]) is int and node[k]>=0,'invalid nonnegative integer schema keyword')
 for k in ['nullable','optional']:
  if k in node:require(type(node[k]) is bool,'invalid boolean schema keyword')
 if 'enum' in node:require(type(node['enum']) is list and len(node['enum'])>0,'invalid enum array')
 if 'additionalProperties' in node:require(type(node['additionalProperties']) in (bool,dict),'invalid additionalProperties')
 # default/const and individual enum members are JSON literals, not schema nodes.
 # Their contents are already-visible data; this validator is not semantic DLP.
 if 'properties' in node:
  require(type(node['properties']) is dict,'invalid properties')
  for name,child in node['properties'].items():
   require(type(name) is str,'invalid property name');schema(child,depth+1)
 if 'required' in node:require(type(node['required']) is list and all(type(v) is str for v in node['required']),'invalid required')
 if 'items' in node:schema(node['items'],depth+1)
 if type(node.get('additionalProperties')) is dict:schema(node['additionalProperties'],depth+1)
 for k in ['anyOf','oneOf','allOf']:
  if k in node:
   require(type(node[k]) is list,'invalid alternatives')
   for child in node[k]:schema(child,depth+1)

def export_first_query(request,*,turn_index,step_index,handler_pin):
 """Requires trusted acquisition from pinned OpenAI FC handler at call boundary.
 Caller-supplied pin/index are assertions, not proof. Unsupported requests fail closed.
 """
 require(handler_pin==PIN,'unreviewed handler pin')
 require(type(turn_index) is int and type(step_index) is int and turn_index==step_index==0,'only first turn first step')
 plain(request)
 require(type(request) is dict,'request must be dictionary')
 require(set(request)<= {'messages','tools','model','temperature','store'},'unexpected request field')
 require('messages' in request,'missing messages')
 messages=request['messages'];require(type(messages) is list and len(messages)>0,'empty/nonlist messages')
 exported=[]
 for m in messages:
  require(type(m) is dict and set(m)=={'role','content'},'unsupported message fields')
  require(m['role']=='user' and type(m['content']) is str,'only text user messages at first query')
  exported.append({'role':'user','content':m['content']})
 tools=request.get('tools',[]);require(type(tools) is list,'tools must be list');names=set()
 for tool in tools:
  require(type(tool) is dict and set(tool)=={'type','function'} and tool['type']=='function','unsupported tool wrapper')
  fn=tool['function'];require(type(fn) is dict and set(fn)<= {'name','description','parameters','strict'} and {'name','description','parameters'}<=set(fn),'unsupported function fields')
  require(type(fn['name']) is str and fn['name'] and fn['name'] not in names,'duplicate/invalid tool name');names.add(fn['name'])
  require(type(fn['description']) is str,'invalid description');schema(fn['parameters'])
  if 'strict' in fn:require(type(fn['strict']) is bool,'invalid strict')
 payload={'messages':exported}
 if tools:payload['tools']=copy.deepcopy(tools)
 require(len(json.dumps(payload,ensure_ascii=False).encode())<=2_000_000,'payload size limit')
 return payload

def make_audit_sidecar(*,source_id,base_group,payload_sha256):
 """Separate metadata only; never called by payload exporter or merged into payload."""
 require(type(source_id) is str and type(base_group) is int and type(payload_sha256) is str,'bad sidecar metadata')
 return {'source_id':source_id,'base_group':base_group,'payload_sha256':payload_sha256,'handler_pin':PIN,'scope':'boundary validation only; capture provenance not established'}
