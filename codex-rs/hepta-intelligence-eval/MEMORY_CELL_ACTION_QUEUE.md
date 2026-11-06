# Experimental PR queue coalescing (not a CI waiver)

PR #1452 already contains hundreds of commits and changed files. GitHub
pull_request path filtering compares the full PR three-dot diff, not only the
latest pushed commit. Thus every unrelated source/documentation update can
schedule many old pretrained research experiments.

Twenty-two independent research workflows now use a stable PR-number concurrency
group with their **own unique workflow prefix**, instead of a new group per
head SHA. GitHub's default concurrency replaces an older **pending** run of
the same workflow when a newer one queues. cancel-in-progress stays false:
an actually running experiment is never canceled by this change.

PR triggers, path filters, model/data pins, test steps, token budgets, source
isolation, and exact checked-out commit bindings are unchanged. The repository's
mandatory blocking-ci, Architecture and admission gates are not modified.
Results from old commits cannot be relabelled current; canceled/pending tasks
are not successes. On workflow_dispatch, github.ref supplies a defined fallback.

This eliminates only redundant waiting, not any required verification. The
prior real source-only LoRA experiment already showed zero wins over the
saturated organized baseline (8/8), while pinned BF16 Qwen loss projection
parity passed one real optimizer step; no model gain or production qualification
is asserted here.

Validation:
python3 -m unittest discover -s scripts/memory_cell -p test_memory_queue_concurrency.py -v

GitHub docs: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
and https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
