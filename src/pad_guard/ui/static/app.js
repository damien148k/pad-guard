// PAD Guard: shell of the local interface (tabs, stepper, settings). The screens display what the
// server sends, built by PAD Guard from its JSON files: no verdict, threshold or severity is computed here.
import { html, render, useState, useEffect, useCallback } from './vendor/preact-htm.module.js';
import { api, url } from './api.js';
import { Logo, Dialog, ErrorLine } from './ui.js';
import { Prep } from './screens/prep.js';
import { Recap } from './screens/recap.js';
import { Run } from './screens/run.js';
import { Report } from './screens/report.js';
import { Profiles } from './screens/profiles.js';
import { Normes } from './screens/normes.js';

const ADMIN = document.querySelector('meta[name="pad-guard-admin"]').content === '1';  // pad-guard ui --admin

const STEPS = [['1', 'Dépôt', 'prep'], ['2', 'Récapitulatif', 'recap'], ['3', 'Analyse', 'run'], ['4', 'Rapport', 'report']];
const TITLES = { prep: 'Nouvelle analyse', recap: 'Récapitulatif', run: 'Analyse', report: 'Rapport', profiles: 'Profils', normes: 'Normes' };
const EMPTY_FORM = { master: null, profile: null, pdf: null, groups: {}, llm: false, llm_model: null };

function Settings({ onClose }) {
  const [root, setRoot] = useState('');
  const [def, setDef] = useState('');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  useEffect(() => { api('/api/settings').then(s => { setRoot(s.analyses_root); setDef(s.default_root); }).catch(e => setError(e.message)); }, []);
  const pick = async () => {
    setError('');
    try { const r = await api('/api/pick', { method: 'POST', body: { kind: 'folder', initial: root } }); if (r.path) setRoot(r.path); }
    catch (e) { setError(e.message); }
  };
  const save = async () => {
    setError(''); setSaved(false);
    try { const s = await api('/api/settings', { method: 'PUT', body: { analyses_root: root } }); setRoot(s.analyses_root); setSaved(true); }
    catch (e) { setError(e.message); }
  };
  return html`<${Dialog} title="Réglages" onClose=${onClose}>
    <div class="col"><span class="label">Dossier des analyses</span>
      <div class="btn-row"><input class="input mono" style="flex:1" value=${root} onInput=${e => setRoot(e.target.value)} aria-label="Dossier des analyses" />
        <button class="btn" onClick=${pick}>Parcourir…</button></div>
      <span class="hint">Chaque analyse y crée un dossier « nom du film_AAAAMMJJ-HHMM ». Par défaut : ${def}</span></div>
    <${ErrorLine} error=${error} />
    ${saved && html`<span class="ok-line"><i></i>Réglage enregistré</span>`}
    <div class="btn-row" style="justify-content:flex-end"><button class="btn" onClick=${onClose}>Fermer</button>
      <button class="btn primary" onClick=${save}>Enregistrer</button></div>
  </${Dialog}>`;
}

