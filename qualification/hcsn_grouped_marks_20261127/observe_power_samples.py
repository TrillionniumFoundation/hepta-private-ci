"""Record deduplicated native NVML total GPU power samples in 12-byte little-endian rows."""
import ctypes as C
import fcntl
import json
import os
from pathlib import Path
import struct
import time


class Value(C.Union):
    _fields_=[('ui',C.c_uint),('ull',C.c_ulonglong),('d',C.c_double)]


class Sample(C.Structure):
    _fields_=[('timestamp',C.c_ulonglong),('value',Value)]


def main():
    base=Path(os.environ['HCSN_GROUPED_STUDY']).resolve();out=base/'board_observations';out.mkdir(exist_ok=True)
    lock=(out/'native_power.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    nv=C.CDLL('libnvidia-ml.so.1');assert nv.nvmlInit_v2()==0
    device=C.c_void_p();assert nv.nvmlDeviceGetHandleByIndex_v2(0,C.byref(device))==0
    call=nv.nvmlDeviceGetSamples
    call.argtypes=[C.c_void_p,C.c_int,C.c_ulonglong,C.POINTER(C.c_int),C.POINTER(C.c_uint),C.POINTER(Sample)]
    path=out/'native_total_power.bin';row=struct.Struct('<QI');last=0
    if path.exists() and path.stat().st_size:
        assert path.stat().st_size%row.size==0
        with path.open('rb') as f:f.seek(-row.size,2);last,_=row.unpack(f.read(row.size))
    begin=time.monotonic();reported=False;vtype=C.c_int();data=(Sample*1024)()
    metadata={'source':'nvmlDeviceGetSamples, NVML_TOTAL_POWER_SAMPLES = 0','format':'<QI little-endian uint64 CPU epoch microseconds and uint32 GPU total power in milliwatts','process_exclusivity':'unverified, includes desktop and other contexts','device_index':0,'sample_value_type_unsigned_int':1}
    (out/'native_power_metadata.json').write_text(json.dumps(metadata,sort_keys=True)+'\n')
    with path.open('ab') as f,(out/'native_power_errors.jsonl').open('a',buffering=1) as err:
        while time.monotonic()-begin<20*3600:
            count=C.c_uint(len(data));rc=call(device,0,last,C.byref(vtype),C.byref(count),data)
            if rc==0:
                assert vtype.value==1
                for s in sorted(data[:count.value],key=lambda v:v.timestamp):
                    if s.timestamp<=last:continue
                    assert abs(s.timestamp/1e6-time.time())<15 and s.value.ui<1000000
                    f.write(row.pack(s.timestamp,s.value.ui));last=s.timestamp
                f.flush()
                if not reported and last:
                    print('native power rows',count.value,'last_us',last,'raw_mW',s.value.ui,flush=True);reported=True
            elif rc!=6:
                err.write(json.dumps({'epoch':time.time(),'nvml_status':rc})+'\n')
                if not reported:raise RuntimeError(('power sampler unavailable',rc))
            if (base/'final.json').exists():break
            time.sleep(.75)
    nv.nvmlShutdown()


if __name__=='__main__':main()
