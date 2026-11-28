"""Read the NVIDIA board energy counter and contemporaneous board power through NVML."""
import ctypes
import statistics
import threading
import time


class BoardMeter:
    def __init__(self):
        self.note = None
        self.power_samples = []
        self.stop_event = threading.Event()
        self.thread = None
        self.lib = None
        try:
            self.lib=ctypes.CDLL('libnvidia-ml.so.1')
            if self.lib.nvmlInit_v2()!=0:
                raise RuntimeError('NVML initialization failed')
            self.handle=ctypes.c_void_p()
            rc=self.lib.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(self.handle))
            if rc:
                raise RuntimeError('NVML index 0 unavailable')
        except (OSError,AttributeError,RuntimeError) as exc:
            self.note=str(exc)
            self.lib=None

    def read(self,function,dtype):
        if not self.lib:
            return None
        try:
            value=dtype()
            rc=getattr(self.lib,function)(self.handle,ctypes.byref(value))
            return value.value if rc==0 else None
        except (OSError,AttributeError):
            return None

    def sample(self):
        w=self.read('nvmlDeviceGetPowerUsage',ctypes.c_uint)
        if w is not None:
            self.power_samples.append((time.perf_counter(),w/1000.))

    def poll(self):
        while not self.stop_event.wait(.2):
            self.sample()

    def __enter__(self):
        self.begin=time.perf_counter()
        self.energy0=self.read('nvmlDeviceGetTotalEnergyConsumption',ctypes.c_ulonglong)
        self.sample()
        if self.lib:
            self.thread=threading.Thread(target=self.poll,daemon=True)
            self.thread.start()
        return self

    def __exit__(self,*args):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        self.sample()
        energy1=self.read('nvmlDeviceGetTotalEnergyConsumption',ctypes.c_ulonglong)
        end=time.perf_counter()
        if self.lib:
            self.lib.nvmlShutdown()
        power=self.power_samples
        integral=sum((b[0]-a[0])*(a[1]+b[1])*.5 for a,b in zip(power,power[1:])) if len(power)>=2 else None
        counter=(energy1-self.energy0)/1000. if energy1 is not None and self.energy0 is not None and energy1>=self.energy0 else None
        self.result={'scope':'whole GPU board during fresh child process, including imports, validations, save and exit',
             'seconds':end-self.begin,'nvml_error':self.note,'board_counter_joules':counter,
             'power_integral_joules':integral,'samples':len(power),
             'covered_seconds':power[-1][0]-power[0][0] if len(power)>1 else None,
             'max_sample_gap_s':max((b[0]-a[0] for a,b in zip(power,power[1:])),default=None),
             'median_power_w':statistics.median(x[1] for x in power) if power else None,
             'power_samples_w_and_offset_s':[[round(t-self.begin,5),w] for t,w in power]}
