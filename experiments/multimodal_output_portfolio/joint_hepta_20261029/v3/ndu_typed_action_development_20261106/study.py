"""Prospective bounded-action frozen-LM/tool development; no independent gain claim."""
import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def append(path, value):
    with Path(path).open('a', encoding='utf8') as stream:
        stream.write(canonical(value).decode()+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def protocol():
    return load(ROOT/'protocol.json')


def source_bytes(name):
    manifest = load(ROOT/'inputs/sources.json')
    row = next(x for x in manifest['files'] if x['local_file'] == name)
    path = ROOT/'inputs/sources'/row.get('storage_file', name)
    data = path.read_bytes()
    if row.get('encoding', 'identity') == 'gzip':
        if hashlib.sha256(data).hexdigest() != row['storage_sha256']:
            raise ValueError('Stored source differs')
        data = gzip.decompress(data)
    if hashlib.sha256(data).hexdigest() != row['sha256']:
        raise ValueError('Source bytes differ')
    return data


def material():
    paths = [ROOT/'study.py', ROOT/'protocol.json'] + sorted((ROOT/'inputs').rglob('*'))
    return {str(p.relative_to(ROOT)): sha(p) for p in paths if p.is_file()}


def freeze():
    save(ROOT/'freeze.json', {'schema':'ndu.typed-action.local-freeze.v1',
         'frozen_at_utc':stamp(), 'model_forwards_observed_for_this_procedure':0,
         'source_sha256':material(), 'external_preregistration':False,
         'prior_development_outcomes_known':True})


def verify_freeze():
    frozen = load(ROOT/'freeze.json')
    if frozen['source_sha256'] != material():
        raise ValueError('Frozen procedure or sources changed')
    return frozen


def verify_model(directory):
    declared = load(ROOT/'inputs/model_manifest.json')
    actual = load(ROOT/'inputs/materialized-model.json')
    if actual['model_id'] != declared['model_id'] or actual['revision'] != declared['revision']:
        raise ValueError('Model identity mismatch')
    records = {x['name']:x for x in actual['files']}
    for row in declared['files']:
        path = directory/row['name']
        if path.is_symlink() or path.stat().st_size != row['bytes']:
            raise ValueError('Wrong model file')
        digest = sha(path)
        if digest != records[row['name']]['sha256']:
            raise ValueError('Materialized model hash mismatch')
        if row.get('sha256') and digest != row['sha256']:
            raise ValueError('Published weight hash mismatch')
        if not row.get('sha256'):
            data = path.read_bytes()
            git = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if git != row['git_blob']:
                raise ValueError('Published model metadata mismatch')
    return declared


def fingerprint(model):
    result = hashlib.sha256()
    for name, parameter in sorted(model.named_parameters()):
        result.update(json.dumps([name, list(parameter.shape), str(parameter.dtype)]).encode())
        result.update(parameter.detach().contiguous().numpy().tobytes())
    return result.hexdigest()


def model_worker(directory):
    started, cpu = time.perf_counter(), time.process_time()
    request = json.load(sys.stdin)
    if set(request) != {'question'} or not isinstance(request['question'], str):
        raise ValueError('Public question only')
    cfg = protocol()
    identity = verify_model(directory)
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        os.environ[name] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(cfg['cpu_threads'])
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(directory, local_files_only=True,
            trust_remote_code=False, use_safetensors=True, dtype=torch.float32,
            attn_implementation='eager')
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    before = fingerprint(model)
    catalog = '\n'.join(f"{x['label']}: {x['tool']}({x['argument']})" for x in cfg['actions'])
    messages = [{'role':'system','content':cfg['system_prompt']},
                {'role':'user','content':'Catalog:\n'+catalog+'\nRequest: '+request['question']+'\nOperation letter:'}]
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True,
              tokenize=True, return_dict=True, return_tensors='pt')
    input_tokens = int(inputs['input_ids'].shape[-1])
    if input_tokens > cfg['max_input_tokens']:
        raise ValueError('Input cap exceeded')
    labels = [x['label'] for x in cfg['actions']]
    tokens = [tokenizer.encode(label, add_special_tokens=False) for label in labels]
    if any(len(x) != 1 for x in tokens):
        raise ValueError('All legal action labels must be exactly one token')
    forward_start = time.perf_counter()
    with torch.inference_mode():
        logits = model(**inputs, use_cache=False).logits[0,-1]
        values = [float(logits[x[0]].item()) for x in tokens]
    forward_seconds = time.perf_counter()-forward_start
    selected = max(range(len(values)), key=lambda i:values[i])
    after = fingerprint(model)
    if before != after:
        raise ValueError('Frozen parameter invariant failed')
    print(json.dumps({'schema':'ndu.frozen-action-decision.v1',
        'model_id':identity['model_id'],'revision':identity['revision'],
        'question_sha256':hashlib.sha256(request['question'].encode()).hexdigest(),
        'prompt_messages':messages,'input_token_ids':inputs['input_ids'][0].tolist(),
        'label_token_ids':dict(zip(labels,[x[0] for x in tokens])),
        'legal_label_logits':dict(zip(labels,values)), 'selected_label':labels[selected],
        'input_tokens':input_tokens, 'decision_output_tokens':1, 'forward_calls':1,
        'parameter_sha256_before':before,'parameter_sha256_after':after,
        'runtime':{'torch':torch.__version__,'transformers':transformers.__version__,'python':sys.version},
        'forward_seconds':forward_seconds,'worker_wall_seconds':time.perf_counter()-started,
        'worker_cpu_seconds':time.process_time()-cpu}, allow_nan=False))


