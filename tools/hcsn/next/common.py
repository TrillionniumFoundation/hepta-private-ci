"""Uniform training with explicit precompilation and no warmup optimizer updates.

The compiled optimizer executable is built for each training shape before the
budget starts. All initialization leaves and update indices have strong dtypes.
Compilation, validation, data preparation, and optimizer execution are recorded
separately. Shared-CPU timings still do not establish hardware or energy gains.
"""
from functools import lru_cache
import time

import jax
import jax.numpy as jnp
from jax.example_libraries import optimizers
import numpy as np
from scipy.special import logsumexp


def strong_parameters(params):
    return jax.tree_util.tree_map(lambda a:jnp.asarray(np.asarray(a),dtype=a.dtype),params)


def signature(tree):
    return [(tuple(a.shape),str(a.dtype),bool(getattr(a,"weak_type",False)))
            for a in jax.tree_util.tree_leaves(tree)]


@lru_cache(maxsize=96)
def predictor(apply_fn):
    return jax.jit(apply_fn)


def predict_model(apply_fn,params,data,batch_size=128):
    predict=predictor(apply_fn)
    outputs=[]
    for offset in range(0,len(data["y"]),batch_size):
        x=jnp.asarray(data["x"][offset:offset+batch_size])
        dt=jnp.asarray(data["dt"][offset:offset+batch_size])
        outputs.append(np.asarray(predict(params,x,dt)))
    return np.concatenate(outputs)


def classification_metrics(logits,labels):
    logits=np.asarray(logits,dtype=np.float64)
    labels=np.asarray(labels)
    log_prob=logits-logsumexp(logits,axis=1,keepdims=True)
    prob=np.exp(log_prob)
    correct=prob.argmax(1)==labels
    confidence=prob.max(1)
    bins=np.minimum((10*confidence).astype(np.int64),9)
    ece=0.
    for index in range(10):
        selected=bins==index
        if selected.any():
            ece+=selected.mean()*abs(correct[selected].mean()-confidence[selected].mean())
    return dict(loss=float(-log_prob[np.arange(len(labels)),labels].mean()),
        accuracy=float(correct.mean()),
        brier=float(np.mean(np.sum((prob-np.eye(prob.shape[1])[labels])**2,axis=1))),
        ece=float(ece))


def evaluate_model(apply_fn,params,data):
    return classification_metrics(predict_model(apply_fn,params,data),data["y"])


