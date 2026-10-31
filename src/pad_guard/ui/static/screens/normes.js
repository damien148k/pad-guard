// NORMES (pad-guard ui --admin): the norms of normes/ and the house values, their review table and the
// signature; a row corrected (checked by releve-norme on the server), a norm's PDF read by the local AI,
// the domain / region / replaced-by information. Everything shown comes from the server; the page only
// ticks rows and sends what was typed. The server checks again every row ticked, and the file unchanged,
// before signing.
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api, url } from '../api.js';
import { Busy, ErrorLine, ModelPicker } from '../ui.js';

const STATE_COLOR = { to_review: 'var(--amber)', signed: 'var(--green)', modified: 'var(--red)', error: 'var(--red)' };
const SECTIONS = [['renvoi', 'Renvois à d\'autres normes'], ['valeur', 'Valeurs'], ['non_retenu', 'Lu dans la norme, sans valeur dans PAD Guard']];
const INFO = [['domain', 'Domaine', 'ex. audio, vidéo, fichier'], ['region', 'Région', 'ex. international, Europe, France'],
  ['superseded_by', 'Remplacée par', 'ex. ebu_r128 V6, 2026']];
const MARK = { done: '✓', active: '▸', todo: '·', failed: '✕', stopped: '■' };

function StatusTag({ status }) {
  return html`<span class="tag" style=${`color:${STATE_COLOR[status.state] || 'var(--mute)'}`}>${status.label}</span>`;
}

// A norm's PDF: stored in normes\sources\ by the server, read by the local AI (draft-profile --kind norme).
function NewNorm({ job, setJob, reload }) {
  const [form, setForm] = useState({ pdf: '', name: '', title: '', version: '', model: '' });
  const [error, setError] = useState('');
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const mine = job && job.kind === 'draft_norm' ? job : null;
  const busy = job && job.state === 'running';
  useEffect(() => { if (mine && mine.state === 'done') reload(); }, [mine && mine.state]);
  const browse = async () => {
    try { const r = await api('/api/pick', { method: 'POST', body: { kind: 'pdf', initial: form.pdf } }); if (r.path) set('pdf', r.path); }
    catch (e) { setError(e.message); }
  };
  const start = async () => {
    setError('');
    try { setJob(await api('/api/jobs/draft-norm', { method: 'POST', body: form })); } catch (e) { setError(e.message); }
  };
  const cancel = async () => { try { setJob(await api('/api/jobs/current/cancel', { method: 'POST' })); } catch (e) { setError(e.message); } };
  return html`<div class="panel">
    <div class="split"><span class="label">Nouvelle norme depuis son PDF</span><span class="hint">IA locale (Ollama) · plusieurs minutes</span></div>
    <div class="btn-row"><input class="input mono" style="flex:1" placeholder="Chemin du PDF de la norme" value=${form.pdf} onInput=${e => set('pdf', e.target.value)} aria-label="PDF de la norme" />
      <button class="btn" onClick=${browse}>Parcourir…</button></div>
    <div class="btn-row">
      <input class="input mono" style="width:200px" placeholder="nom_de_la_norme" value=${form.name} onInput=${e => set('name', e.target.value)} aria-label="Nom de la norme" />
      <input class="input" style="flex:1" placeholder="Titre (ex. EBU R 128 s2 — Loudness for streaming)" value=${form.title} onInput=${e => set('title', e.target.value)} aria-label="Titre du document" />
      <input class="input" style="width:200px" placeholder="Version (ex. V1, 2021)" value=${form.version} onInput=${e => set('version', e.target.value)} aria-label="Version du document" />
      <button class="btn primary" disabled=${!form.pdf || !form.name || !form.title || !form.version || !form.model || busy} onClick=${start}>Relevé IA</button></div>
    <${ModelPicker} value=${form.model} onChange=${m => set('model', m)} />
    <span class="hint">Le PDF est enregistré dans normes\\sources\\. Chaque proposition de l'IA est vérifiée par le code de releve-norme (citation dans la page, nombre dans la citation) ; une ligne refusée est écartée. Le sens reste à relire, ligne par ligne.</span>
    <${ErrorLine} error=${error} />
    ${mine && html`<div class="col" style="gap:8px;border-top:1px solid var(--line);padding-top:12px">
      <div class="split"><span class="label">${mine.title}</span><span class="hint">${mine.elapsed}${mine.remaining ? ' · restant ' + mine.remaining : ''}</span></div>
      <div class="stages" style="border-top:0">${mine.stages.map(s => html`<div class=${'stage ' + s.state} style="grid-template-columns:28px minmax(0,1fr) 220px 110px;padding:8px 0">
        <span class="m">${MARK[s.state]}</span><span class="l" style="font-size:16px">${s.label}</span><span class="c">${s.files}</span><span class="i">${s.info}</span></div>`)}</div>
      ${mine.errors.length > 0 && html`<div class="error">${mine.errors.join('\n')}</div>`}
      ${mine.state === 'running' && html`<div class="btn-row"><button class="btn" onClick=${cancel}>Annuler</button></div>`}</div>`}
  </div>`;
}

