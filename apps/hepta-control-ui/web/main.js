// Loader boundary only; browser state, rendering and effects live in Rust.
try {
  const { default: init, start } = await import("./pkg/hepta_control_web.js");
  await init();
  await start();
} catch {
  // Rust publishes typed failures after initialization. A loader failure cannot
  // execute Rust, so expose only a fixed non-sensitive, fail-closed diagnostic.
  if (globalThis.__heptaUiControlReadiness?.phase !== "failed") {
    document.documentElement.dataset.uiControlReady = "failed";
    const error = document.getElementById("error-status");
    error.textContent = "UI_CONTROL_STARTUP: The verified browser module could not load. Reload or contact the operator.";
    error.hidden = false;
    document.querySelectorAll("button").forEach(button => { button.disabled = true; });
    Object.defineProperty(globalThis, "__heptaUiControlReadiness", {
      value: Object.freeze({ phase: "failed", errorCode: "UI_CONTROL_STARTUP" }),
      configurable: false, writable: false,
    });
  }
}
