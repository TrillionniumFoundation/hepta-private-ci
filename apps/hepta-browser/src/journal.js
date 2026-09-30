// Stable public import path for the Browser durable owner. The complete v2
// implementation is isolated in journal-v2.js so transition, crash-recovery
// and interprocess-owner semantics can evolve without changing callers.
export {
  FileBrowserOperationJournal,
  MemoryBrowserOperationJournal,
} from "./journal-v2.js";