def tool_worker():
    request = json.load(sys.stdin)
    registered = [x for x in protocol()['actions'] if x == request]
    if len(registered) != 1:
        raise ValueError('Only exact catalog actions accepted')
    if request['tool'] == 'table_count':
        db = sqlite3.connect(':memory:')
        try:
            db.executescript(source_bytes('chinook.sql').decode('utf-8-sig'))
            db.execute('PRAGMA query_only=ON')
            name = request['argument']
            answer = db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
        finally:
            db.close()
    else:
        data = source_bytes('statistics.py').decode()
        tree = ast.parse(data)
        nodes = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == request['argument']]
        if len(nodes) != 1:
            raise ValueError('Ambiguous source function')
        answer = data.splitlines()[nodes[0].lineno-1].strip()
        if not answer.endswith(':'):
            raise ValueError('Multiline declaration outside fixed action class')
    print(json.dumps({'answer':answer,'operation':request},allow_nan=False))


def literal_route(question):
    matches = [x for x in protocol()['actions'] if re.search(r'(?<![\w])'+re.escape(x['argument'])+r'(?![\w])',question)]
    return matches[0]['label'] if len(matches) == 1 else None


def private_expected():
    """Separate evaluation only: SQL primary-key rows; source regex, not tool code."""
    cfg = protocol()
    db = sqlite3.connect(':memory:')
    db.executescript(source_bytes('chinook.sql').decode('utf-8-sig'))
    source = source_bytes('statistics.py').decode()
    expected = {}
    for task in cfg['tasks']:
        # Task names are transparent declared target identifiers; model worker never sees this map.
        if task['family'] == 'sqlite_count':
            name = task['question'].split('the ')[-1].split(' table')[0]
            expected[task['task_id']] = len(db.execute('SELECT "'+name+'Id" FROM "'+name+'"').fetchall())
        else:
            name = task['question'].split('for the ')[1].split(' function')[0]
            matches = re.findall(r'^def '+re.escape(name)+r'\([^\n]*\):$',source,re.M)
            if len(matches) != 1:
                raise ValueError('Independent reference signature ambiguous')
            expected[task['task_id']] = matches[0].strip()
    db.close()
    return expected