function Drafts({ drafts, open }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  if (!drafts.length) return null;
  const make = async name => {
    setError(''); setBusy(name);
    try { await api(`/api/normes/drafts/${name}/survey`, { method: 'POST' }); open(name); } catch (e) { setError(e.message); }
    setBusy('');
  };
  return html`<div class="table"><div class="table-head"><span class="label">Relevés de l'IA à mettre en fiche</span></div>
    ${drafts.map(d => html`<div class="norm-row" style="cursor:default">
      <span><b>${d.title || d.name}</b><br /><span class="hint mono">${d.name}</span></span>
      <span class="mono">${d.model || '—'}</span><span class="mono">${d.version || '—'}</span>
      <span class="mono">${d.proposals} proposition${d.proposals > 1 ? 's' : ''}</span>
      <span><button class="btn" disabled=${!!busy} onClick=${() => make(d.name)}>${busy === d.name ? 'Vérification…' : 'Créer la fiche'}</button></span></div>`)}
    <${ErrorLine} error=${error} /></div>`;
}

function List({ norms, drafts, open, job, setJob, reload }) {
  return html`<div class="page">
    <div class="head"><span class="kicker">Administration</span><h1>Normes</h1>
      <p class="lead">Chaque norme lue par PAD Guard et les valeurs maison : relire chaque ligne, cocher OK, signer.</p></div>
    <div class="table">
      <div class="norm-row norm-head"><span>Norme</span><span>Organisme</span><span>Version</span><span>PDF</span><span>Statut</span></div>
      ${norms.map(n => html`<button class="norm-row" onClick=${() => open(n.name)} aria-label=${'Ouvrir ' + n.name}>
        <span><b>${n.title || n.name}</b><br /><span class="hint mono">${n.name}${[n.domain, n.region].filter(Boolean).map(t => ' · ' + t).join('')}${n.superseded_by ? ' · remplacée par ' + n.superseded_by : ''}</span></span>
        <span>${n.body || '—'}</span><span class="mono">${n.version || '—'}</span>
        <span class="mono">${n.pdf_present === null || n.pdf_present === undefined ? 'sans PDF' : n.pdf_present ? 'présent' : 'absent'}</span>
        <span>${n.error ? html`<span class="error">${n.error}</span>` : html`<${StatusTag} status=${n.status} />`}</span></button>`)}
    </div>
    <${Drafts} drafts=${drafts} open=${open} />
    <${NewNorm} job=${job} setJob=${setJob} reload=${reload} />
  </div>`;
}

