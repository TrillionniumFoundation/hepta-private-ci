"""Actual raw-input encoder and shared projection, reusable for cost measurement."""
import io
import json
from pathlib import Path
import time

import duckdb
import numpy as np
from PIL import Image
from tokenizers import Tokenizer

from feature_utils import CACHE,FOLDER,session


class RawPipeline:
    def __init__(self,dataset):
        self.dataset=dataset
        raw=np.load(CACHE/(dataset+"_features.npz"))
        self.projection=raw["projection"]
        self.projected_center=raw["center"]@self.projection
        self.scale=raw["scale"]
        if dataset=="ag_news":
            folder=Path("/tmp/hcsn-encoder-assets")
            self.encoder=session(folder/"model.onnx")
            self.tokenizer=Tokenizer.from_file(str(folder/"tokenizer.json"))
            self.tokenizer.enable_truncation(max_length=64)
            self.tokenizer.enable_padding(length=64)
            self.input_names={v.name for v in self.encoder.get_inputs()}
        elif dataset=="cifar10":
            self.encoder=session(CACHE/"mobilenet_spatial.onnx")
            self.mean=np.array([.485,.456,.406],np.float32)[None,:,None,None]
            self.std=np.array([.229,.224,.225],np.float32)[None,:,None,None]
        else:
            raise ValueError(dataset)

    def selected_test_inputs(self,count):
        manifest=json.loads((FOLDER/(self.dataset+"_manifest.json")).read_text())
        rows=manifest["selection"]["test"][:count]
        connection=duckdb.connect()
        if self.dataset=="ag_news":
            raw=connection.execute("SELECT text FROM read_parquet(?)",[str(CACHE/"ag_test.parquet")]).fetchall()
            selected=[raw[r["source_row"]][0] for r in rows]
        else:
            raw=connection.execute("SELECT img FROM read_parquet(?)",[str(CACHE/"cifar_test.parquet")]).fetchall()
            selected=[raw[r["source_row"]][0]["bytes"] for r in rows]
        connection.close()
        return selected

    def __call__(self,value):
        start=time.perf_counter()
        if self.dataset=="ag_news":
            token=self.tokenizer.encode(value)
            mask=np.asarray([token.attention_mask],np.int64)
            values=dict(input_ids=np.asarray([token.ids],np.int64),attention_mask=mask,
                        token_type_ids=np.asarray([token.type_ids],np.int64))
            inputs={k:v for k,v in values.items() if k in self.input_names}
        else:
            image=Image.open(io.BytesIO(value)).convert("RGB")
            resized=np.asarray(image.resize((224,224),Image.Resampling.BILINEAR))
            inputs={self.encoder.get_inputs()[0].name:
                    (resized.astype(np.float32).transpose(2,0,1)[None]/255.-self.mean)/self.std}
        preprocess=time.perf_counter()-start
        start=time.perf_counter()
        hidden=self.encoder.run(None,inputs)[0]
        encoder=time.perf_counter()-start
        start=time.perf_counter()
        if self.dataset=="ag_news":
            masked=hidden*mask[...,None]
            chunks=masked.reshape(-1,16,4,384).sum(2)/np.maximum(mask.reshape(-1,16,4).sum(2)[...,None],1)
            mean=masked.sum(1)/np.maximum(mask.sum(1,keepdims=True),1)
            tokens=np.concatenate([chunks,mean[:,None]],1).astype(np.float32)
        else:
            chunks=[hidden[:,:,iy][:,:,:,ix].mean((2,3)) for iy in np.array_split(np.arange(7),4)
                    for ix in np.array_split(np.arange(7),4)]
            chunks.append(hidden.mean((2,3)))
            tokens=np.stack(chunks,axis=1)
        projected=((tokens@self.projection)-self.projected_center)/self.scale
        projection=time.perf_counter()-start
        return projected.astype(np.float32),dict(preprocessing_seconds=preprocess,
            encoder_seconds=encoder,pooling_projection_seconds=projection)
