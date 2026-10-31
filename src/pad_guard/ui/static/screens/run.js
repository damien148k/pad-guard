// Étape 3 · Analyse: the job of the server (pad-guard analyze in a separate process), as the
// server describes it from the progress lines of the CLI. The percentage is the share of images
// measured; probe (SHA-256 of the whole file) and the audio measurements have no counter.
import { html, useState } from '../vendor/preact-htm.module.js';
import { api } from '../api.js';
import { Dialog } from '../ui.js';

const MARK = { done: '✓', active: '▸', todo: '·', failed: '✕', stopped: '■' };
const KICKER = { running: 'Analyse en cours', done: 'Analyse terminée', failed: "Échec de l'analyse",
  cancelled: 'Analyse annulée', interrupted: 'Analyse interrompue' };

export function Run({ job, setJob, openRun, newAnalysis }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  if (!job || job.kind.startsWith('draft')) {
    return html`<div class="page"><span class="kicker">Étape 3 · Analyse</span><p class="lead">Aucune analyse en cours.</p>
      <div><button class="btn" onClick=${newAnalysis}>Nouvelle analyse</button></div></div>`;
  }
  const running = job.state === 'running', done = job.state === 'done';
  const pct = job.pct === null || job.pct === undefined ? null : Math.floor(job.pct);
  const cells = pct === null ? 0 : pct;
  const cancel = async () => {
    setAsking(false); setError('');
    try { setJob(await api('/api/jobs/current/cancel', { method: 'POST' })); } catch (e) { setError(e.message); }
  };
  const fr = n => (n ?? 0).toLocaleString('fr-FR');
  return html`<div class="run">
    <div class="col" style="gap:28px">
      <div class="head"><span class="kicker" style=${{ color: done ? 'var(--green)' : running ? '' : 'var(--red)' }}>Étape 3 · ${KICKER[job.state] || job.state}</span>
        <h1 class="small">${job.title}</h1><span class="sub">${job.command}</span></div>
      <div class="pct"><span style=${{ color: done ? 'var(--green)' : 'var(--ink)' }}>${pct === null ? '—' : pct + ' %'}</span>
        <div class="counters">
          <div><b>${fr(job.done)}</b>/ ${job.total ? fr(job.total) : '…'} images mesurées</div>
          <div><b>${job.elapsed}</b>écoulé</div>
          <div><b>${done ? '00:00' : job.remaining || '—'}</b>restant${running && !job.remaining ? ' (estimé pendant les mesures image)' : ''}</div></div></div>
      <div class=${'cellbar' + (done ? ' done' : '') + (running && pct === null ? ' indeterminate' : '')}>
        ${Array.from({ length: 100 }, (_, i) => html`<span class=${i < cells ? 'on' : ''}></span>`)}</div>
      <div class="stages">${job.stages.map(s => html`<div class=${'stage ' + s.state}>
        <span class="m">${MARK[s.state]}</span><span class="l">${s.label}</span><span class="c">${s.files}</span><span class="i">${s.info}</span></div>`)}</div>
      ${job.state === 'failed' && html`<div class="note red"><b>La commande s'est arrêtée</b>(code ${job.exit_code}). Messages de PAD Guard dans le journal.</div>`}
    </div>
    <div class="col" style="gap:14px">
      <span class="label">Journal</span>
      <div class="journal">${job.journal.map(l => html`<div><span class="t">${l.t}</span><span class=${'msg ' + (l.tone || '')}>${l.msg}</span></div>`)}</div>
      ${error && html`<div class="error">${error}</div>`}
      <div class="btn-row">
        ${running ? html`<button class="btn" style="flex:1" onClick=${() => setAsking(true)}>Annuler</button>`
          : html`<button class="btn" style="flex:1" onClick=${newAnalysis}>Nouvelle analyse</button>`}
        <button class="btn primary" style="flex:1" disabled=${!(done && job.run_id)} onClick=${() => openRun(job.run_id)}>Voir le rapport</button></div>
    </div>
    ${asking && html`<${Dialog} title="Annuler l'analyse ?" onClose=${() => setAsking(false)}>
      <p class="lead">Les processus de mesure sont arrêtés. Le dossier de l'analyse reste incomplet : il faudra relancer l'analyse.</p>
      <div class="btn-row" style="justify-content:flex-end"><button class="btn" onClick=${() => setAsking(false)}>Continuer l'analyse</button>
        <button class="btn danger" onClick=${cancel}>Annuler l'analyse</button></div></${Dialog}>`}
  </div>`;
}
