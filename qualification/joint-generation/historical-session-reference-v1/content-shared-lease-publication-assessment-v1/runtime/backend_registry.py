"""Closed two-backend registry; unknown models/schemas never dynamically import."""
from runtime import PixelTrainingRuntime,SCHEMA as PIXEL_SCHEMA
from fashion_backend import FashionBackend,FixedFashionStep,SCHEMA as FASHION_SCHEMA

def registered(model):return type(model) in (PixelTrainingRuntime,FashionBackend)
def input_width(model):
 if type(model) is PixelTrainingRuntime:return model.dimensions[0]
 if type(model) is FashionBackend:return 784
 raise ValueError('unknown backend')
def restore(payload):
 if type(payload) is not dict:raise ValueError('backend payload')
 if payload.get('schema')==PIXEL_SCHEMA:return PixelTrainingRuntime.from_checkpoint_payload(payload)
 if payload.get('schema')==FASHION_SCHEMA:return FashionBackend.from_checkpoint_payload(payload)
 raise ValueError('unregistered checkpoint backend')
def admit_step(model,step,profile,cursor):
 if type(model) is PixelTrainingRuntime:
  if not callable(step):raise ValueError('pixel callback required')
 elif type(model) is FashionBackend:
  keys=profile.get('fixed_step_keys')
  if not isinstance(step,FixedFashionStep) or type(keys) is not list or cursor>=len(keys) or step.key()!=keys[cursor]:raise ValueError('full target/noise/sequence/objective step binding')
 else:raise ValueError('unknown training backend')
