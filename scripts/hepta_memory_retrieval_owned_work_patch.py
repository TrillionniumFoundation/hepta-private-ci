#!/usr/bin/env python3
"""One-shot, exact-preimage source migration for owned retrieval work.

Run without write credentials. The separate publisher accepts only the four
explicit source paths emitted here and never executes this program or Rust.
"""
from pathlib import Path
import json
import re
import subprocess
import sys

BASE = "caf94fa7d754c5d43880994156617790d090f9fb"
PATHS = (
    "codex-rs/hepta-agentd/src/retrieval_executor.rs",
    "codex-rs/hepta-agentd/src/retrieval_executor_tests.rs",
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "codex-rs/hepta-agentd/Cargo.toml",
)

def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()

def replace(text, old, new, count=1):
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"preimage mismatch: expected {count}, found {actual}: {old[:100]!r}")
    return text.replace(old, new)

def load(path):
    data = Path(path).read_bytes()
    expected = subprocess.check_output(["git", "show", f"{BASE}:{path}"])
    if data != expected:
        raise RuntimeError(f"source drift: {path}")
    return data.decode("utf-8")

def apply():
    source = {path: load(path) for path in PATHS}
    p = PATHS[0]
    text = source[p]
    marker = "    pub(crate) fn profile_digest(&self) -> Digest32 {"
    text = replace(text, marker, '''    /// Shadow shares the request's absolute upper bound, not its cancellation
    /// state. An optional experiment must never cancel compatibility delivery.
    pub(crate) fn begin_shadow(&self, parent: &RetrievalRequestWork) -> RetrievalRequestWork {
        let mut shadow = self.begin(RetrievalWorkClass::Shadow);
        shadow.deadline = shadow.deadline.min(parent.deadline);
        shadow.control = RecallWorkControlV1::bounded(shadow.deadline, 250_000);
        if parent.checkpoint().is_err() {
            shadow.control.cancel();
        }
        shadow
    }

''' + marker)
    text = replace(text,
        'hepta.retrieval.executor.v2:delivery=2,800ms;shadow=1,40ms;work=250000;queue=0;async=absolute-deadline',
        'hepta.retrieval.executor.v3:delivery=2,800ms;shadow=1,40ms,parent-bounded;work=250000;queue=0;async=owned-supervised;shadow-cancellation=independent')
    start = text.index("    pub(crate) async fn run_async<T, F>(")
    end = text.index("    pub(crate) async fn run<T, F>(", start)
    text = text[:start] + '''    pub(crate) async fn run_async<T, F>(
        &self,
        request: &RetrievalRequestWork,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: Future<Output = T> + Send + 'static,
    {
        request.checkpoint()?;
        let slots = match request.class {
            RetrievalWorkClass::Delivery => &self.delivery,
            RetrievalWorkClass::Shadow => &self.shadow,
        };
        let permit = Arc::clone(slots)
            .try_acquire_owned()
            .map_err(|_| "retrieval execution capacity exhausted".to_string())?;
        let control = request.control.clone();
        let mut cancel_on_drop = CancelOnDrop {
            control: control.clone(),
            armed: true,
        };
        // The owner operation, not its waiter, retains the capacity charge.
        // In particular, dropping a SQLx future need not stop a queued SQLite
        // command. Keep the owned operation alive until it really returns.
        let mut worker = tokio::spawn(async move {
            let _permit = permit;
            control.checkpoint().map_err(|error| error.to_string())?;
            let value = operation.await;
            control.checkpoint().map_err(|error| error.to_string())?;
            Ok(value)
        });
        match tokio::time::timeout_at(
            tokio::time::Instant::from_std(request.deadline),
            &mut worker,
        )
        .await
        {
            Ok(result) => {
                cancel_on_drop.armed = false;
                result.map_err(|_| "retrieval async owner failed".to_string())?
            }
            Err(_) => {
                request.control.cancel();
                // Do not abort: capacity remains owned until the underlying
                // operation exits, and its final checkpoint rejects late success.
                Err("retrieval request deadline exceeded".to_string())
            }
        }
    }

''' + text[end:]
    source[p] = text

    p = PATHS[2]
    text = source[p]
    text = replace(text, '''    let work_class = if delivers_hnmf {
        RetrievalWorkClass::Delivery
    } else {
        RetrievalWorkClass::Shadow
    };
    let request_work = executor.begin(work_class);''', '''    let request_work = executor.begin(RetrievalWorkClass::Delivery);
    let shadow_work = executor.begin_shadow(&request_work);
    let retrieval_work = if delivers_hnmf {
        &request_work
    } else {
        &shadow_work
    };''')
    old = "match load_retrieval_context(current, owner, body_generation, executor, &request_work)"
    text = replace(text, old, "match load_retrieval_context(current, owner, body_generation, executor, retrieval_work)")
    text = replace(text, '''.run(&request_work, move |work| {
                    execute_owner_observation_controlled(''', '''.run(retrieval_work, move |work| {
                    execute_owner_observation_controlled(''')
    text = replace(text, '''let appended = executor
            .run(&request_work, move |work| {''', '''let appended = executor
            .run(retrieval_work, move |work| {''')
    # Every future owns its bounded arguments. No caller borrow can outlive its
    # waiter, and no timeout cancels the capacity accounting of a SQLite command.
    patterns = (
        (r"store\.lane_c_snapshot\(&access, &scope, (\w+)\)",
         lambda m: '{ let store = store.clone(); let access = access.clone(); let scope = scope.clone(); async move { store.lane_c_snapshot(&access, &scope, ' + m[1] + ').await } }', 2),
        (r"store\.observe_memory_retrieval\(&access, &RetrievalRequest::new\(query, now\)\)",
         lambda m: '{ let store = store.clone(); let access = access.clone(); let query = query.to_string(); async move { store.observe_memory_retrieval(&access, &RetrievalRequest::new(&query, now)).await } }', 1),
        (r"store\.revalidate_memory_candidates\(&access, &ordered_bindings, revalidation_now\)",
         lambda m: '{ let store = store.clone(); let access = access.clone(); let ordered_bindings = ordered_bindings.clone(); async move { store.revalidate_memory_candidates(&access, &ordered_bindings, revalidation_now).await } }', 1),
        (r"store\.revalidate_lane_c_snapshot\(&access, &scope, &cut, (\w+)\)",
         lambda m: '{ let store = store.clone(); let access = access.clone(); let scope = scope.clone(); let cut = cut.clone(); async move { store.revalidate_lane_c_snapshot(&access, &scope, &cut, ' + m[1] + ').await } }', 2),
    )
    for pattern, replacement, expected in patterns:
        text, count = re.subn(pattern, replacement, text)
        if count != expected:
            raise RuntimeError(f"owner boundary count: {pattern}: {count} != {expected}")
    source[p] = text

    p = PATHS[3]
    text = source[p]
    dependency = 'codex-hepta-infer-core = { path = "../hepta-infer-core" }\n'
    dev = text.index("[dev-dependencies]")
    if dependency not in text[dev:]:
        raise RuntimeError("expected inference dependency only in dev-dependencies")
    text = replace(text, dependency, "")
    text = replace(text, "[dependencies]\n", "[dependencies]\n" + dependency)
    source[p] = text

    source[PATHS[1]] += '''
#[tokio::test]
async fn cancelled_shadow_preserves_baseline_delivery() {
    let executor = RetrievalExecutor::new();
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    let shadow = executor.begin_shadow(&delivery);
    shadow.control.cancel();
    assert!(executor.run_async(&shadow, async { 1 }).await.is_err());
    assert_eq!(executor.run(&delivery, |_| Ok(2)).await.unwrap(), 2);
    assert_eq!(executor.run_async(&delivery, async { 3 }).await.unwrap(), 3);
}

#[tokio::test]
async fn shadow_cannot_renew_an_expired_parent_deadline() {
    let executor = RetrievalExecutor::new();
    let mut parent = executor.begin(RetrievalWorkClass::Delivery);
    parent.deadline = Instant::now();
    let child = executor.begin_shadow(&parent);
    assert!(child.deadline <= parent.deadline);
    assert!(executor.run_async(&child, async { 1 }).await.is_err());
}

#[tokio::test]
async fn async_timeout_retains_capacity_until_owner_exits() {
    let executor = RetrievalExecutor::new();
    let request = executor.begin(RetrievalWorkClass::Shadow);
    let (release_tx, release_rx) = tokio::sync::oneshot::channel::<()>();
    assert!(executor.run_async(&request, async move {
        let _ = release_rx.await;
        17
    }).await.is_err());
    assert_eq!(executor.shadow.available_permits(), 0);
    let other = executor.begin(RetrievalWorkClass::Shadow);
    assert!(executor.run_async(&other, async { 18 }).await.is_err());
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    assert_eq!(executor.run_async(&delivery, async { 19 }).await.unwrap(), 19);
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        while executor.shadow.available_permits() != 1 {
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
    assert!(executor.run_async(&request, async { 20 }).await.is_err());
}

#[tokio::test]
async fn cancelled_async_wait_keeps_the_owner_operation_charged() {
    let executor = Arc::new(RetrievalExecutor::new());
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = tokio::sync::oneshot::channel::<()>();
    let running = Arc::clone(&executor);
    let waiter = tokio::spawn(async move {
        let request = running.begin(RetrievalWorkClass::Delivery);
        running.run_async(&request, async move {
            let _ = entered_tx.send(());
            let _ = release_rx.await;
            1
        }).await
    });
    entered_rx.await.unwrap();
    waiter.abort();
    let _ = waiter.await;
    assert_eq!(executor.delivery.available_permits(), 1);
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        while executor.delivery.available_permits() != 2 {
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
}
'''
    for path, text in source.items():
        Path(path).write_text(text, encoding="utf-8")
        print(f"modified {path}")

def manifest(output):
    changes = []
    for path in PATHS:
        content = Path(path).read_text(encoding="utf-8")
        changes.append({"path": path, "before": git("rev-parse", f"HEAD:{path}"), "content": content})
    Path(output).write_text(json.dumps({"base": git("rev-parse", "HEAD"), "changes": changes}), encoding="utf-8")

if __name__ == "__main__":
    if sys.argv[1:] == ["apply"]:
        apply()
    elif len(sys.argv) == 3 and sys.argv[1] == "manifest":
        manifest(sys.argv[2])
    else:
        raise SystemExit("usage: owned_work_patch.py apply | manifest OUTPUT")
