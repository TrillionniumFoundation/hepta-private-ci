from pathlib import Path

path = Path("codex-rs/ext/hepta-prompt/src/lib.rs")
text = path.read_text(encoding="utf-8")
old_start = "        tokio::spawn(async move {\n            let prepared ="
new_start = "        std::mem::drop(tokio::spawn(async move {\n            let prepared ="
if text.count(old_start) != 1:
    raise SystemExit("single-flight spawn start changed unexpectedly")
text = text.replace(old_start, new_start, 1)
old_end = "            for waiter in waiters {\n                let _ = waiter.send(value.clone());\n            }\n        });\n    }\n}\n\nimpl ContextContributor"
new_end = "            for waiter in waiters {\n                let _ = waiter.send(value.clone());\n            }\n        }));\n    }\n}\n\nimpl ContextContributor"
if text.count(old_end) != 1:
    raise SystemExit("single-flight spawn end changed unexpectedly")
path.write_text(text.replace(old_end, new_end, 1), encoding="utf-8")
