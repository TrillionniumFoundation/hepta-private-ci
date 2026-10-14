# Shared-model ambiguity: local nonlinear backups need not glue globally

This is an additive, exact finite decision experiment. The exogenous visible
bit `S` is observed before choosing `guess0`, `guess1` or `abstain`,
but the index of the probability law remains hidden. Two globally admissible
joint laws are fixed:

- Model A: `(S,Y)` is `(0,1)` or `(1,0)`, each probability 1/2;
- Model B: `(S,Y)` is `(0,0)` or `(1,1)`, each probability 1/2.

Payoffs are +1 if correct, -1 if incorrect, and -1/4 if abstaining.
A legal policy has one action for each PUBLIC signal, never access to the
hidden model or terminal label. Exhaustive evaluation of all 3²=9 legal
policies gives robust GLOBAL max-min value 0: guess0 for both signals.

If a local backward recursion instead allows the adversary to choose a
DIFFERENT conditional law after each signal, guesses can always be made wrong.
It therefore abstains everywhere and returns -1/4. The difference is exactly
1/4, and is a change of objective, not a numerical solver failure.

This model-ambiguity set is nonrectangular: conditional worst-case models
cannot in general be chosen independently across branches while still
representing one globally admissible joint law. To claim consistency with the
global problem, preserve cross-branch coupling/latent-model state, or declare
a rectangular ambiguity hull as a DIFFERENT problem.

The experiment demonstrates why locally unique nonlinear value backups are
not enough to conclude global equivalence. It is not a neural/FBSDE
existence theorem, learned semantic reasoning, a calibrated uncertainty set,
future Hepta observation, or a native action/grant. The original four-gate
reviewer and every production owner remain unchanged. No model promotion.

Reproduction on an exact checkout:

```sh
PYTHONPATH=qualification/neuron-stem python -m unittest -v test_fbsde_ambiguity
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_ambiguity.py
```
