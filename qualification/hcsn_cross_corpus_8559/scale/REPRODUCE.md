The study first considered 8,734/1,094/1,093 official RSICD train/validation/test photographs. The inherited raw-pixel roster applies source-order filtering when a filename, a deterministic chosen caption, or 32×32 RGB pixels duplicate a previously accepted row. It retained 6,311/742/964 photographs. This study reads the authors' original five captions for each row and applies an additional transformed near-duplicate screen. NWPU, Sydney and UCM are decoded directly from their release images. RSICD uses bilinear downsampling from the legacy cache; the other three use BOX. DATA.json contains all raw file and derived array digests. The captions, limited spatial resolution and four sequence positions describe an aerial-image research encoder.

From the study directory, the normal stages are:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python sources.py /data/rsicd /data/ucm
python scale/acquire.py /data/corpora
python scale/data.py /data/rsicd /data/ucm /data/corpora /work/scale/data
python scale/linear_scale.py /work/scale
python scale/matrix.py /work/scale /work/law4.npz --cpu 5
python scale/timing.py /work/scale
python scale/confirmation.py /work/scale /work/law4.npz --seal
python scale/confirmation.py /work/scale /work/law4.npz --confirm
python scale/recount.py /work/scale
```

Use an available single CPU index. The reference worker uses the 4-atom law in the first experiment's evidence. scale/supervise.py can run alongside an already-started matrix and will recover an interrupted matrix only after checking inactivity and per-trial locks. It seals and evaluates autonomously after all twelve final endpoints. Every registered step and time endpoint is scored. The optional snapshot files hold the optimizer, sampler, PyTorch RNG and cumulative counters.

The four earliest budget-30 workers were already running before process-lifetime instrumentation was added. The analysis brackets their total child-process time using adjacent durable timestamps. Later workers also measure elapsed time from OS process birth through each selection and all preceding child runs. The accounting change leaves the numerical model, sampler, data and optimization budget unchanged. Component sums and the worker span are reported separately. The known Python process teardown tail may differ by fractions of a second or longer during contention. Early timing brackets are available in EARLY_CLOCK_BRACKETS.json. The new NWPU/Sydney source acquisition spanned 45.19 seconds from acquisition log creation to last checksum line, in addition to shared four-corpus preprocessing. RSICD and UCM prior cache acquisition is unmetered.
