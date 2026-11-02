"""Typed C API transport for all three compiled financial precision modes."""
import ctypes
from pathlib import Path
import numpy as np

MODES={'float64':0,'float32':1,'compensated32':2}


class Kernel:
    def __init__(self,path):
        self.path=Path(path).resolve();self.library=ctypes.CDLL(str(self.path))
        self.call=self.library.hcsn_batch
        fp=ctypes.POINTER(ctypes.c_float);ip=ctypes.POINTER(ctypes.c_int);dp=ctypes.POINTER(ctypes.c_double)
        self.call.argtypes=[ctypes.c_int,ctypes.c_int,fp,fp,ip,ctypes.c_int,dp,ip];self.call.restype=ctypes.c_int
        self.primitive_call=self.library.hcsn_primitive;self.primitive_call.argtypes=[ctypes.c_int,fp,fp];self.primitive_call.restype=ctypes.c_int

    def batch(self,theta,states,coordinates,mode='compensated32',reuse_span=0):
        theta=np.ascontiguousarray(theta,dtype=np.float32);states=np.ascontiguousarray(states,dtype=np.float32)
        coordinates=np.ascontiguousarray([1 if c=='asset' else 0 if c=='log_distance' else -1 for c in coordinates],dtype=np.int32)
        count=len(states)
        if theta.shape!=(count,9) or coordinates.shape!=(count,):raise ValueError('Batch shape mismatch')
        result=np.empty((count,55),dtype=np.float64);status=np.empty(count,dtype=np.int32)
        failures=self.call(MODES[mode],count,theta.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                           states.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),coordinates.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
                           int(reuse_span),result.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),status.ctypes.data_as(ctypes.POINTER(ctypes.c_int)))
        if failures<0:raise RuntimeError('Invalid mode, batch or floating-point rounding environment: '+str(failures))
        if failures!=int(np.count_nonzero(status)):raise RuntimeError('Inconsistent failure count')
        return result[:,:5],result[:,5:].reshape(count,5,10),status

    def primitive(self,operation,words):
        values=np.ascontiguousarray(words,dtype=np.float32)
        if values.shape!=(4,):raise ValueError('Expected four FP32 high/low words')
        result=np.empty(2,dtype=np.float32)
        status=self.primitive_call(operation,values.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),result.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
        return result,status