def train_model(params,apply_fn,train_data,validation,seed,steps=300,batch_size=32,
                lr=.003,eval_every=50):
    """Train using one dataset or a fixed cyclic list of different-length datasets.

    Only train and validation are accepted. The optimizer update budget starts
    at zero after AOT compilation; there are no discarded warmup updates.
    """
    start_total=time.perf_counter()
    params=strong_parameters(params)
    if any(weak for _,_,weak in signature(params)):
        raise TypeError("Initialization must contain no weakly typed leaves")
    datasets=train_data if isinstance(train_data,(list,tuple)) else [train_data]
    init_opt,update_opt,get_params=optimizers.adam(lr)
    state=init_opt(params)
    def loss_fn(p,x,dt,y):
        logits=apply_fn(p,x,dt)
        return -jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(len(y)),y])
    @jax.jit
    def step(index,opt_state,x,dt,y):
        loss,gradient=jax.value_and_grad(loss_fn)(get_params(opt_state),x,dt,y)
        norm=jnp.sqrt(sum(jnp.sum(g*g) for g in jax.tree_util.tree_leaves(gradient)))
        gradient=jax.tree_util.tree_map(lambda g:g*jnp.minimum(1.,1./(norm+1e-8)),gradient)
        return update_opt(index,gradient,opt_state),loss,norm
    compiled={}
    compile_start=time.perf_counter()
    for dataset in datasets:
        batch=tuple(jnp.asarray(dataset[k][:batch_size]) for k in ("x","dt","y"))
        if len(batch[2])!=batch_size:
            raise ValueError("Training dataset is smaller than one batch")
        if not np.isfinite(dataset["x"]).all() or not np.isfinite(dataset["dt"]).all():
            raise ValueError("Nonfinite training data")
        if np.any(dataset["dt"]<=0):
            raise ValueError("Time gaps must be positive")
        key=tuple((tuple(a.shape),str(a.dtype)) for a in batch)
        if key not in compiled:
            compiled[key]=step.lower(jnp.asarray(0,dtype=jnp.int32),state,*batch).compile()
    compilation=time.perf_counter()-compile_start
    original_signature=signature(state)
    rng=np.random.default_rng(50000+seed)
    best_loss=float("inf");best_params=params;best_step=0
    history=[];norms=[];times=[];validation_seconds=0.;host_seconds=0.
    for index in range(steps):
        before=time.perf_counter()
        dataset=datasets[index%len(datasets)]
        ids=rng.integers(0,len(dataset["y"]),batch_size)
        batch=tuple(jnp.asarray(dataset[k][ids]) for k in ("x","dt","y"))
        key=tuple((tuple(a.shape),str(a.dtype)) for a in batch)
        host_seconds+=time.perf_counter()-before
        before=time.perf_counter()
        state,loss,norm=compiled[key](jnp.asarray(index,dtype=jnp.int32),state,*batch)
        jax.block_until_ready((state,loss,norm))
        times.append(time.perf_counter()-before)
        if index in (0,1,steps-1) and signature(state)!=original_signature:
            raise RuntimeError("Optimizer state signature changed after precompilation")
        value=float(loss);norms.append(float(norm))
        if not np.isfinite(value) or not np.isfinite(norms[-1]):
            raise FloatingPointError(f"Nonfinite training at update {index}")
        if (index+1)%eval_every==0 or index+1==steps:
            before=time.perf_counter()
            metrics=evaluate_model(apply_fn,get_params(state),validation)
            validation_seconds+=time.perf_counter()-before
            history.append(dict(step=index+1,train_minibatch_loss=value,validation=metrics))
            if metrics["loss"]<best_loss:
                best_loss=metrics["loss"];best_params=get_params(state);best_step=index+1
    timing=dict(best_step=best_step,steps=steps,batch_size=batch_size,learning_rate=lr,
        train_examples_seen=steps*batch_size,compilation_seconds=compilation,
        optimizer_execution_seconds=float(sum(times)),
        optimizer_update_median_ms=float(1000*np.median(times)),
        optimizer_update_p95_ms=float(1000*np.percentile(times,95)),
        validation_seconds=validation_seconds,host_batch_seconds=host_seconds,
        total_train_call_seconds=time.perf_counter()-start_total,
        first_three_optimizer_update_seconds=times[:3],
        compiled_training_shapes=len(compiled),strong_initial_parameters=True,
        optimizer_signature_stable=True,warmup_optimizer_updates=0,
        max_unclipped_gradient_norm=max(norms),mean_unclipped_gradient_norm=float(np.mean(norms)),
        caveat="AOT optimizer timing on shared CPU; no hardware, energy or end-to-end superiority claim")
    return best_params,history,timing


def measure_latency(apply_fn,params,data,batch_size=32,repeats=50):
    """Pure logits only; compilation and three warmup predictions are excluded."""
    x=jnp.asarray(data["x"][:batch_size]);dt=jnp.asarray(data["dt"][:batch_size])
    compiled=predictor(apply_fn).lower(params,x,dt).compile()
    for _ in range(3):
        compiled(params,x,dt).block_until_ready()
    values=[]
    for _ in range(repeats):
        start=time.perf_counter();compiled(params,x,dt).block_until_ready()
        values.append(1000*(time.perf_counter()-start))
    return dict(batch_size=len(x),median_ms=float(np.median(values)),
        p95_ms=float(np.percentile(values,95)),p99_ms=float(np.percentile(values,99)),
        includes_encoder=False,includes_metrics=False,includes_compilation=False,
        scope="Pure logits, shared CPU, fixed batch and sequence shape")