function Info({ sheet, setSheet }) {
  const [form, setForm] = useState(Object.fromEntries(INFO.map(([k]) => [k, sheet[k] || ''])));
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const save = async () => {
    setError(''); setSaved(false);
    try { setSheet(await api(`/api/normes/${sheet.name}/info`, { method: 'PUT', body: form })); setSaved(true); }
    catch (e) { setError(e.message); }
  };
  return html`<div class="panel">
    <div class="split"><span class="label">Informations sur le document</span><span class="hint">sans effet sur les valeurs ni sur la signature</span></div>
    <div class="btn-row">${INFO.map(([k, label, hint]) => html`<input class="input" style="flex:1" placeholder=${label + ' (' + hint + ')'}
      value=${form[k]} onInput=${e => { setForm(f => ({ ...f, [k]: e.target.value })); setSaved(false); }} aria-label=${label} />`)}
      <button class="btn" onClick=${save}>Enregistrer</button></div>
    ${saved && html`<span class="ok-line"><i></i>Enregistré dans meta</span>`}
    <${ErrorLine} error=${error} /></div>`;
}

function Correct({ name, row, done, cancel }) {
  const [form, setForm] = useState({ valeur: row.valeur, page: row.page ?? '', citation: row.citation });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setError(''); setBusy(true);
    try { done(await api(`/api/normes/${name}/correct`, { method: 'POST', body: { key: row.key, ...form } })); }
    catch (e) { setError(e.message); }
    setBusy(false);
  };
  return html`<div class="correct">
    ${row.kind === 'valeur' && html`<label class="col" style="gap:4px"><span class="label">Valeur</span>
      <input class="input mono" value=${form.valeur} onInput=${e => setForm(f => ({ ...f, valeur: e.target.value }))} aria-label="Valeur corrigée" /></label>`}
    <label class="col" style="gap:4px"><span class="label">Page</span>
      <input class="input mono" style="width:90px" value=${form.page} onInput=${e => setForm(f => ({ ...f, page: e.target.value }))} aria-label="Page corrigée" /></label>
    <label class="col" style="gap:4px;flex:1"><span class="label">Citation (copiée du PDF)</span>
      <textarea class="input" rows="3" value=${form.citation} onInput=${e => setForm(f => ({ ...f, citation: e.target.value }))} aria-label="Citation corrigée"></textarea></label>
    <div class="btn-row"><button class="btn" onClick=${cancel}>Annuler</button>
      <button class="btn primary" disabled=${busy} onClick=${send}>${busy ? 'Vérification dans le PDF…' : 'Vérifier et corriger'}</button></div>
    <${ErrorLine} error=${error} /></div>`;
}

