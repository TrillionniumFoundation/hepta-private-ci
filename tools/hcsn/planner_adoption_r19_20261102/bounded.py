"""Entry- and byte-bounded LRU ownership for the unchanged forty-state law."""

from collections import OrderedDict
import sys

import numpy as np

from ..support_retention_r16_20261101.compression import BlockLaw

TRANSITION_LIMIT=96
EVENT_LIMIT=16
KERNEL_LIMIT=8
WORKSPACE_LIMIT=1
COUNTER_MAX=(1<<64)-1
PERSISTENT_ARRAY_CAP=2_097_152


def array_bytes(value):
    seen=set();stack=[value];total=0
    while stack:
        item=stack.pop()
        if id(item) in seen:continue
        seen.add(id(item))
        if isinstance(item,np.ndarray):
            if isinstance(item.base,np.ndarray):stack.append(item.base)
            else:total+=item.nbytes
        elif isinstance(item,dict):stack.extend(item.values())
        elif isinstance(item,(tuple,list)):stack.extend(item)
    return total


class LRU(OrderedDict):
    """No hidden retained entries; live cache references count toward byte bounds."""

    def __init__(self,maximum,maximum_entry_bytes):
        super().__init__();self.maximum=maximum;self.maximum_entry_bytes=maximum_entry_bytes
        self.hits=self.misses=self.evictions=self.insertions=self.maximum_occupancy=0
        self.counters_saturated=False

    def _increment(self,name):
        value=getattr(self,name)
        if value<COUNTER_MAX:setattr(self,name,value+1)
        else:self.counters_saturated=True

    def __contains__(self,key):
        found=super().__contains__(key)
        if found:self._increment("hits")
        else:self._increment("misses")
        return found

    def __getitem__(self,key):
        result=super().__getitem__(key);self.move_to_end(key);return result

    def __setitem__(self,key,value):
        if len(repr(key).encode())>256 or array_bytes(value)>self.maximum_entry_bytes:
            raise ValueError("Cache entry exceeds the declared resource contract")
        if super().__contains__(key):super().__delitem__(key)
        super().__setitem__(key,value);self._increment("insertions")
        while len(self)>self.maximum:self.popitem(last=False);self._increment("evictions")
        self.maximum_occupancy=max(self.maximum_occupancy,len(self))

    def metrics(self):
        return dict(entries=len(self),maximum=self.maximum,hits=self.hits,misses=self.misses,
            evictions=self.evictions,insertions=self.insertions,maximum_occupancy=self.maximum_occupancy,
            maximum_entry_array_bytes=self.maximum_entry_bytes,counters_saturated=self.counters_saturated,counter_max=COUNTER_MAX)


class BoundedLaw(BlockLaw):
    """Same law identity and dense expm; only cache eviction policy differs."""

    def _finish(self):
        super()._finish()
        fixed={k:v for k,v in self.__dict__.items() if isinstance(v,np.ndarray)}
        if array_bytes(fixed)>65_536:raise ValueError("Immutable law exceeds finite-profile byte cap")
        self._transition_cache=LRU(TRANSITION_LIMIT,12_800)
        self._event_cache=LRU(EVENT_LIMIT,13_448)


class BoundedKernels:
    """LRU of original numerical transition/readout products, shared by all cores."""

    def __init__(self):self.entries=LRU(KERNEL_LIMIT,56_320)

    def get(self,law,dt):
        key=(id(law),law.identity,float(dt).hex())
        if key in self.entries:return self.entries[key]
        matrices={h:law.transition(h*dt) for h in range(4)}
        rewards={h:p@law.reward for h,p in matrices.items()}
        for value in rewards.values():value.setflags(write=False)
        self.entries[key]=(matrices,rewards)
        return self.entries[key]


class Workspace:
    """Bounded terminal dot buffers; old matrix shapes/order are preserved."""

    def __init__(self):self.entries=LRU(WORKSPACE_LIMIT,4_000)

    def terminal(self,p,reward):
        rows=len(p)
        if rows>125:raise ValueError("Outside the declared three-slot single-belief tree")
        if 125 not in self.entries:self.entries[125]=np.empty((125,4),dtype=float)
        output=self.entries[125][:rows]
        np.matmul(p,reward,out=output)
        return np.max(output,axis=1)[:,None]


def resource_metrics(law,kernels,workspace):
    seen=set();stack=[law.__dict__,kernels.__dict__,workspace.__dict__];bytes_total=objects=0
    while stack:
        value=stack.pop()
        if id(value) in seen:continue
        seen.add(id(value));objects+=sys.getsizeof(value)
        if isinstance(value,np.ndarray):
            if isinstance(value.base,np.ndarray):stack.append(value.base)
            else:bytes_total+=value.nbytes
        elif isinstance(value,dict):
            stack.extend(value.keys());stack.extend(value.values())
            if isinstance(value,LRU):stack.append(value.__dict__)
        elif isinstance(value,(tuple,list)):stack.extend(value)
    if bytes_total>PERSISTENT_ARRAY_CAP:raise MemoryError("Persistent array ownership cap exceeded")
    return dict(unique_owned_or_referenced_array_bytes=bytes_total,array_cap=PERSISTENT_ARRAY_CAP,
        recursive_getsizeof_bytes=objects,transition=law._transition_cache.metrics(),
        event=law._event_cache.metrics(),kernel=kernels.entries.metrics(),workspace=workspace.entries.metrics(),
        scope="Law+kernel+workspace physical ndarray bases deduplicated together; sys.getsizeof overlaps ndarray data. Does not claim total RSS/native allocator cap.")
