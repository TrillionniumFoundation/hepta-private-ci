"""Uniform Adam budget, gradient clipping, validation-only checkpoint selection."""

import time
import numpy as np
import jax
import jax.numpy as jnp
from jax.example_libraries import optimizers
try:
    from .models import apply_model
except ImportError:
    from models import apply_model


def loss_fn(params,x,dt,y,kind):
    logits=apply_model(params,x,dt,kind)
    return -jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(y.shape[0]),y])


def make_trainer(kind,lr=.003):
    init_opt,update_opt,get_params=optimizers.adam(lr)
    @jax.jit
    def step(i,state,x,dt,y):
        loss,grads=jax.value_and_grad(loss_fn)(get_params(state),x,dt,y,kind)
        norm=jnp.sqrt(sum(jnp.sum(a*a) for a in jax.tree_util.tree_leaves(grads)))
        scale=jnp.minimum(1.,1./(norm+1e-8))
        grads=jax.tree_util.tree_map(lambda a:a*scale,grads)
        return update_opt(i,grads,state),loss,norm
    @jax.jit
    def evaluate(params,x,dt,y):
        logits=apply_model(params,x,dt,kind)
        probs=jax.nn.softmax(logits)
        loss=-jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(y.shape[0]),y])
        accuracy=jnp.mean(jnp.argmax(logits,-1)==y)
        brier=jnp.mean(jnp.sum((probs-jax.nn.one_hot(y,logits.shape[-1]))**2,axis=-1))
        return loss,accuracy,brier
    return init_opt,step,get_params,evaluate


def evaluate_dataset(evaluate,params,data,batch_size=128):
    rows=[]
    for i in range(0,len(data["y"]),batch_size):
        batch=[jnp.asarray(data[k][i:i+batch_size]) for k in ("x","dt","y")]
        out=evaluate(params,*batch)
        rows.append((len(batch[2]),np.asarray([float(v) for v in out])))
    result=sum(n*v for n,v in rows)/sum(n for n,_ in rows)
    return dict(loss=float(result[0]),accuracy=float(result[1]),brier=float(result[2]))


def train_model(params,kind,train,validation,seed,steps=300,batch_size=32,lr=.003,
                trainer=None,eval_every=50):
    """Return best validation checkpoint, history and timing metadata.

    All kinds use identical minibatch indices for a given seed. No test set is
    passed to this function. Compilation timing is separated from warm updates.
    """
    if trainer is None:
        trainer=make_trainer(kind,lr)
    init_opt,step,get_params,evaluate=trainer
    state=init_opt(params)
    rng=np.random.default_rng(50000+seed)
    history=[]; best_loss=float("inf"); best_params=params; best_step=0
    train_time=0.; compilation=0.; norms=[]
    for it in range(steps):
        idx=rng.integers(0,len(train["y"]),batch_size)
        batch=[jnp.asarray(train[k][idx]) for k in ("x","dt","y")]
        start=time.perf_counter()
        state,loss,norm=step(it,state,*batch)
        loss.block_until_ready()
        elapsed=time.perf_counter()-start
        if it==0:
            compilation=elapsed
        else:
            train_time+=elapsed
        norms.append(float(norm))
        if not np.isfinite(float(loss)):
            raise FloatingPointError(f"Nonfinite loss in {kind}, seed {seed}, step {it}")
        if (it+1)%eval_every==0 or it+1==steps:
            metrics=evaluate_dataset(evaluate,get_params(state),validation)
            history.append(dict(step=it+1,train_minibatch_loss=float(loss),validation=metrics))
            if metrics["loss"]<best_loss:
                best_loss=metrics["loss"]; best_params=get_params(state); best_step=it+1
    return best_params,history,dict(best_step=best_step,first_update_seconds=compilation,
        warm_training_seconds=train_time,max_unclipped_gradient_norm=max(norms),
        mean_unclipped_gradient_norm=float(np.mean(norms)),steps=steps,batch_size=batch_size,
        train_examples_seen=steps*batch_size,learning_rate=lr)