function Sheet({ name, back, reload }) {
  const [sheet, setSheet] = useState(null);
  const [checked, setChecked] = useState({});
  const [editing, setEditing] = useState(null);
  const [by, setBy] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = () => api(`/api/normes/${name}`).then(s => { setSheet(s); setChecked({}); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, [name]);
  if (!sheet) return html`<div class="page">${error ? html`<${ErrorLine} error=${error} />` : html`<${Busy} text="Lecture de la norme…" />`}</div>`;
  const all = sheet.rows.length > 0 && sheet.rows.every(r => checked[r.key]);
  const sign = async () => {
    setError(''); setBusy(true);
    try {
      const s = await api(`/api/normes/${name}/sign`, { method: 'POST', body: { by, checked: Object.keys(checked).filter(k => checked[k]) } });
      setSheet(s); setChecked({}); reload();
    } catch (e) { setError(e.message); }
    setBusy(false);
  };
  const toggle = key => setChecked(c => ({ ...c, [key]: !c[key] }));
  const corrected = s => { setSheet(s); setEditing(null); setChecked({}); reload(); };
  return html`<div class="page">
    <div class="head"><button class="mini" style="align-self:flex-start" onClick=${back}>← Normes</button>
      <span class="kicker">${sheet.body || ''} · ${sheet.version || ''}</span><h1>${sheet.title || sheet.name}</h1>
      ${sheet.document && sheet.document !== sheet.title && html`<p class="lead">${sheet.document}</p>`}
      <div class="btn-row"><${StatusTag} status=${sheet.status} />
        <span class="hint mono">${sheet.pdf ? (sheet.pdf_present ? sheet.pdf : sheet.pdf + ' (absent de normes\\sources\\)') : 'sans PDF'}</span>
        <span class="hint mono">Tableau : ${sheet.table}</span></div>
      ${sheet.status.problems.length > 0 && html`<div class="error">${sheet.status.problems.join('\n')}</div>`}</div>
    <div class="note">Pour chaque ligne, cliquer sur la page ouvre le PDF à cette page : comparer la valeur à la citation, puis cocher OK.
      Un champ absent du tableau n'est pas contrôlé par la norme. La signature ne porte que sur ce tableau.
      ${sheet.correction_refusal ? html`Correction : ${sheet.correction_refusal}.` : html`Une ligne fausse : « Corriger » (valeur, page, citation vérifiées dans le PDF par releve-norme), puis nouvelle signature.`}</div>
    ${SECTIONS.map(([kind, title]) => {
      const rows = sheet.rows.filter(r => r.kind === kind);
      if (!rows.length) return null;
      return html`<div class="table"><div class="table-head"><span class="label">${title}</span></div>
        <div class="nrow nrow-head"><span>OK</span><span>Champ</span><span>Valeur</span><span>Page</span><span>Citation</span><span>Remarque</span></div>
        ${rows.map(r => html`<div class=${'nrow' + (checked[r.key] ? ' ok' : '')}>
          <label class="check"><input type="checkbox" checked=${!!checked[r.key]} onChange=${() => toggle(r.key)} aria-label=${'OK ' + r.champ} /></label>
          <span>${r.label && html`<span>${r.label}</span><br />`}<span class="hint mono">${r.champ}</span></span>
          <span class="mono">${r.valeur}${r.unite ? ' ' + r.unite : ''}</span>
          <span class="mono">${r.page == null ? '—' : r.pdf
            ? html`<a href=${url(r.pdf) + '#page=' + r.page} target="_blank" rel="noopener" title=${'Ouvrir ' + (r.document || 'le PDF') + ' p. ' + r.page}>p. ${r.page}</a>`
            : 'p. ' + r.page}${r.document && r.document !== sheet.rows[0].document ? html`<br /><span class="hint">${r.document}</span>` : ''}</span>
          <span class="quote">${r.citation ? (r.quote ? `« ${r.citation} »` : r.citation) : '—'}</span>
          <span class="hint">${r.remarque}${r.correctable && editing !== r.key && html`<br /><button class="mini" style="margin-top:6px" onClick=${() => setEditing(r.key)} aria-label=${'Corriger ' + r.champ}>Corriger</button>`}</span>
          ${editing === r.key && html`<${Correct} name=${name} row=${r} done=${corrected} cancel=${() => setEditing(null)} />`}</div>`)}</div>`;
    })}
    ${sheet.absents && html`<div class="note"><span class="label">Champs absents</span><br />${sheet.absents}</div>`}
    <${Info} key=${sheet.name} sheet=${sheet} setSheet=${setSheet} />
    <div class="panel">
      <div class="split"><span class="label">Signature</span><span class="hint">${Object.values(checked).filter(Boolean).length} / ${sheet.rows.length} lignes cochées</span></div>
      <div class="btn-row"><input class="input" style="width:320px" placeholder="Nom du validateur" value=${by} onInput=${e => setBy(e.target.value)} aria-label="Nom du validateur" />
        <button class="btn primary" disabled=${!all || !by.trim() || busy} onClick=${sign}>Signer</button></div>
      <span class="hint">Écrit validated_by, validated_at et l'empreinte du fichier dans normes/${sheet.name}.yaml ; une modification ultérieure du fichier remet « modifiée depuis la signature ».</span>
      <${ErrorLine} error=${error} /></div>
  </div>`;
}

export function Normes({ job, setJob }) {
  const [norms, setNorms] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState('');
  const load = () => api('/api/normes').then(r => { setNorms(r.norms); setDrafts(r.drafts); }).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);
  if (open) return html`<${Sheet} name=${open} back=${() => { setOpen(null); load(); }} reload=${load} />`;
  if (!norms) return html`<div class="page">${error ? html`<${ErrorLine} error=${error} />` : html`<${Busy} text="Lecture de normes/…" />`}</div>`;
  return html`<${List} norms=${norms} drafts=${drafts} open=${setOpen} job=${job} setJob=${setJob} reload=${load} />`;
}
