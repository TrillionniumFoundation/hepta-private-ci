# Original scoped compiler result

The actual scoped just fix returned 255 after 29.329 seconds while checking rama dependencies, before Agentd type checking. The preserved 412-byte stderr does not establish OOM, SIGKILL, timeout or ENOSPC as the cause. No autofix was applied and the original source hashes are equal. No tests or JUnit were produced.
