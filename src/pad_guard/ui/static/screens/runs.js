// Analyses already made: the folders of the analyses root (run.json, verdict.json).
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api } from '../api.js';

// Tone written by the server from verdict.json (never recomputed here).
export const TONE = { ok: 'var(--green)', nc: 'var(--red)', draft: 'var(--amber)', none: 'var(--mute)' };

export function RecentRuns({ openRun }) {
  const [runs, setRuns] = useState(null);
  useEffect(() => { api('/api/runs').then(r => setRuns(r.runs)).catch(() => setRuns([])); }, []);
  if (!runs || !runs.length) return null;
  return html`<div class="panel">
    <div class="split"><span class="label">Analyses récentes</span><span class="hint">${runs[0].root}</span></div>
    <div class="runs">${runs.slice(0, 8).map(r => html`
      <button class="run-row" onClick=${() => openRun(r.id)}>
        <span class="f">${r.file_name}</span><span>${r.profile}</span><span>${r.analyzed_at_text}</span>
        <span style=${{ color: TONE[r.tone] }}>${r.label}</span></button>`)}</div></div>`;
}
