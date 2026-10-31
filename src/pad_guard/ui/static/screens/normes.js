// NORMES (pad-guard ui --admin): the norms of normes/ and the house values, their review table and the
// signature. Everything shown comes from the server (survey, norm, signature status); the page only ticks
// the rows. The server checks again that every row is ticked, and the file unchanged, before signing.
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api, url } from '../api.js';
import { Busy, ErrorLine } from '../ui.js';

const STATE_COLOR = { to_review: 'var(--amber)', signed: 'var(--green)', modified: 'var(--red)', error: 'var(--red)' };
const SECTIONS = [['renvoi', 'Renvois à d\'autres normes'], ['valeur', 'Valeurs'], ['non_retenu', 'Lu dans la norme, sans valeur dans PAD Guard']];

function StatusTag({ status }) {
  return html`<span class="tag" style=${`color:${STATE_COLOR[status.state] || 'var(--mute)'}`}>${status.label}</span>`;
}

function List({ norms, open }) {
  return html`<div class="page">
    <div class="head"><span class="kicker">Administration</span><h1>Normes</h1>
      <p class="lead">Chaque norme lue par PAD Guard et les valeurs maison : relire chaque ligne, cocher OK, signer.</p></div>
    <div class="table">
      <div class="norm-row norm-head"><span>Norme</span><span>Organisme</span><span>Version</span><span>PDF</span><span>Statut</span></div>
      ${norms.map(n => html`<button class="norm-row" onClick=${() => open(n.name)} aria-label=${'Ouvrir ' + n.name}>
        <span><b>${n.title || n.name}</b><br /><span class="hint mono">${n.name}</span></span>
        <span>${n.body || '—'}</span><span class="mono">${n.version || '—'}</span>
        <span class="mono">${n.pdf_present === null || n.pdf_present === undefined ? 'sans PDF' : n.pdf_present ? 'présent' : 'absent'}</span>
        <span>${n.error ? html`<span class="error">${n.error}</span>` : html`<${StatusTag} status=${n.status} />`}</span></button>`)}
    </div></div>`;
}

function Sheet({ name, back, reload }) {
  const [sheet, setSheet] = useState(null);
  const [checked, setChecked] = useState({});
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
      Une correction se fait par ${html`<span class="mono">${sheet.correction}</span>`}, puis nouvelle signature.</div>
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
          <span class="hint">${r.remarque}</span></div>`)}</div>`;
    })}
    ${sheet.absents && html`<div class="note"><span class="label">Champs absents</span><br />${sheet.absents}</div>`}
    <div class="panel">
      <div class="split"><span class="label">Signature</span><span class="hint">${Object.values(checked).filter(Boolean).length} / ${sheet.rows.length} lignes cochées</span></div>
      <div class="btn-row"><input class="input" style="width:320px" placeholder="Nom du validateur" value=${by} onInput=${e => setBy(e.target.value)} aria-label="Nom du validateur" />
        <button class="btn primary" disabled=${!all || !by.trim() || busy} onClick=${sign}>Signer</button></div>
      <span class="hint">Écrit validated_by, validated_at et l'empreinte du fichier dans normes/${sheet.name}.yaml ; une modification ultérieure du fichier remet « modifiée depuis la signature ».</span>
      <${ErrorLine} error=${error} /></div>
  </div>`;
}

export function Normes() {
  const [norms, setNorms] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState('');
  const load = () => api('/api/normes').then(r => setNorms(r.norms)).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);
  if (open) return html`<${Sheet} name=${open} back=${() => { setOpen(null); load(); }} reload=${load} />`;
  if (!norms) return html`<div class="page">${error ? html`<${ErrorLine} error=${error} />` : html`<${Busy} text="Lecture de normes/…" />`}</div>`;
  return html`<${List} norms=${norms} open=${setOpen} />`;
}
