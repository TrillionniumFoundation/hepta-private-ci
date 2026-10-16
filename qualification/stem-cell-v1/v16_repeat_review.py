"""Read-only second original-model process comparison, never a semantic evaluator."""
import argparse
import json
from v16_literal_witness_reader import read,digest,sealed,SCHEMA


def compare(first,second):
    if first.get('schema')!=SCHEMA+'.actual-original-reader-results' or second.get('schema')!=first['schema']:
        raise ValueError('wrong original Reader run schema')
    for k in ('plan_sha256','model_sha256','tokenizer_sha256','reader_config_sha256','requests','model_forwards'):
        if first.get(k)!=second.get(k):raise ValueError('physical process material/run mismatch: '+k)
    for x in (first,second):
        if (x.get('stronger_reference_reader_executed') is not False
            or x.get('human_verified_sufficiency') is not False
            or x.get('independent_semantic_correctness') is not None
            or x.get('hf_operator_tokenizer_parity') is not False
            or x.get('production_authorized') is not False):
            raise ValueError('forged independent validation')
    a=first['raw_answers'];b=second['raw_answers']
    if type(a)!=dict or type(b)!=dict or set(a)!=set(b) or len(a)!=128:raise ValueError('complete repeated model calls missing')
    keys=('case_id','arm','source_ids','answer_text','answer_sha256','token_ids','input_tokens','output_tokens')
    for key in a:
        if any(a[key].get(k)!=b[key].get(k) for k in keys):
            raise ValueError('the same source and original model produced a different output: '+key)
    return {'schema':SCHEMA+'.original-independent-process-repeat',
            'original_first_answer_sha256':digest(first),
            'original_second_answer_sha256':digest(second),
            'matched_exact_original_request_outputs':len(a),
            'first_physical_forwards':first['model_forwards'],
            'second_physical_forwards':second['model_forwards'],
            'first_cpu_seconds':first['execution_cpu_seconds'],
            'second_cpu_seconds':second['execution_cpu_seconds'],
            'first_wall_seconds':first['execution_wall_seconds'],
            'second_wall_seconds':second['execution_wall_seconds'],
            'original_model_hf_parity_verified':False,
            'independent_semantic_accuracy':None,
            'stronger_reference_reader_executed':False,
            'production_authorized':False,
            'result':'PHYSICAL_BYTES_REPEATABLE_ONLY'}


def main():
    a=argparse.ArgumentParser()
    for k in ('first','second','output'):a.add_argument('--'+k,required=True)
    x=a.parse_args();sealed(x.output,compare(read(x.first),read(x.second)))
    print(json.dumps({'completed':'PHYSICAL_BYTES_REPEATABLE_ONLY'}))

if __name__=='__main__':main()
