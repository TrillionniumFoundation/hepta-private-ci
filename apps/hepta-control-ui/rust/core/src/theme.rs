//! Shared presentation tokens; colors never stand in for observed runtime state.
//! The canonical native host may consume these after source-branch convergence.
pub const BACKGROUND: &str = "#0a0f18";
pub const SURFACE: &str = "#111926";
pub const BORDER: &str = "#354860";
pub const TEXT: &str = "#e6edf7";
pub const MUTED: &str = "#a6b7cd";
pub const CYAN: &str = "#69e0e8";
pub const VIOLET: &str = "#b8a6ff";
pub const WARNING: &str = "#ffcf80";
pub const ERROR: &str = "#ffa4ae";

/// External static stylesheet generated from Rust, compatible with style-src 'self'.
pub fn browser_stylesheet() -> String {
    format!(
        r#":root {{
  color-scheme: dark;
  --background: {BACKGROUND}; --surface: {SURFACE}; --border: {BORDER};
  --text: {TEXT}; --muted: {MUTED}; --cyan: {CYAN}; --violet: {VIOLET};
  --warning: {WARNING}; --error: {ERROR};
  background: var(--background); color: var(--text);
}}
body {{ background: radial-gradient(ellipse at 90% 0%, #202b48 0, transparent 45%), var(--background); }}
header {{ padding-top: 2.5rem; padding-bottom: 1rem; }}
header h1 {{ margin: 0; letter-spacing: -.04em; font-size: clamp(2rem, 5vw, 3rem); }}
header p {{ color: var(--muted); max-width: 60ch; }}
main {{ padding-bottom: 4rem; }}
section {{ background: var(--surface); border-color: var(--border); border-radius: 1rem; padding: 1.5rem; box-shadow: 0 1rem 3rem #0002; }}
h2 {{ margin-top: 0; font-size: 1.2rem; letter-spacing: .01em; }}
.summary-grid {{ gap: 1rem; }}
.summary-grid div {{ border: 1px solid var(--border); border-radius: .65rem; padding: 1rem; background: #0c1420; }}
.summary-grid dt {{ color: var(--muted); font-size: .8rem; letter-spacing: .08em; text-transform: uppercase; }}
.summary-grid dd {{ margin: .45rem 0 0; color: var(--cyan); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
th {{ background: #0c1420; color: var(--muted); font-size: .8rem; letter-spacing: .04em; }}
th, td {{ border-color: var(--border); padding: .85rem; }}
select, textarea {{ background: #0c1420; color: var(--text); border: 1px solid #4e6784; border-radius: .5rem; padding: .75rem; }}
button {{ background: #1d3041; color: var(--text); border: 1px solid #4e6784; border-radius: .5rem; cursor: pointer; }}
button:hover:not(:disabled) {{ border-color: var(--cyan); background: #254359; }}
button:disabled {{ background: #17202e; color: var(--muted); cursor: not-allowed; }}
.danger {{ border-color: #a96270; color: var(--error); }}
button:focus-visible, select:focus-visible, textarea:focus-visible, .table-scroll:focus-visible, a:focus-visible {{ outline-color: var(--cyan); }}
.warning {{ color: var(--warning); background: #332716; border-radius: .5rem; }}
.error {{ color: var(--error); background: #351e2a; border-radius: .5rem; }}
#pending-list, #completed-list {{ padding-left: 1.3rem; overflow-wrap: anywhere; }}
#pending-list li, #completed-list li {{ margin-block: .75rem; font-variant-numeric: tabular-nums; }}
#pending-list button {{ margin-left: .6rem; }}
dialog {{ background: var(--surface); color: var(--text); border: 1px solid var(--violet); border-radius: 1rem; padding: 1.75rem; box-shadow: 0 2rem 8rem #0008; }}
dialog::backdrop {{ background: #030711b8; }}
/* Instrument-panel hierarchy: semantic labels and real status values remain text. */
body {{ background: radial-gradient(ellipse at 95% 0%, #1d2c42 0, transparent 48%), var(--background); }}
header {{ padding-top: 2rem; padding-bottom: .25rem; }}
.eyebrow {{ color: var(--cyan); font: 600 .75rem ui-monospace, monospace; letter-spacing: .2em; margin: 0 0 .65rem; }}
header h1 {{ font-size: clamp(1.9rem, 4vw, 2.75rem); font-weight: 650; }}
header p {{ margin-top: .6rem; }}
section {{ border-radius: .65rem; padding: 1.25rem; border-top: 2px solid #476174; margin-block: 1rem; }}
h2 {{ display: flex; align-items: baseline; gap: .65rem; font-size: 1rem; letter-spacing: .035em; }}
.section-index {{ font: 600 .7rem ui-monospace, monospace; color: var(--cyan); border: 1px solid #42606c; padding: .2rem .35rem; border-radius: .2rem; }}
.summary-grid {{ gap: .65rem; }}
.summary-grid div {{ padding: .75rem; border-radius: .35rem; border-top-color: #527788; }}
.summary-grid dd {{ font-family: ui-monospace, monospace; font-size: .95rem; }}
.table-scroll {{ border-radius: .3rem; }}
table {{ min-width: 38rem; }}
th, td {{ padding: .7rem; white-space: nowrap; overflow-wrap: normal; }}
td:first-child, td:nth-child(3), td:nth-child(4) {{ font-family: ui-monospace, monospace; font-size: .85rem; }}
.status-chip {{ display: inline-flex; align-items: center; gap: .45rem; padding: .2rem .5rem; border: 1px solid #4e6784; border-radius: .25rem; font: 500 .8rem ui-monospace, monospace; }}
.status-chip::before {{ content: ""; width: .45rem; height: .45rem; background: currentColor; border-radius: 50%; }}
.status-chip[data-status="ready"], .status-chip[data-status="running"] {{ color: var(--cyan); background: #12303a; border-color: #38616a; }}
.status-chip[data-status="degraded"] {{ color: var(--warning); background: #332716; border-color: #796337; }}
.status-chip[data-status="degraded"]::before {{ border-radius: 0; transform: rotate(45deg); }}
.status-chip[data-status="failed"] {{ color: var(--error); background: #351e2a; border-color: #895361; }}
button {{ font-size: .9rem; font-weight: 550; border-radius: .35rem; padding-inline: .85rem; }}
#request-reconcile {{ border-color: #65979e; }}
select {{ appearance: none; padding-right: 2.5rem; background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%); background-position: calc(100% - 1.15rem) 50%, calc(100% - .85rem) 50%; background-size: .3rem .3rem; background-repeat: no-repeat; }}
textarea {{ min-height: 5rem; }}
#confirm-summary {{ overflow-wrap: anywhere; }}
dialog {{ max-width: min(38rem, calc(100vw - 3rem)); box-sizing: border-box; padding: 1.25rem; }}
@media (min-width: 64rem) {{ main {{ display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr); column-gap: 1.25rem; }} main > section {{ min-width: 0; }} main > section:first-child {{ grid-column: 1 / -1; }} }}
@media (max-width: 42rem) {{ section {{ padding: 1rem; }} .summary-grid {{ grid-template-columns: 1fr; }} .button-row button {{ flex: 1 1 100%; }} }}
@media (min-width: 23rem) and (max-width: 42rem) {{ .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .summary-grid div:last-child {{ grid-column: 1 / -1; }} }}
@media (forced-colors: active) {{ body, section, .summary-grid div, th, select, textarea, button, dialog {{ background: Canvas; color: CanvasText; border-color: CanvasText; box-shadow: none; }} .summary-grid dd, .summary-grid dt, .error, .warning, .danger {{ color: CanvasText; }} }}
"#
    )
}
