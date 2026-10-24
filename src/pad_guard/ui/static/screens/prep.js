// Étape 1 · Dépôt. The film is chosen by its path (native dialog opened by the server, or typed):
// a 120 GB master never goes through the browser. The format comes from probe (without the hash).
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api } from '../api.js';
import { Corners, Logo, Busy, ErrorLine } from '../ui.js';
import { RecentRuns } from './runs.js';

function profileLine(p) {
  if (p.error) return 'profil invalide : ' + p.error;
  const status = p.status === 'validated' ? `validé${p.validated_at ? ' le ' + p.validated_at.split('-').reverse().join('/') : ''}` : 'brouillon, non validé';
  return `${p.broadcaster} · v${p.version} · ${status}`;
}

function PathPicker({ kind, label, placeholder, onPath, initial }) {
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const browse = async () => {
    setError('');
    try { const r = await api('/api/pick', { method: 'POST', body: { kind, initial } }); if (r.path) onPath(r.path, setError); }
    catch (e) { setError(e.message); }
  };
  return html`<button class="btn" onClick=${browse}>Parcourir…</button>
    <div class="path"><input class="input mono" placeholder=${placeholder} value=${text} onInput=${e => setText(e.target.value)}
      onKeyDown=${e => { if (e.key === 'Enter' && text.trim()) onPath(text.trim(), setError); }} aria-label=${label} />
      <button class="mini" disabled=${!text.trim()} onClick=${() => onPath(text.trim(), setError)}>Utiliser</button></div>
    <${ErrorLine} error=${error} />`;
}

function Master({ form, setForm, caps }) {
  const m = form.master, pv = form.preview;
  const [error, setError] = useState('');
  const choose = async (path, fail) => {
    try { const info = await api('/api/file-info', { method: 'POST', body: { path } }); setForm(f => ({ ...f, master: info, preview: null, assign: null })); }
    catch (e) { fail(e.message); }
  };
  // Format preview as soon as the film and the profile are known (the checks depend on the profile).
  useEffect(() => {
    if (!m || !form.profile || (pv && pv.master.path === m.path && pv.profile === form.profile)) return;
    let live = true;
    setError('');
    setForm(f => ({ ...f, preview: { loading: true, master: m, profile: form.profile } }));
    api('/api/probe-preview', { method: 'POST', body: { path: m.path, profile: form.profile } })
      .then(r => live && setForm(f => ({ ...f, preview: { ...r, profile: form.profile }, assign: r.assign })))
      .catch(e => { if (live) { setError(e.message); setForm(f => ({ ...f, preview: { failed: true, master: m, profile: form.profile } })); } });
    return () => { live = false; };
  }, [m && m.path, form.profile]);

  if (!m) {
    return html`<div class="zone bp"><${Corners} />
      <${Logo} width=${64} variant="outline" ink="#749dc4" accent="#749dc4" />
      <span class="big">Choisissez le film master</span>
      <span class="small">${caps ? caps.summary + '. ' : ''}Le film reste où il est : PAD Guard le lit sur place.</span>
      <${PathPicker} kind="master" label="Chemin du film master" placeholder="ou collez le chemin : D:\\Masters\\film.mov" onPath=${choose} /></div>`;
  }
  return html`<div class="card bp"><${Corners} />
    <div class="card-head"><div class="film-icon">master</div>
      <div class="name"><span>${m.name}</span><span class="sub">${m.size} · ${m.path}</span></div>
      <button class="mini" onClick=${() => setForm(f => ({ ...f, master: null, preview: null, assign: null }))}>Retirer</button></div>
    ${!m.supported_extension && html`<span class="ok-line amber"><i></i>Extension inattendue : PAD Guard attend ${caps ? caps.extensions.join(', ') : 'un film master'}</span>`}
    ${!form.profile && html`<span class="hint" style="margin-top:auto">Choisissez le profil de chaîne pour lire le format du fichier.</span>`}
    ${pv && pv.loading && html`<${Busy} text="Détection du format…" />`}
    <${ErrorLine} error=${error} />
    ${pv && pv.key_cells && html`<div class="col" style="margin-top:auto">
      ${pv.accepted ? html`<span class="ok-line"><i></i>Format détecté</span>`
        : html`<span class="ok-line red"><i></i>Fichier refusé : ${pv.refusal_reasons.join(' ')}</span>`}
      <div class="cells">${pv.key_cells.map(([k, v]) => html`<div><span class="k">${k}</span><span class="v">${v}</span></div>`)}</div></div>`}
  </div>`;
}

