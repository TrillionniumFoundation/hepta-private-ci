# Delayed spiking network and complete-path learning

Run `node research/rr_snn_v3/validate_network.cjs` for functional checks.
Run `node research/rr_snn_v3/learn_network.cjs` for the frozen diagnostic.
The protocol and candidate are committed before first training and heldout data
generation; the earlier protocol freeze is 5741ac758ebd67841a69d4b7d1903e9f9e113f5d.
The final code/protocol freeze is identified in the subsequent execution receipt.

## Actual network

Two finite-state marked neurons exchange their actual physical pulses through
positive delays 0.1 and 0.15. The coordinator advances to the next physical or
external event, without a fixed simulation time grid. It advances all units to
the shared event time, batches emitted pulses, then schedules future deliveries.
Every neuron retains its own budget, refractory state, residual random clock,
trace, deadlines and complete path statistics. Budgets are not globally pooled.

The diagnostic has two evidence states, up rate 3, positive pulse debit 1,
refractory 0.05, trace time constant 0.6, horizon 4, initial budget 6 and cap 8.
It has two obligations with maturity [1,3] or [2,2], identical initial evidence,
budget and memory count. The shock at 1.5 is 2 or 0; a refill at 2.5 adds 1.
A deadline output has additional settlement cost 1 plus physical pulse cost 1.
A parameter-independent continuation proxy values post-decision budget and
retained obligations. This proxy is not an optimal future-utility solution.

Each input holds a feature vector until the next input:
bias, observed external drive, received presynaptic mark, tanh(actual own trace),
and current maturity pressure. The pulse rate is exp(theta dot features).
Pressure sums (renewDebit+renewLoss)*exp(-remaining time)/(1+budget).
The mean-maturity ablation receives the complete observation but compresses the
deadlines before constructing this feature. Both modes use actual emitted pulses.

## Functional evidence

Thirteen grouped checks cover physical recurrence, observation slicing, complete
checkpoint restore, pending axonal deliveries, canonical JSON object-key order,
equal numeric rates with different feature regimes, same-state different-deadline
counterfactuals, analytic path-score finite differences, final censoring and nine
invalid/overflow inputs. Restore binds the graph, full physical configurations,
weights, scenario, feature history and physical pulse cursor.

The counterfactual checks show the chosen full-schedule feature can alter rates
before the first deadline, whereas its mean-only ablation cannot distinguish
the paired schedules. They do not establish improved memory value or superiority
over an equally informed ALIF, CT-RNN or other strong baseline.

## Likelihood and what is learned

For a fully observed joint past, pulse intensity is eligibility*exp(theta dot F).
On a fixed observed path, F, delayed input delivery, gate and eligible exposure
are known path functions. The joint likelihood includes both neurons' source
pulses. Deliveries are deterministic consequences and receive no duplicate
likelihood term. Positive delays preserve causality.

The pulse NLL is sum(exp(theta dot F)*exposure-count*(theta dot F)).
Its gradient is sum((hazard-count)*F). Training adds one L2 penalty per neuron
with coefficient 0.01 and uses Adam for exactly 300 updates at learning rate 0.03.
The objective sums all 128 training episodes; gradient normalization by regime
count is declared in the protocol. There are five learned pulse-rate weights
per neuron and ten in total. Initial weights are all zero.

Absolute reported path NLL includes the fixed up-channel term
3*exposureUp-countUp*log(3). It has no parameter gradient and cancels in paired
candidate differences. Heldout likelihood excludes training regularization.
All ordinary internal jumps are observed. If future data expose only output
pulses, unobserved internal states require a different inference procedure.

Data seeds 10000..10127 generate training episodes; 50000..50127 generate 128
heldout episodes only after fitting ends. Four maturity/shock conditions have
32 episodes each. There is no holdout checkpoint or architecture selection.
The 10,000-resample bootstrap resamples entire two-neuron episodes within strata.
It conditions on this one fitted candidate and does not include training-set
uncertainty. Development seeds 9000..9999 are separate.

This is complete-observation conditional-intensity MLE. It is not terminal utility
optimization, a free-running predictive-calibration study, a fair architecture
benchmark or a real future-window evaluation. Neither the model, analytic
interval formulas nor a successful fit prove architectural novelty or superiority.
