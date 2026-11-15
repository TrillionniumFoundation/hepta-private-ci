"""Native operator/GNU parsers for the new resource v2 evidence gate; stdlib only."""
from decimal import Decimal, InvalidOperation
import re

from metadata_io import digest_bytes, strict_json
from resource_arithmetic import require

NATIVE_WALL, NATIVE_RSS = 1950, 2147483648
THREADS = ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')


def payload(raw):
    for _ in range(6):
        obj=strict_json(raw)
        require(isinstance(obj,dict) and not obj.get('isError') and obj.get('error') is None, 'error/nonobject native wrapper')
        kinds=[k for k in ('raw','result','content') if k in obj]
        require(len(kinds)<=1,'ambiguous native wrapper')
        if not kinds:
            return obj
        kind=kinds[0]
        if kind=='content':
            items=obj[kind]
            require(isinstance(items,list) and len(items)==1 and items[0].get('type')=='text'
                    and isinstance(items[0].get('text'),str),'ambiguous MCP native content')
            raw=items[0]['text'].encode()
        else:
            import json
            raw=json.dumps(obj[kind],allow_nan=False).encode()
    raise ValueError('excessive native wrapper depth')


def number(value,label):
    require(isinstance(value,str) and re.fullmatch(r'\d+(?:\.\d{1,2})?',value) is not None,'invalid GNU '+label)
    try: out=Decimal(value)
    except InvalidOperation as exc: raise ValueError('invalid GNU number') from exc
    require(out.is_finite() and out>=0,'negative/nonfinite GNU '+label)
    return out


def gnu_time(raw,argv):
    text=raw.decode('utf-8',errors='strict')
    labels=('Command being timed','User time (seconds)','System time (seconds)',
            'Elapsed (wall clock) time (h:mm:ss or m:ss)','Maximum resident set size (kbytes)','Exit status')
    found={}
    for line in text.splitlines():
        for label in labels:
            prefix=label+': '
            if line.strip().startswith(prefix):
                require(label not in found,'duplicate GNU field: '+label)
                found[label]=line.strip()[len(prefix):]
    require(set(found)==set(labels),'missing GNU fields')
    require(argv and all(isinstance(a,str) and a and not re.search(r"""[\s'"]""",a) for a in argv),'ambiguous direct argv')
    require(found[labels[0]]=='"'+' '.join(argv)+'"','GNU timed command differs from request')
    user,system=number(found[labels[1]],'user CPU'),number(found[labels[2]],'system CPU')
    clock=found[labels[3]].split(':')
    require(len(clock) in (2,3),'unsupported GNU clock')
    values=[number(v,'elapsed') for v in clock]
    require(all(v==int(v) for v in values[:-1]) and values[-1]<60
            and (len(values)==2 or values[1]<60),'invalid GNU elapsed components')
    elapsed=values[-1]+values[-2]*60+(values[0]*3600 if len(values)==3 else 0)
    require(re.fullmatch(r'\d+',found[labels[4]]) and re.fullmatch(r'\d+',found[labels[5]]),'noninteger GNU RSS/exit')
    peak,code=int(found[labels[4]])*1024,int(found[labels[5]])
    require(code==0 and elapsed+Decimal('.01')<=NATIVE_WALL and peak<=NATIVE_RSS,'native GNU exit/wall/RSS cap failed')
    return {'printed_whole_wall_seconds':float(elapsed),'conservative_wall_upper_seconds':float(elapsed+Decimal('.01')),
            'printed_user_CPU_seconds':float(user),'printed_system_CPU_seconds':float(system),
            'printed_CPU_sum_seconds':float(user+system),'per_field_print_resolution_seconds':.01,
            'peak_RSS_bytes':peak,'returncode':code,'scope':'Whole native direct command, quantized GNU output; not precise wait4.'}


