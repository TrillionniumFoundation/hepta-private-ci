"""Hand-built raw transport and GNU fixtures. No native command is started."""
import copy
import json
import unittest
from native_parsers import complete_logs,gnu_time,launch,payload


def native_request():
    args=['-v','-o','/synthetic/time.txt','/synthetic/python','-B','/synthetic/bootstrap.py',
          '--mode','execute','--authorization','/synthetic/auth.json','--authorization-sha','a'*64,'--output','/synthetic/out']
    request={'host':'synthetic','executable':'/usr/bin/time','args':args,'cwd':'/synthetic',
        'idempotency_key':'synthetic-once','timeout_seconds':1950,'cpu_quota_percent':100,
        'memory_max_bytes':2147483648,'nice':10,
        'env':dict(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',
                   CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1')}
    job={k:request[k] for k in ('host','executable','args','cwd','idempotency_key')}
    job.update(id='synthetic-job',request_digest='b'*64,request_fingerprint=1088882175884290006,
               launch_state='launched',launch_error=None,env_keys=list(request['env']))
    return request,{'job':job,'launch':{'ok':True},'reused':False},{'native_job_id':'synthetic-job',
        'idempotency_key':'synthetic-once','native_request_digest':'b'*64,'expected_output_directory':'/synthetic/out'}


def gnu(args,elapsed='1:02.03'):
    return ('\tCommand being timed: "'+' '.join(args)+'"\n'
            '\tUser time (seconds): 12.34\n\tSystem time (seconds): 1.23\n'
            '\tElapsed (wall clock) time (h:mm:ss or m:ss): '+elapsed+'\n'
            '\tMaximum resident set size (kbytes): 1000\n\tExit status: 0\n').encode()


def log_fixture():
    terminal={'job_id':'synthetic-job','state':'succeeded','exit_code':0,'timed_out':False,'cancelled':False,
        'automatic_retry':False,'output_complete':True,'output_durable':True,'terminal_publication_confirmed':True,
        'log_bytes':{'stdout':{'seen':6,'stored':6},'stderr':{'seen':0,'stored':0}},
        'log_synced':{'stdout':True,'stderr':True},'log_errors':{'stdout':None,'stderr':None},
        'log_truncated':{'stdout':False,'stderr':False}}
    pages=[]
    for offset,data in ((0,b'abc'),(3,b'def')):
        pages.append({'job_id':'synthetic-job','stdout':{'offset':offset,'next_offset':offset+3,
            'size':6,'bytes_hex':data.hex(),'eof':offset==3},
            'stderr':{'offset':0,'next_offset':0,'size':0,'bytes_hex':'','eof':True}})
    return terminal,pages


class NativeParserTests(unittest.TestCase):
    def test_raw_wrapper_preserves_full_integer_and_rejects_ambiguity(self):
        request,ack,envelope=native_request()
        raw=json.dumps({'result':{'content':[{'type':'text','text':json.dumps(ack)}]}}).encode()
        self.assertEqual(payload(raw)['job']['request_fingerprint'],1088882175884290006)
        for bad in (b'{"raw":{},"result":{}}',b'{"isError":true}',b'{"a":NaN}',b'{"a":1,"a":2}',
                    b'{"content":[{"type":"text","text":"{}"},{"type":"text","text":"{}"}]}'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):payload(bad)

    def test_GNU_full_command_and_quantized_upper_wall(self):
        request,_,_=native_request();args=request['args'][3:]
        result=gnu_time(gnu(args),args)
        self.assertEqual(result['printed_whole_wall_seconds'],62.03)
        self.assertEqual(result['conservative_wall_upper_seconds'],62.04)
        self.assertEqual(gnu_time(gnu(args,'0:32:29.99'),args)['conservative_wall_upper_seconds'],1950.)
        with self.assertRaises(ValueError):gnu_time(gnu(args,'32:30.00'),args)

    def test_GNU_duplicate_missing_nonfinite_or_wrong_command_refused(self):
        request,_,_=native_request();args=request['args'][3:];good=gnu(args)
        bads=[good+b'User time (seconds): 1.00\n',good.replace(b'12.34',b'NaN'),
              good.replace(b'Exit status: 0',b'Exit status: 1'),
              good.replace(b'1000\n',b'2097153\n'),good.replace(b'/synthetic/python',b'/different/python'),
              good.replace(b'\tSystem time (seconds): 1.23\n',b'')]
        for bad in bads:
            with self.subTest(bad=bad[-80:]),self.assertRaises(ValueError):gnu_time(bad,args)

    def test_original_first_ACK_binds_request_without_using_file_SHA_as_digest(self):
        request,ack,envelope=native_request()
        flags,args=launch(request,ack,envelope)
        self.assertEqual(flags['--mode'],'execute')
        self.assertEqual(args[2],'/synthetic/time.txt')
        changed=copy.deepcopy(ack); changed['job']['request_fingerprint']=0
        self.assertEqual(launch(request,changed,envelope)[0],flags)  # Opaque fingerprint deliberately unused.

    def test_reused_mismatched_limited_or_inline_launch_refused(self):
        for fault in ('reuse_type','digest','limits','inline','thread','cwd'):
            request,ack,envelope=native_request()
            if fault=='reuse_type':ack['reused']='true'
            if fault=='digest':envelope['native_request_digest']='wrong'
            if fault=='limits':request['cpu_quota_percent']=600
            if fault=='inline':request['args'][5]='-c'
            if fault=='thread':request['env']['OMP_NUM_THREADS']='2'
            if fault=='cwd':ack['job']['cwd']='/wrong'
            with self.subTest(fault=fault),self.assertRaises(ValueError):launch(request,ack,envelope)

    def test_contiguous_complete_hex_pages_are_bound(self):
        terminal,pages=log_fixture()
        result=complete_logs(terminal,pages,'synthetic-job')
        self.assertEqual(result['stdout']['bytes'],6)
        self.assertEqual(result['stderr']['bytes'],0)

    def test_log_gap_overlap_earlyEOF_or_missing_tail_refused(self):
        for fault in ('gap','overlap','eof','missing','truncated','different_job'):
            terminal,pages=log_fixture()
            if fault=='gap':pages[1]['stdout']['offset']=4
            if fault=='overlap':pages[1]['stdout']['offset']=0
            if fault=='eof':pages[0]['stdout']['eof']=True
            if fault=='missing':pages.pop()
            if fault=='truncated':terminal['log_truncated']['stdout']=True
            if fault=='different_job':pages[0]['job_id']='other'
            with self.subTest(fault=fault),self.assertRaises(ValueError):complete_logs(terminal,pages,'synthetic-job')


if __name__=='__main__':
    unittest.main()

