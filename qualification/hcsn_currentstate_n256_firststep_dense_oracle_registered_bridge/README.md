# N256 warm-1 registered execution bridge

Status: **SOURCE FROZEN / ONE AUTOMATIC PATH / HOLD / all_closed=false**.

Draft #6637 froze the original one-shot launcher, but exact-head Actions metadata
contained only the generic architecture, V8, and blocking workflows.  No
dedicated workflow run, job, artifact, authentic-input read, dynamic step, or
matrix exponential exists for that head.  The new workflow file was not a
registered execution path; waiting longer cannot turn the absence into a run.

This successor leaves the original execution-freeze protocol job unchanged and
adds a branch-exact job to its already registered workflow.  The job invokes the
unchanged #6637 launcher with the unchanged unique execution key.  It cannot run
under manual dispatch or another branch, concurrency is one, and an in-progress
job is not cancelled.  The original runtime hash, same-job resource policy,
4 GiB pre-exec child limit, 600-second child deadline, historical RED/UNKNOWN
accounting, and one-attempt budget are unchanged.

A successful run would close only the independent authentic N256 warm
0→0.001 dense-oracle capsule and actual bounded cost.  It is not candidate
equality, N512, later cycles, arbitrary histories, finite-domain qualification,
full-network training, task benefit, or production adoption.  C2 full replay
remains 0/6; HPCA remains NoUpdate with external custody and equal-budget
benefit open; global status remains HOLD and `all_closed=false`.