function Broadcaster({ form, setForm, profiles, toProfiles }) {
  const [pdfError, setPdfError] = useState('');
  const choosePdf = async (path, fail) => {
    setPdfError('');
    try {
      const r = await api('/api/pdf-match', { method: 'POST', body: { path } });
      const own = r.profiles.find(p => p.status === 'validated') || r.profiles[0];
      setForm(f => ({ ...f, pdf: r, profile: own ? own.name : f.profile, preview: own ? null : f.preview }));
    } catch (e) { fail(e.message); }
  };
  const pdf = form.pdf;
  const own = pdf && pdf.profiles.length ? pdf.profiles[0] : null;
  return html`<div class="col">
    ${profiles === null ? html`<${Busy} text="Lecture des profils…" />` : html`<div class="profiles">${profiles.map(p => html`
      <button class=${'prof' + (form.profile === p.name ? ' on' : '')} disabled=${!!p.error}
        onClick=${() => setForm(f => ({ ...f, profile: p.name, preview: null, assign: null }))}>
        <span class="radio"></span><span class="t"><span>${p.name}</span><span>${profileLine(p)}</span></span>
        <span class=${'tag ' + (p.status === 'validated' ? 'green' : 'amber')}>${p.status === 'validated' ? 'validé' : 'brouillon'}</span></button>`)}</div>`}
    <div class="panel" style="gap:10px">
      <div class="split"><span class="label">Depuis le cahier des charges</span><span class="hint">PDF du diffuseur</span></div>
      ${!pdf ? html`<div class="btn-row"><${PathPicker} kind="pdf" label="Chemin du PDF" placeholder="ou collez le chemin du PDF" onPath=${choosePdf} /></div>`
        : html`<div class="card-head"><div class="pdf-icon">PDF</div>
            <div class="name"><span style="font-size:20px">${pdf.name}</span><span class="sub">${pdf.pages} pages · SHA-256 ${pdf.sha256.slice(0, 12)}…</span></div>
            <button class="mini" onClick=${() => setForm(f => ({ ...f, pdf: null }))}>Retirer</button></div>
          ${own ? html`<span class=${'ok-line' + (own.status === 'validated' ? '' : ' amber')}><i></i>Document reconnu (même empreinte) : profil ${own.name} v${own.version} (${own.status === 'validated' ? 'validé' : 'brouillon'})</span>`
            : pdf.drafts.length ? html`<span class="ok-line amber"><i></i>Brouillon ${pdf.drafts[0].name} issu de ce document, pas encore validé.
                <button class="btn link" onClick=${toProfiles}>Le relire →</button></span>`
            : html`<span class="ok-line amber"><i></i>Aucun profil ne vient de ce document.
                <button class="btn link" onClick=${toProfiles}>Créer un brouillon avec l'IA locale →</button></span>`}`}
      <${ErrorLine} error=${pdfError} />
    </div>
  </div>`;
}

export function Prep({ form, setForm, profiles, job, next, toProfiles, openRun }) {
  // Formats PAD Guard measures (formats.py): the hint is never written in the page.
  const [caps, setCaps] = useState(null);
  useEffect(() => { api('/api/capabilities').then(setCaps).catch(() => setCaps(null)); }, []);
  const ready = form.master && form.profile && form.preview && form.preview.accepted;
  const busy = job && job.state === 'running' && job.kind === 'analyze';
  return html`<div class="page">
    <div class="head"><span class="kicker">Étape 1 · Choix des fichiers</span><h1>Nouvelle analyse</h1>
      <p class="lead">Choisissez le film master et le profil de la chaîne. Le format du master est lu dans le fichier.</p></div>
    ${busy && html`<div class="note amber"><b>Analyse en cours</b>${job.title} : une seule analyse à la fois.</div>`}
    <div class="grid2">
      <div class="col"><div class="split"><span class="label">Film master</span><span class="hint">${caps ? caps.summary : ''}</span></div>
        <${Master} form=${form} setForm=${setForm} caps=${caps} /></div>
      <div class="col"><div class="split"><span class="label">Profil de chaîne</span><span class="hint">profiles/*.yaml</span></div>
        <${Broadcaster} form=${form} setForm=${setForm} profiles=${profiles} toProfiles=${toProfiles} /></div>
    </div>
    <${RecentRuns} openRun=${openRun} />
    <div class="footer-bar"><button class="btn primary big" disabled=${!ready} onClick=${next}>Voir le récapitulatif →</button>
      ${!ready && html`<span class="hint">${!form.master ? 'Choisissez le film master' : !form.profile ? 'Choisissez le profil de chaîne'
        : !form.preview || form.preview.loading ? 'Lecture du format…' : 'Fichier refusé par ce profil'}</span>`}</div>
  </div>`;
}