def supervised(argv, payload, timeout, output, event_context, ledger):
    request_id = uuid.uuid4().hex
    start, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    common = {'request_id':request_id, 'context':event_context, 'argv':argv,
              'payload':payload, 'started_at_utc':stamp(), 'started_monotonic':start}
    append(ledger,dict(common,phase='intent'))
    status = 'failed'
    stdout = stderr = b''
    returncode = None
    try:
        process = subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            stdout,stderr = process.communicate(canonical(payload),timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            stdout,stderr = process.communicate()
            status = 'timeout'
        returncode = process.returncode
        if status != 'timeout' and returncode == 0:
            response = json.loads(stdout)
            status = 'ok'
        else:
            response = None
    except Exception as exc:
        response = None
        stderr += (type(exc).__name__+': '+str(exc)).encode()
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = dict(common,phase='terminal',status=status,returncode=returncode,
            finished_at_utc=stamp(), wall_seconds=time.perf_counter()-start,
            parent_cpu_seconds=time.process_time()-cpu,
            child_cpu_seconds=after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime,
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            external_paid_model_api_calls=0,actual_host_currency_cost=None)
        append(ledger,record)
        save(output/(request_id+'.json'), {'receipt':record,'response':response,'stdout':stdout.decode('utf8',errors='replace'),'stderr':stderr.decode('utf8',errors='replace')})
    return response,record


def run(runtime, model_dir, output):
    cfg = protocol()
    frozen = verify_freeze()
    output.mkdir(parents=True,exist_ok=False)
    ledger = output/'events.jsonl'
    started, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    verification_started = time.perf_counter()
    gold = private_expected()
    verification_preparation_seconds = time.perf_counter()-verification_started
    save(output/'private_expected.json',gold)
    rows=[]
    total_forward_calls=total_tool_calls=0
    for i, task in enumerate(cfg['tasks']):
        arms = cfg['arms'][i%3:]+cfg['arms'][:i%3]
        for arm in arms:
            begin, cpu_begin = time.perf_counter(), time.process_time()
            row={'task_id':task['task_id'],'family':task['family'],'source_cluster':task['source_cluster'],'arm':arm,
                 'started_at_utc':stamp(),'selected_label':None,'delivered':False,'correct':False,
                 'model_calls':0,'tool_calls':0,'failure':None,'raw_response_id':None}
            answer=None
            if arm == 'frozen_lm_selector':
                if total_forward_calls>=cfg['maximum_model_forwards']:
                    raise ValueError('Model budget exhausted')
                row['model_calls']=1
                total_forward_calls+=1
                decision,receipt=supervised([str(runtime),str(ROOT/'study.py'),'model-worker','--model-dir',str(model_dir)],
                     {'question':task['question']},cfg['model_deadline_seconds'],output,{'task_id':task['task_id'],'arm':arm,'stage':'model'},ledger)
                row['raw_response_id']=receipt['request_id']
                row['model_wall_seconds']=receipt['wall_seconds']
                row['model_child_cpu_seconds']=receipt['child_cpu_seconds']
                if decision is None:
                    row['failure']='model_'+receipt['status']
                else:
                    row['selected_label']=decision['selected_label']
            elif arm == 'literal_router':
                row['selected_label']=literal_route(task['question'])
            if row['selected_label'] is not None:
                action=next(x for x in cfg['actions'] if x['label']==row['selected_label'])
                remaining=cfg['episode_deadline_seconds']-(time.perf_counter()-begin)
                if remaining <= 0:
                    row['failure']='deadline_before_tool'
                else:
                    if total_tool_calls>=cfg['maximum_task_tool_dispatches']:
                        raise ValueError('Tool budget exhausted')
                    row['tool_calls']=1
                    total_tool_calls+=1
                    result,receipt=supervised([sys.executable,str(ROOT/'study.py'),'tool-worker'],action,
                         min(remaining,cfg['tool_deadline_seconds']),output,{'task_id':task['task_id'],'arm':arm,'stage':'tool'},ledger)
                    row['tool_request_id']=receipt['request_id']
                    row['tool_wall_seconds']=receipt['wall_seconds']
                    row['tool_child_cpu_seconds']=receipt['child_cpu_seconds']
                    if result is None:
                        row['failure']='tool_'+receipt['status']
                    else:
                        # Deterministic typed delivery. No model rewrite, gold, or parser repair.
                        answer=result['answer']
                        row['delivered']=time.perf_counter()-begin<=cfg['episode_deadline_seconds']
                        row['correct']=row['delivered'] and type(answer) is type(gold[task['task_id']]) and answer==gold[task['task_id']]
            row['answer']=answer
            row['elapsed_seconds']=time.perf_counter()-begin
            row['host_cpu_seconds']=time.process_time()-cpu_begin
            row['finished_at_utc']=stamp()
            rows.append(row)
            save(output/f'episode-{len(rows):02d}.json',row)
            print(json.dumps({k:row[k] for k in ['task_id','arm','selected_label','delivered','correct','elapsed_seconds']}),flush=True)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    unchanged=verify_freeze()==frozen
    summary={arm:{'episodes':sum(x['arm']==arm for x in rows),
       'correct':sum(x['correct'] for x in rows if x['arm']==arm),
       'delivered':sum(x['delivered'] for x in rows if x['arm']==arm),
       'model_calls':sum(x['model_calls'] for x in rows if x['arm']==arm),
       'tool_calls':sum(x['tool_calls'] for x in rows if x['arm']==arm),
       'inclusive_episode_wall_seconds':sum(x['elapsed_seconds'] for x in rows if x['arm']==arm),
       'child_cpu_seconds':sum(x.get('model_child_cpu_seconds',0)+x.get('tool_child_cpu_seconds',0) for x in rows if x['arm']==arm)} for arm in cfg['arms']}
    report={'schema':'ndu.typed-action-development-result.v1','finished_at_utc':stamp(),'protocol_sha256':sha(ROOT/'protocol.json'),
        'freeze':frozen,'source_unchanged':unchanged,'episodes':rows,'arms':summary,
        'model_calls':total_forward_calls,'tool_calls':total_tool_calls,
        'outer_wall_seconds':time.perf_counter()-started,'outer_parent_cpu_seconds':time.process_time()-cpu,
        'outer_children_cpu_seconds':after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime,
        'evaluation_preparation_wall_seconds':verification_preparation_seconds,
        'actual_host_currency_cost':None,'external_paid_model_api_calls':0,
        'source_clusters':2,'independent_confirmation':False,'ndu_algorithm_evaluated':False,
        'historical_failed_results_replaced':False,'scale_decision':'HOLD'}
    report['artifacts_sha256']={str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    save(output/'result.json',report)
    print(json.dumps(summary,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=['freeze','model-worker','tool-worker','run'])
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--model-dir',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.role=='freeze':freeze()
    elif args.role=='model-worker':model_worker(args.model_dir)
    elif args.role=='tool-worker':tool_worker()
    else:run(args.runtime,args.model_dir,args.output)


if __name__=='__main__':main()