def launch(request,ack,envelope):
    require(request.get('executable')=='/usr/bin/time' and request.get('timeout_seconds')==NATIVE_WALL
            and request.get('cpu_quota_percent')==100 and request.get('memory_max_bytes')==NATIVE_RSS
            and request.get('nice')==10 and request.get('stdin') in (None,''),'native launch contract differs')
    env=request['env']
    require(all(env.get(k)=='1' for k in THREADS) and env.get('CUDA_VISIBLE_DEVICES')==''
            and env.get('PYTHONDONTWRITEBYTECODE')=='1','native thread/device contract differs')
    require(type(ack.get('reused')) is bool and ack.get('launch',{}).get('ok') is True,'valid original/reconciled launch ACK required')
    job=ack['job']
    require(job.get('launch_state')=='launched' and job.get('launch_error') is None,'native launch not acknowledged')
    for key in ('executable','args','cwd','host','idempotency_key'):
        require(job[key]==request[key],'native ACK/request differs: '+key)
    require(sorted(job['env_keys'])==sorted(env),'native ACK environment-key set differs')
    require(job['id']==envelope['native_job_id'] and job['idempotency_key']==envelope['idempotency_key']
            and job['request_digest']==envelope['native_request_digest']
            and all(isinstance(envelope[k],str) and envelope[k] for k in
                    ('native_job_id','idempotency_key','native_request_digest')),'native job/key/digest differs')
    args=request['args']
    require(isinstance(args,list) and len(args)==14 and args[:2]==['-v','-o'] and args[4]=='-B'
            and args[5].endswith('/bootstrap.py') and args[5].startswith('/'),'direct pre-staged bootstrap required')
    require(all(isinstance(a,str) and a and not re.search(r"""[\s'"]""",a) for a in args),'ambiguous native args')
    flags=dict(zip(args[6::2],args[7::2]))
    require(set(flags)=={'--mode','--authorization','--authorization-sha','--output'} and flags['--mode']=='execute'
            and flags['--output']==envelope['expected_output_directory'],'bootstrap execute flags differ')
    return flags,args


def complete_logs(terminal,pages,job_id):
    require(terminal.get('job_id')==job_id and terminal.get('state')=='succeeded' and terminal.get('exit_code')==0
            and all(terminal.get(k) is False for k in ('timed_out','cancelled','automatic_retry'))
            and all(terminal.get(k) is True for k in ('output_complete','output_durable','terminal_publication_confirmed')),
            'successful durable native terminal absent')
    require(pages,'no raw native log pages')
    streams={name:bytearray() for name in ('stdout','stderr')}
    for page in pages:
        require(page['job_id']==job_id,'log belongs to another native job')
        for name,received in streams.items():
            part,total=page[name],terminal['log_bytes'][name]
            require(type(total['stored']) is int and total['stored']>=0 and total['seen']==total['stored']
                    and terminal['log_synced'][name] is True and terminal['log_errors'][name] is None
                    and terminal['log_truncated'][name] is False,'native log incomplete/truncated')
            require(all(type(part[k]) is int for k in ('offset','next_offset','size')),'noninteger native offsets')
            require(isinstance(part['bytes_hex'],str) and re.fullmatch(r'(?:[0-9a-fA-F]{2})*',part['bytes_hex']) is not None,'invalid native hex')
            chunk=bytes.fromhex(part['bytes_hex'])
            require(part['offset']==len(received) and part['next_offset']==len(received)+len(chunk)
                    and part['size']==total['stored'] and part['next_offset']<=part['size']
                    and type(part['eof']) is bool and part['eof']==(part['next_offset']==part['size']),
                    'native log gap/overlap/length/EOF differs')
            received.extend(chunk)
    require(all(pages[-1][name]['eof'] is True and len(data)==terminal['log_bytes'][name]['stored']
                for name,data in streams.items()),'native logs not complete from zero')
    return {name:digest_bytes(bytes(data)) for name,data in streams.items()}

