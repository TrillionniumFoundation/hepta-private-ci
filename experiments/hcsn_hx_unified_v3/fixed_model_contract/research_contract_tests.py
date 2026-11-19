"""Finite two-model identity tests; no generic/adversarial certificate claims."""
import ast,hashlib,importlib.util,json,math,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from contract import *
R=Path(__file__).resolve().parent

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def function_ast(path):
 tree=ast.parse(Path(path).read_text());return ast.dump(next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='equity'),include_attributes=False)

class ContractTests(unittest.TestCase):
 def test_two_valid_bundles_and_canonical_order(self):
  for key,row in registry().items():
   d=R/'bundles'/row['name'];c,p=validate_bundle(d);emit(d)
   result=verify_runtime(d);self.assertEqual(result['model_digest'],key)
   runtime=module('runtime_'+row['name'],d/'fastpath.py')
   self.assertEqual(runtime.MODEL,'HX exact rational model sha256:'+key)
   self.assertEqual(runtime.MODEL_DIGEST,digest(runtime.EXACT_PARAMETERS))
   self.assertEqual(runtime.CONTRACT_SHA256,digest(c))
   self.assertEqual(runtime.SCHEMA_VERSION,SCHEMA)
   reordered=dict(reversed(list(c.items())));reordered['exact_params']=dict(reversed(list(c['exact_params'].items())))
   self.assertEqual(canonical(c),canonical(reordered))
   self.assertEqual(render(c,p),render(reordered,p))

 def test_source_and_numerical_receipts_reproduce(self):
  outcomes=[]
  for key,row in registry().items():
   source=(R/row['source_directory']).resolve();dest=R/'replay'/row['name'];dest.mkdir(parents=True,exist_ok=True)
   for name in ('oracle.py','verify_root.py','precompute.py'):
    self.assertEqual(hashlib.sha256((source/name).read_bytes()).hexdigest(),row['source_hashes'][name]);shutil.copyfile(source/name,dest/name)
   for name in ('verify_root.py','precompute.py'):
    run=subprocess.run([sys.executable,str(dest/name)],capture_output=True,text=True,timeout=120)
    (dest/(name+'.log')).write_text(run.stdout+run.stderr)
    self.assertEqual(run.returncode,0)
   for fn,kind,expected in [('ROOT_PROOF.json','root',row['root_receipt_sha256']),('COEFFICIENTS.json','coefficient',row['coefficient_receipt_sha256'])]:
    self.assertEqual(digest(normalized(load_json(dest/fn),kind)),expected)
   outcomes.append({'model_digest':key,'root_and_precompute_exit_zero':True,'nontiming_receipts_match':True})
  (R/'REPLAY_RESULTS.json').write_text(json.dumps(outcomes,indent=2)+'\n')

 def test_default_and_second_numerical_kernel_regression(self):
  results=[]
  for key,row in registry().items():
   source=(R/row['source_directory']).resolve();dest=R/'bundles'/row['name'];verify_runtime(dest)
   old=module('old_'+row['name'],source/'fastpath.py');new=module('new_'+row['name'],dest/'fastpath.py');oracle=module('oracle_'+row['name'],source/'oracle.py');model=oracle.Model(oracle.EXACT)
   self.assertEqual(function_ast(source/'fastpath.py'),function_ast(dest/'fastpath.py'))
   for constant in ('VMIN','VMAX','BHI','BLO','C2','C3','C4','RELATIVE_ERROR_BOUND'):
    self.assertEqual(getattr(old,constant).hex(),getattr(new,constant).hex())
   assets=[float.fromhex(x['asset_hex']) for x in load_json(source/'EVIDENCE.json')['raw_cases']]+[new.VMIN,new.VMAX]
   points=[]
   for v in assets:
    truth=model.local(oracle.float_exact(v));literal=model.literal(oracle.float_exact(v),model.B);value=new.equity(v)
    self.assertEqual(value.hex(),old.equity(v).hex());self.assertTrue(truth>0);self.assertTrue((literal-truth).contains(0))
    error=(oracle.float_exact(value)-truth).abs_upper()/truth.lower();self.assertTrue(error<arb(2)**(-49))
    points.append({'asset_hex':v.hex(),'output_hex':value.hex(),'bit_identical_old_new':True,'relative_error_upper':error.str(85)})
   results.append({'model_digest':key,'kernel_AST_unchanged':True,'constants_unchanged':True,'points':points})
  (R/'NUMERICAL_REGRESSION.json').write_text(json.dumps(results,indent=2)+'\n')

 def test_frozen_negative_matrix(self):
  default=R/'bundles/default';other=R/'bundles/second';records=[]
  def field(file,key,value):
   def mutate(d):
    obj=load_json(d/file);obj[key]=value;(d/file).write_text(json.dumps(obj))
   return mutate
  def nested_param(value):
   def mutate(d):
    c=load_json(d/'CONTRACT.json');c['exact_params']['payout']=value;(d/'CONTRACT.json').write_text(json.dumps(c))
   return mutate
  def missing(file,key):
   def mutate(d):
    c=load_json(d/file);del c[key];(d/file).write_text(json.dumps(c))
   return mutate
  def duplicate(d):
   path=d/'CONTRACT.json';text=path.read_text();path.write_text(text[:-2]+',"schema_version":"'+SCHEMA+'"}\n')
  def jsonnan(d):
   p=d/'CONTRACT.json';p.write_text(p.read_text().replace('"root_precision_bits": 160','"root_precision_bits": NaN'))
  cases=[
   ('wrong_parameters',nested_param('2/25')),
   ('swapped_model_digest',field('CONTRACT.json','model_digest',load_json(other/'CONTRACT.json')['model_digest'])),
   ('cross_root',lambda d:shutil.copyfile(other/'ROOT_PROOF.json',d/'ROOT_PROOF.json')),
   ('cross_coefficients',lambda d:shutil.copyfile(other/'COEFFICIENTS.json',d/'COEFFICIENTS.json')),
   ('wrong_log_domain',field('CONTRACT.json','log_distance_upper','2^-18')),
   ('wrong_endpoint',field('CONTRACT.json','asset_upper_hex','0x1.0p+7')),
   ('weaker_threshold',field('CONTRACT.json','runtime_relative_bound','2^-40')),
   ('schema_version',field('CONTRACT.json','schema_version','unknown')),
   ('proof_version',field('CONTRACT.json','proof_version','unknown')),
   ('flint_version',field('CONTRACT.json','python_flint','0.8.0')),
   ('nonfinite_json',jsonnan),
   ('nonfinite_coefficient',field('COEFFICIENTS.json','relative_error_upper','nan')),
   ('missing_contract',missing('CONTRACT.json','model_digest')),
   ('missing_coefficient',missing('COEFFICIENTS.json','root_hi_hex')),
   ('unknown_coefficient_status',field('COEFFICIENTS.json','status','UNKNOWN')),
   ('unknown_root_status',field('ROOT_PROOF.json','status','UNKNOWN')),
   ('duplicate_contract_key',duplicate),
   ('unknown_contract_field',field('CONTRACT.json','unregistered_field',1)),
   ('unregistered_rational_spelling',nested_param('6/200')),
   ('float_parameter',nested_param(.03)),
   ('oversized_json',lambda d:(d/'CONTRACT.json').write_bytes(b' '*(MAX_JSON_BYTES+1))),
   ('invalid_utf8',lambda d:(d/'CONTRACT.json').write_bytes(b'\xff'))]
  for name,mutate in cases:
   for preexisting in (False,True):
    with self.subTest(name=name,preexisting=preexisting),tempfile.TemporaryDirectory(dir=R) as td:
     d=Path(td)
     for filename in ('CONTRACT.json','ROOT_PROOF.json','COEFFICIENTS.json'):shutil.copyfile(default/filename,d/filename)
     good=(default/'fastpath.py').read_bytes()
     if preexisting:(d/'fastpath.py').write_bytes(good)
     mutate(d)
     try:emit(d)
     except (ValueError,TypeError,KeyError,OverflowError) as exc:reason=type(exc).__name__+': '+str(exc)
     else:self.fail('Invalid bundle emitted: '+name)
     self.assertEqual((d/'fastpath.py').exists(),preexisting)
     if preexisting:self.assertEqual((d/'fastpath.py').read_bytes(),good)
     self.assertFalse(list(d.glob('.runtime-*')))
     records.append({'case':name,'preexisting':preexisting,'rejected':True,'reason':reason,'output_unchanged_or_absent':True})
  # Runtime identity checks inspect bytes, never import altered source.
  for name,old,new in [('runtime_model','MODEL_DIGEST=','MODEL_DIGEST="wrong" #'),('runtime_constant','C2=float.fromhex','C2=2.0 #')]:
   with tempfile.TemporaryDirectory(dir=R) as td:
    d=Path(td)
    for filename in ('CONTRACT.json','ROOT_PROOF.json','COEFFICIENTS.json','fastpath.py'):shutil.copyfile(default/filename,d/filename)
    path=d/'fastpath.py';path.write_text(path.read_text().replace(old,new,1));before=path.read_bytes()
    with self.assertRaises(ContractError):verify_runtime(d)
    self.assertEqual(path.read_bytes(),before)
    records.append({'case':name,'rejected':True,'not_imported':True,'checker_nonmutating':True})
  with tempfile.TemporaryDirectory(dir=R) as td:
   d=Path(td)
   for filename in ('CONTRACT.json','ROOT_PROOF.json','COEFFICIENTS.json','fastpath.py'):shutil.copyfile(default/filename,d/filename)
   path=d/'fastpath.py';changed=path.read_bytes().replace(b'\n',b'\r\n');path.write_bytes(changed)
   with self.assertRaises(ContractError):verify_runtime(d)
   self.assertEqual(path.read_bytes(),changed)
   records.append({'case':'runtime_CRLF_bytes','rejected':True,'not_imported':True,'checker_nonmutating':True})
  self.assertEqual(len(records),47)
  (R/'NEGATIVE_RESULTS.json').write_text(json.dumps(records,indent=2)+'\n')

if __name__=='__main__':unittest.main(verbosity=2)
