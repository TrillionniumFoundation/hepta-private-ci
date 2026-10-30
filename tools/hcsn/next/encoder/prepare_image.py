"""Frozen MobileNet spatial features on CIFAR-10; occlude before encoding."""
import io
import time

import duckdb
import numpy as np
import onnx
from PIL import Image

from feature_utils import CACHE,SEED,choose,finish,fingerprint,session,sha


def image_rows(split):
    connection=duckdb.connect()
    raw=connection.execute("SELECT img,label FROM read_parquet(?)",
        [str(CACHE/("cifar_"+split+".parquet"))]).fetchall()
    connection.close()
    rows=[]
    for index,(blob,label) in enumerate(raw):
        image=np.asarray(Image.open(io.BytesIO(blob["bytes"])).convert("RGB")).copy()
        assert image.shape==(32,32,3)
        rows.append((index,image,int(label),fingerprint(image.tobytes())))
    counts=np.bincount([r[2] for r in rows],minlength=10)
    assert np.all(counts==(5000 if split=="train" else 1000))
    return rows


def main():
    model=CACHE/"mobilenetv2-12.onnx"
    assert sha(model)=="c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5"
    expected={"cifar_train.parquet":"8428b53a88a11ac374111006708df51469e315a22ac6d66470afd9c78d2ae883",
              "cifar_test.parquet":"841389e6f2d64f28bf17310e430aebac20ec3ba611a3c5e231dc93c645ce84de"}
    for name,digest in expected.items():assert sha(CACHE/name)==digest
    pools={"train":image_rows("train"),"test":image_rows("test")}
    seen=set();selected={}
    for offset,(split,count) in enumerate((("train",2000),("validation",500),("test",1000))):
        selected[split]=choose(pools["test" if split=="test" else "train"],count,10,SEED+offset,seen)
    del pools
    graph=onnx.load(model)
    pools=[n for n in graph.graph.node if n.op_type=="GlobalAveragePool"]
    assert len(pools)==1
    spatial=pools[0].input[0]
    del graph.graph.output[:]
    graph.graph.output.append(onnx.helper.make_tensor_value_info(spatial,onnx.TensorProto.FLOAT,[None,1280,7,7]))
    derived=CACHE/"mobilenet_spatial.onnx"
    onnx.checker.check_model(graph);onnx.save(graph,derived)
    encoder=session(derived)
    mean=np.array([.485,.456,.406],np.float32)[None,:,None,None]
    std=np.array([.229,.224,.225],np.float32)[None,:,None,None]
    def encode(images):
        pieces=[]
        for offset in range(0,len(images),16):
            resized=np.stack([np.asarray(Image.fromarray(img).resize((224,224),Image.Resampling.BILINEAR))
                              for img in images[offset:offset+16]])
            inputs=(resized.astype(np.float32).transpose(0,3,1,2)/255.-mean)/std
            hidden=encoder.run(None,{encoder.get_inputs()[0].name:inputs})[0]
            assert hidden.shape[1:]==(1280,7,7)
            chunks=[hidden[:,:,iy][:,:,:,ix].mean((2,3))
                    for iy in np.array_split(np.arange(7),4) for ix in np.array_split(np.arange(7),4)]
            chunks.append(hidden.mean((2,3)))
            pieces.append(np.stack(chunks,axis=1).astype(np.float32))
        return np.concatenate(pieces)
    features={};labels={};times={}
    for split,rows in selected.items():
        start=time.perf_counter();features[split]=encode([r[1] for r in rows]);times[split]=time.perf_counter()-start
        labels[split]=np.array([r[2] for r in rows],np.int32)
        print(split,features[split].shape,times[split],flush=True)
    images=[]
    for row in selected["test"]:
        image=row[1].copy();image[8:24,8:24]=128;images.append(image)
    start=time.perf_counter();features["corrupted_test"]=encode(images);times["corrupted_test"]=time.perf_counter()-start
    labels["corrupted_test"]=labels["test"].copy()
    difference=np.linalg.norm(features["test"][:,-1]-features["corrupted_test"][:,-1],axis=1)
    assert np.all(difference>0)
    metadata=dict(model="onnxmodelzoo/mobilenetv2-12",model_revision="23a2a25eaaa6fcd61865414c8a1acf13dda66b7a",
        model_sha256=sha(model),derived_encoder_sha256=sha(derived),derived_output=spatial,
        graph_change="Expose tensor feeding GlobalAveragePool; weights and activations unchanged",
        dataset_source="https://www.cs.toronto.edu/~kriz/cifar.html",
        dataset_mirror="https://huggingface.co/datasets/uoft-cs/cifar10",
        dataset_revision="0b2714987fa478483af9968de7c934580d0bb9a2",
        source_sha256_downloads=expected,encoder_times_seconds=times,
        encoder_total_examples=4500,encoder_total_seconds=sum(times.values()),
        preprocessing="RGB uint8 -> bilinear 224x224 -> ImageNet mean/std; 4x4 spatial groups of 7x7 map plus global mean",
        corrupted_input="Central original-resolution 16x16 square set to uint8 value128; resize and full re-encoding",
        corrupted_input_sha256=[fingerprint(image.tobytes()) for image in images],
        global_feature_changed_fraction=float(np.mean(difference>0)),
        global_feature_l2_difference_mean=float(difference.mean()),threads=1)
    finish("cifar10",features,labels,selected,metadata)


if __name__=="__main__":
    main()
