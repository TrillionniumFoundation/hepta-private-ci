#!/usr/bin/env python3
"""Independent archived frozen Laya421 *historical* matched public case reference.

The older run is NOT authenticated production no-change, future utility, or
matched current host lifecycle cost. Never selects a Stem.
"""
from __future__ import annotations
import argparse,hashlib,io,json,math
from pathlib import Path
from zipfile import ZipFile,BadZipFile
ZIP_SHA='e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'
class Invalid(ValueError):pass
def digest(b):return hashlib.sha256(b).hexdigest()
def pairs(entries):
 d={}
 for k,v in entries:
  if k in d:raise Invalid('duplicate JSON')
  d[k]=v
 return d
def parse(raw):return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
def compare(panel,reports,archive):
 if (type(panel) is not dict or panel.get('case_count')!=224 or panel.get('cross_sectional_not_future') is not True or
     type(reports) is not dict or set(reports)!={'granite_97m_r2','mmbert_small','embeddinggemma_2_text'}):
  raise Invalid('wrong public candidate panel')
 panel_sha=digest(canonical(panel));cases=panel['cases'];bycase={c['case_id']:c for c in cases}
 if len(cases)!=224 or len(bycase)!=224:raise Invalid('duplicate public source case')
 if not 0<len(archive)<=2_000_000 or digest(archive)!=ZIP_SHA:raise Invalid('wrong immutable Laya ZIP')
 try:
  with ZipFile(io.BytesIO(archive)) as z:
   infos=z.infolist();names=[x.filename for x in infos]
   if len(names)!=len(set(names)) or sum(x.file_size for x in infos)>8_000_000 or any(
     n.startswith('/') or '\\' in n or '..' in n.split('/') for n in names):raise Invalid('unsafe ZIP')
   original=parse(z.read('stem-laya-physical-arm.json'))
   source=parse(z.read('stem-agnews-source.json'))
 except (BadZipFile,KeyError,TypeError,UnicodeDecodeError) as exc:
  raise Invalid('unreadable historical Laya evidence') from exc
 if (source.get('panel_digest')!=panel_sha or original.get('panel_digest')!=panel_sha or
     original.get('schema')!='hepta.stem.agnews-physical-arm.v1' or original.get('arm_id')!='laya421_frozen' or
     original.get('production_promotion')!='DENY_ALL' or original.get('cross_sectional_not_future') is not True):
  raise Invalid('wrong Laya source/arm/status')
 observed={}
 for row in original['rows']:
  key=row.get('case_id');p=row.get('prob_sports')
  if (key not in bycase or key in observed or bycase[key]['split'] not in ('calibration','test') or
      row.get('split')!=bycase[key]['split'] or row.get('source_digest')!=bycase[key]['source_digest'] or
      row.get('joint_input_digest')!=bycase[key]['joint_input_digest'] or
      type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1):
   raise Invalid('historical per-case identity/probability mismatch')
  observed[key]=float(p)
 if set(observed)!={c['case_id'] for c in cases if c['split'] in ('calibration','test')}:
  raise Invalid('incomplete historical Laya arm')
 test=[c for c in cases if c['split']=='test'];correct=sum((observed[c['case_id']]>=.5)==bool(c['label']) for c in test)
 brier=sum((observed[c['case_id']]-c['label'])**2 for c in test)/len(test)
 comparisons={}
 for model,r in reports.items():
  if r.get('schema')!='hepta.e1-english-public-pretrained-head.v1' or r.get('public_panel_sha256')!=panel_sha or r.get('production_promotion_permitted') is not False:
   raise Invalid('new pilot source changed')
  entries=r['fitting']['controls']['learned_head']['predictions'];pred={x['case_id']:x for x in entries}
  if len(entries)!=96 or len(pred)!=96:raise Invalid('unpaired new Head')
  wins=[0,0]
  for c in test:
   key=c['case_id']
   if key not in pred or pred[key].get('joint_input_digest')!=c['joint_input_digest']:raise Invalid('new Head swapped case')
   v=pred[key].get('positive_probability')
   if type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1:raise Invalid('nonfinite Head probability')
   old=(observed[key]>=.5)==bool(c['label']);new=(v>=.5)==bool(c['label'])
   if old and not new:wins[0]+=1
   if new and not old:wins[1]+=1
  n=sum(wins);pval=min(1.,2.*sum(math.comb(n,k) for k in range(min(wins)+1))/(2**n)) if n else 1.
  comparisons[model]={'historical_laya_only_correct':wins[0],'new_Head_only_correct':wins[1],
                       'unadjusted_mcnemar_p':pval}
 return {'schema':'hepta.e1-historical-laya-triplet.v1','laya_test_cases':64,'laya_test_correct':correct,
         'laya_test_brier':brier,'comparisons':comparisons,
         'historical_reference_is_production_no_change':False,
         'model_origin_independently_authenticated':False,'matched_costs_or_prompt_formats':False,
         'future_ndu_verified':False,'stem_winner_selected':False,
         'authority':'DENY_ALL','production_promotion_permitted':False}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--panel',type=Path,required=True)
 p.add_argument('--historical-laya-zip',type=Path,required=True)
 for model in ('granite_97m_r2','mmbert_small','embeddinggemma_2_text'):
  p.add_argument('--'+model.replace('_','-'),type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 names=('granite_97m_r2','mmbert_small','embeddinggemma_2_text')
 report={name:parse(getattr(args,name).read_bytes()) for name in names}
 panel=parse(args.panel.read_bytes())
 if digest(canonical(panel))!='2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4':
  raise Invalid('changed source panel outside original frozen Laya evidence')
 result=compare(panel,report,args.historical_laya_zip.read_bytes())
 with args.output.open('x',encoding='utf8') as out:json.dump(result,out,sort_keys=True,indent=2,allow_nan=False);out.write('\n')
if __name__=='__main__':main()