function App() {
  const [tab, setTab] = useState('analyse');
  const [screen, setScreen] = useState('prep');
  const [form, setForm] = useState(EMPTY_FORM);
  const [job, setJob] = useState(null);
  const [runId, setRunId] = useState(null);
  const [profiles, setProfiles] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [settings, setSettings] = useState(false);
  const [error, setError] = useState('');

  const loadProfiles = useCallback(() => api('/api/profiles').then(r => { setProfiles(r.profiles); setDrafts(r.drafts); })
    .catch(e => setError(e.message)), []);

  // The job runs on the server: on (re)opening the page, its state comes back from there.
  useEffect(() => {
    loadProfiles();
    const shown = /(?:^#|&)run=([^&]*)/.exec(location.hash);  // a report link: #run=<folder>&a=<anomaly key>
    if (shown) { setRunId(decodeURIComponent(shown[1])); setScreen('report'); }
    api('/api/jobs/current').then(j => {
      setJob(j);
      if (j && j.kind !== 'draft' && j.state === 'running') setScreen('run');
    }).catch(e => setError(e.message));
  }, []);

  const running = job && job.state === 'running';
  useEffect(() => {
    if (!running) return undefined;
    const source = new EventSource(url('/api/jobs/current/events'));
    source.onmessage = e => setJob(JSON.parse(e.data));
    return () => source.close();
  }, [running, job && job.id]);

  useEffect(() => { document.title = `PAD Guard — ${TITLES[tab === 'analyse' ? screen : tab]}`; }, [tab, screen]);

  const go = s => { setTab('analyse'); setScreen(s); };
  const stepIdx = STEPS.findIndex(s => s[2] === screen);
  const canGo = { prep: true, recap: !!(form.master && form.profile), run: !!(job && job.kind !== 'draft'), report: !!runId };
  const pendingDrafts = drafts.filter(d => !d.validated).length;
  const openRun = id => { setRunId(id); history.replaceState(null, '', `#run=${encodeURIComponent(id)}`); go('report'); };
  const newAnalysis = () => { setForm(EMPTY_FORM); go('prep'); };

  let body;
  if (tab === 'normes' && ADMIN) {
    body = html`<${Normes} />`;
  } else if (tab === 'profiles') {
    body = html`<${Profiles} profiles=${profiles} drafts=${drafts} job=${job} setJob=${setJob} reload=${loadProfiles} pdf=${form.pdf}
      useProfile=${name => { setForm(f => ({ ...f, profile: name, pdf: null })); go(form.master ? 'recap' : 'prep'); }} />`;
  } else if (screen === 'prep') {
    body = html`<${Prep} form=${form} setForm=${setForm} profiles=${profiles} job=${job} openRun=${openRun}
      next=${() => go('recap')} toProfiles=${() => setTab('profiles')} />`;
  } else if (screen === 'recap') {
    body = html`<${Recap} form=${form} setForm=${setForm} profiles=${profiles} job=${job} back=${() => go('prep')}
      started=${j => { setJob(j); go('run'); }} toProfiles=${() => setTab('profiles')} />`;
  } else if (screen === 'run') {
    body = html`<${Run} job=${job} setJob=${setJob} openRun=${openRun} newAnalysis=${newAnalysis} />`;
  } else {
    body = html`<${Report} runId=${runId} job=${job} setJob=${j => { setJob(j); go('run'); }} />`;
  }

  return html`<div class="app">
    <header class="topbar">
      <div class="brand"><${Logo} width=${34} /><span>PAD GUARD<b>:</b></span></div>
      <nav class="tabs">
        <button class=${'tab' + (tab === 'analyse' ? ' on' : '')} onClick=${() => setTab('analyse')}>Analyse</button>
        <button class=${'tab' + (tab === 'profiles' ? ' on' : '')} onClick=${() => setTab('profiles')}>Profils
          ${pendingDrafts > 0 && html`<span class="badge">${pendingDrafts} brouillon${pendingDrafts > 1 ? 's' : ''}</span>`}</button>
        ${ADMIN && html`<button class=${'tab' + (tab === 'normes' ? ' on' : '')} onClick=${() => setTab('normes')}>Normes</button>`}
      </nav>
      ${tab === 'analyse' && html`<div class="stepper">${STEPS.map(([n, label, s], i) => html`
        <button class=${'step' + (i === stepIdx ? ' on' : i < stepIdx ? ' past' : '')} disabled=${!canGo[s]} onClick=${() => go(s)}>
          <span>${n}</span><span>${label}</span></button>`)}</div>`}
      <div class="local"><i></i>Local · aucun envoi réseau</div>
      <button class="icon-btn" onClick=${() => setSettings(true)} title="Dossier des analyses">Réglages</button>
    </header>
    <main class="main">${error && html`<div class="page"><${ErrorLine} error=${error} /></div>`}${body}</main>
    ${settings && html`<${Settings} onClose=${() => setSettings(false)} />`}
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
