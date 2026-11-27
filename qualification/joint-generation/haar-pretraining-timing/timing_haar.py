"""Explicit three fixed coordinate paths; no optimizer-state transport."""
import numpy as np
from matched_haar import MatchedHaarModel,MODE as MATCHED_MODE
from haar_coordinate import PROFILE,encoder_coordinates
MODE='fixed-haar-pretraining-timing-v1'
PATHS=(('raw','raw'),('raw','haar'),('haar','haar'))
def clone_to_coordinate(source,*,coordinate_path,mode):
    if mode!=MODE or type(coordinate_path) is not tuple or coordinate_path not in PATHS:raise ValueError('explicit fixed timing path')
    if type(source) is not MatchedHaarModel or source.representation!=coordinate_path[0]:raise ValueError('known matched source coordinate')
    if any(not np.isfinite(v).all() for v in source.params.values()):raise ValueError('finite parameters')
    out=MatchedHaarModel(*source.dimensions[:3],hidden=source.dimensions[3],representation=coordinate_path[1],mode=MATCHED_MODE)
    transformed=encoder_coordinates(PROFILE,source.params['encoder'])
    out._count('encoder_transform_calls');out._count('encoder_transform_rows',32)
    out.params={k:v.copy() for k,v in source.params.items()}
    if coordinate_path[0]!=coordinate_path[1]:out.params['encoder']=transformed
    out.conversion_source_digest=source.digest()
    return out
