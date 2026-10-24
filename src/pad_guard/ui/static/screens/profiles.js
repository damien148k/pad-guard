// Profils: the profiles of profiles/, a draft from a broadcaster's PDF (draft-profile, local AI),
// and the review of a draft, field by field (the functions of review-profile). Every field needs
// an explicit decision; implausible values and rules capped by a norm are shown in red.
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api, url } from '../api.js';
import { Corners, Busy, ErrorLine } from '../ui.js';

const STATUS = { A_VERIFIER: ['À vérifier', 'steel'], CONFLIT: ['Conflit', 'amber'], INVRAISEMBLABLE: ['Invraisemblable', 'red'],
  RENVOI_NORME: ['Renvoi à une norme', 'amber'] };
const MARK = { done: '✓', active: '▸', todo: '·', failed: '✕', stopped: '■' };

function slug(text) {
  return (text || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
}

// --- list and new draft -------------------------------------------------------------------

function NewDraft({ pdf, job, setJob, openReview }) {
  const [path, setPath] = useState(pdf ? pdf.path : '');
  const [broadcaster, setBroadcaster] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const draftJob = job && job.kind === 'draft' ? job : null;
  const busy = job && job.state === 'running';
  const browse = async () => {
    try { const r = await api('/api/pick', { method: 'POST', body: { kind: 'pdf', initial: path } }); if (r.path) setPath(r.path); }
    catch (e) { setError(e.message); }
  };
  const start = async () => {
    setError('');
    try { setJob(await api('/api/jobs/draft', { method: 'POST', body: { pdf: path, name, broadcaster } })); }
    catch (e) { setError(e.message); }
  };
  const cancel = async () => { try { setJob(await api('/api/jobs/current/cancel', { method: 'POST' })); } catch (e) { setError(e.message); } };
  const draftName = draftJob && draftJob.result && draftJob.result.draft ? draftJob.result.draft.split(/[\\/]/).pop().replace(/\.yaml$/, '') : null;
  return html`<div class="panel">
    <div class="split"><span class="label">Nouveau brouillon depuis le cahier des charges</span><span class="hint">IA locale (Ollama) · plusieurs minutes</span></div>
    <div class="btn-row"><input class="input mono" style="flex:1" placeholder="Chemin du PDF du diffuseur" value=${path} onInput=${e => setPath(e.target.value)} aria-label="PDF du diffuseur" />
      <button class="btn" onClick=${browse}>Parcourir…</button></div>
    <div class="btn-row"><input class="input" style="flex:1" placeholder="Diffuseur (ex. France Télévisions)" value=${broadcaster}
        onInput=${e => { setBroadcaster(e.target.value); if (!name || name === slug(broadcaster)) setName(slug(e.target.value)); }} aria-label="Diffuseur" />
      <input class="input mono" style="width:260px" placeholder="nom_du_profil" value=${name} onInput=${e => setName(e.target.value)} aria-label="Nom du profil" />
      <button class="btn primary" disabled=${!path || !name || busy} onClick=${start}>Extraire (IA locale)</button></div>
    <span class="hint">Chaque valeur proposée est « à vérifier » : la citation est contrôlée dans le PDF, seul un humain confirme le sens. Le PDF est copié dans diffuseurs/.</span>
    <${ErrorLine} error=${error} />
    ${draftJob && html`<div class="col" style="gap:8px;border-top:1px solid var(--line);padding-top:12px">
      <div class="split"><span class="label">${draftJob.title}</span><span class="hint">${draftJob.elapsed}${draftJob.remaining ? ' · restant ' + draftJob.remaining : ''}</span></div>
      <div class="stages" style="border-top:0">${draftJob.stages.map(s => html`<div class=${'stage ' + s.state} style="grid-template-columns:28px minmax(0,1fr) 220px 110px;padding:8px 0">
        <span class="m">${MARK[s.state]}</span><span class="l" style="font-size:16px">${s.label}</span><span class="c">${s.files}</span><span class="i">${s.info}</span></div>`)}</div>
      ${draftJob.errors.length > 0 && html`<div class="error">${draftJob.errors.join('\n')}</div>`}
      <div class="btn-row">${draftJob.state === 'running' && html`<button class="btn" onClick=${cancel}>Annuler</button>`}
        ${draftJob.state === 'done' && draftName && html`<button class="btn primary" onClick=${() => openReview(draftName)}>Relire le brouillon ${draftName} →</button>`}</div></div>`}
  </div>`;
}

function List({ profiles, drafts, pdf, job, setJob, openReview, useProfile }) {
  return html`<div class="list-page">
    <div class="head"><span class="kicker">Profils de chaîne</span><h1>Profils</h1>
      <p class="lead">Un profil validé peut produire un verdict CONFORME ; un brouillon ne donne qu'un résultat indicatif.</p></div>
    <div class="grid2">
      <div class="col"><span class="label">Profils (profiles/)</span>
        ${profiles === null ? html`<${Busy} text="Lecture des profils…" />` : html`<div class="profiles">${profiles.map(p => html`
          <div class="prof" style="cursor:default"><span></span><span class="t"><span>${p.name}</span>
            <span>${p.error ? 'profil invalide : ' + p.error : `${p.broadcaster} · v${p.version} · ${p.status === 'validated' ? `validé par ${p.validated_by} le ${(p.validated_at || '').split('-').reverse().join('/')}` : 'brouillon'}`}</span></span>
            <span class="btn-row"><span class=${'tag ' + (p.status === 'validated' ? 'green' : 'amber')}>${p.status === 'validated' ? 'validé' : 'brouillon'}</span>
              ${!p.error && html`<button class="mini" onClick=${() => useProfile(p.name)}>Analyser</button>`}</span></div>`)}</div>`}
        <span class="label" style="margin-top:12px">Brouillons à relire (profiles/drafts/)</span>
        <div class="profiles">${drafts.map(d => html`<div class="prof" style="cursor:default"><span></span>
          <span class="t"><span>${d.name}</span><span>${d.broadcaster || ''} · ${d.source_document || ''}${d.pages ? ` · ${d.pages} p.` : ''}</span></span>
          <span class="btn-row"><span class=${'tag ' + (d.validated ? 'green' : 'amber')}>${d.validated ? 'profil validé' : 'à relire'}</span>
            <button class="mini" onClick=${() => openReview(d.name)}>Relire →</button></span></div>`)}
          ${drafts.length === 0 && html`<div class="empty">Aucun brouillon.</div>`}</div>
      </div>
      <div class="col"><${NewDraft} pdf=${pdf} job=${job} setJob=${setJob} openReview=${openReview} /></div>
    </div></div>`;
}

// --- review --------------------------------------------------------------------------------

function Finding({ x, on, onClick }) {
  return html`<button class=${'cand' + (on ? ' on' : '') + (x.implausible ? ' red' : '')} onClick=${onClick}>
    <span class="v">${x.value ?? '—'}</span>
    <span class="col" style="gap:4px"><span class="q">p. ${x.page} · « ${x.quote} »</span>
      ${x.implausible && html`<span class="why">INVRAISEMBLABLE : ${x.reason}</span>`}
      ${!x.implausible && x.reason && html`<span class="fine">${x.status} : ${x.reason}</span>`}</span></button>`;
}

function Editor({ name, q, pos, total, onDecided, next, showPage, setQuote }) {
  const [cand, setCand] = useState(null);
  const [fix, setFix] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { setCand(null); setFix(null); setError(''); }, [q.path]);
  const send = async (answer, extra = {}) => {
    setError('');
    try { onDecided(await api(`/api/drafts/${name}/decision`, { method: 'PUT', body: { path: q.path, answer, ...extra } })); setFix(null); }
    catch (e) { setError(e.message); }
  };
  const reset = async () => {
    try { onDecided(await api(`/api/drafts/${name}/decision/reset`, { method: 'POST', body: { path: q.path } })); } catch (e) { setError(e.message); }
  };
  const [label, cls] = STATUS[q.status] || [q.status, 'grey'];
  const can = c => q.choices.includes(c);
  return html`<div class="editor">
    <div class="btn-row"><span class="mono" style="font-size:12px;color:var(--steel-hi)">${q.path}</span><span class=${'tag ' + cls}>${label}</span>
      ${q.answer_label && html`<span class="tag green">${q.answer_label}</span>`}<span class="hint" style="margin-left:auto">${pos} / ${total}</span></div>
    <h2 style="font-size:30px;line-height:1.1">${q.description}</h2>
    ${q.proposal && html`<div class="col"><span class="label">Valeur proposée</span>
      <div class="input big" style=${{ borderColor: q.implausible ? 'var(--red)' : '' }}>${q.value}</div>
      ${q.implausible && html`<div class="note red"><b>INVRAISEMBLABLE</b>${q.proposal.reason}. Jamais acceptée par défaut.</div>`}
      <div class="quote"><span class="label">Citation du cahier des charges · page ${q.proposal.page}</span><p>« ${q.proposal.quote} »</p>
        <button class="btn link" style="align-self:flex-start;padding:0" onClick=${() => { showPage(q.proposal.page); setQuote(q.proposal); }}>Voir la page ${q.proposal.page} →</button></div>
      ${q.rejected.length > 0 && html`<div class="note amber"><b>${q.rejected.length} autre(s) proposition(s) rejetée(s)</b>avec une autre valeur : la valeur proposée est peut-être incomplète.
        <ul class="bullets">${q.rejected.map(x => html`<li>${x.value} (p. ${x.page}, ${x.status} : ${x.reason}) « ${x.quote} »</li>`)}</ul></div>`}</div>`}
    ${q.reference && html`<div class="note amber"><b>Renvoi à ${q.reference.norm}</b>Le document renvoie à la norme sans écrire la valeur (p. ${q.reference.page}) « ${q.reference.quote} ».
      Laissé vide, le champ est hérité de la norme : exigence du client si le renvoi est confirmé, sinon recommandation plafonnée à mineur.</div>`}
    ${q.candidates.length > 0 && html`<div class="col"><span class="label">Propositions en conflit : choisissez-en une, corrigez ou laissez vide</span>
      ${q.findings.map((x, i) => q.candidates.some(c => c.n === i + 1)
        ? html`<${Finding} x=${x} on=${cand === i + 1 || q.answer === String(i + 1)} onClick=${() => { setCand(i + 1); showPage(x.page); setQuote(x); }} />`
        : html`<div class="cand" style="cursor:default;opacity:.6"><span class="v">${x.value ?? '—'}</span><span class="q">p. ${x.page} · ${x.status}${x.reason ? ' : ' + x.reason : ''} « ${x.quote} »</span></div>`)}</div>`}
    <div class="cells">
      <div><span class="k">Profil de base</span><span class="v">${q.base_value ?? '—'}</span></div>
      <div><span class="k">Norme${q.norm ? ' · ' + q.norm.title : ''} (information)</span><span class="v" style="color:var(--mute)">${q.norm ? q.norm.value : 'aucune'}</span></div></div>
    ${q.differs_from_norm && html`<div class="note amber"><b>Diffère de la norme</b>Le cahier des charges du client fait foi : c'est sa valeur qui sera appliquée.</div>`}
    ${q.decision && html`<span class="fine">Décision : ${q.decision.action}${q.decision.value ? ' · ' + q.decision.value : ''}${q.decision.source ? ' · ' + q.decision.source : ''}</span>`}
    ${fix && html`<div class="panel"><span class="label">Correction</span>
      <input class="input big" placeholder="Valeur (YAML, ex. -23 ou [&quot;25/1&quot;])" value=${fix.value} onInput=${e => setFix({ ...fix, value: e.target.value })} aria-label="Valeur corrigée" />
      <div class="btn-row"><input class="input mono" style="width:120px" placeholder="Page" value=${fix.page} onInput=${e => setFix({ ...fix, page: e.target.value })} aria-label="Page" />
        <input class="input" style="flex:1" placeholder="Citation exacte du document (vide : A VERIFIER)" value=${fix.quote} onInput=${e => setFix({ ...fix, quote: e.target.value })} aria-label="Citation" /></div>
      <div class="btn-row"><button class="btn primary" onClick=${() => send('c', fix)}>Enregistrer la correction</button><button class="btn" onClick=${() => setFix(null)}>Annuler</button></div></div>`}
    <${ErrorLine} error=${error} />
    <div class="btn-row" style="margin-top:auto">
      ${can('a') && html`<button class=${'btn ' + (q.implausible ? 'danger' : 'primary')} onClick=${() => send('a')}>${q.implausible ? 'Accepter malgré tout' : 'Accepter la proposition'}</button>`}
      ${q.candidates.length > 0 && html`<button class="btn primary" disabled=${!cand} onClick=${() => send(String(cand))}>Choisir ce candidat</button>`}
      <button class="btn" onClick=${() => setFix({ value: q.value || '', page: '', quote: '' })}>Corriger</button>
      ${can('v') && html`<button class="btn" onClick=${() => send('v')}>Laisser vide</button>`}
      ${can('g') && html`<button class="btn" onClick=${() => send('g')}>Garder la valeur de base</button>`}
      ${q.answer && html`<button class="btn" onClick=${reset}>Rétablir l'extraction</button>`}
      <button class="btn link" style="margin-left:auto" onClick=${next}>Champ suivant →</button></div>
  </div>`;
}

function References({ name, data, setData }) {
  const [error, setError] = useState('');
  const answer = async (norm, confirmed) => {
    try { setData(await api(`/api/drafts/${name}/reference`, { method: 'POST', body: { norm, confirmed } })); } catch (e) { setError(e.message); }
  };
  return html`<div class="editor"><h2 style="font-size:30px">Renvois du document à une norme</h2>
    <p class="lead">Confirmé, les valeurs de la norme deviennent des exigences du client (sans plafonnement), sauf celles que le client chiffre lui-même. Non confirmé, ce sont des recommandations plafonnées à mineur.</p>
    ${data.references.map(r => html`<div class="panel"><div class="split"><span style="font:600 22px var(--cond)">${r.title}</span>
        <span class=${'tag ' + (r.confirmed === true ? 'green' : r.confirmed === false ? 'grey' : 'amber')}>${r.confirmed === true ? 'confirmé' : r.confirmed === false ? 'non confirmé' : 'à décider'}</span></div>
      <div class="quote"><span class="label">Page ${r.page}</span><p>« ${r.quote} »</p></div>
      <span class="fine">Valeurs de la norme : ${r.values.map(([p, v]) => `${p} = ${v}`).join(' ; ')}</span>
      <div class="btn-row"><button class="btn primary" onClick=${() => answer(r.norm, true)}>Confirmer le renvoi</button>
        <button class="btn" onClick=${() => answer(r.norm, false)}>Ne pas confirmer</button></div></div>`)}
    <${ErrorLine} error=${error} /></div>`;
}

function PageImage({ name, page, quote }) {
  const [boxes, setBoxes] = useState(null);
  const text = quote && quote.page === page ? quote.quote : '';
  useEffect(() => {
    setBoxes(null);
    if (!text) return;
    api(`/api/drafts/${name}/highlight?page=${page}&quote=${encodeURIComponent(text)}`).then(r => setBoxes(r)).catch(() => setBoxes(null));
  }, [name, page, text]);
  return html`<div class="page-img"><img src=${url(`/api/drafts/${name}/page/${page}`)} alt=${'Page ' + page + ' du document'} />
      ${boxes && boxes.boxes.map(b => html`<div class="hl" style=${{ left: `calc(${b.x0 * 100}% - 3px)`, top: `calc(${b.top * 100}% - 2px)`,
        width: `calc(${(b.x1 - b.x0) * 100}% + 6px)`, height: `calc(${(b.bottom - b.top) * 100}% + 4px)` }}></div>`)}</div>
    ${text && boxes && !boxes.found && html`<span class="hint">Citation non retrouvée telle quelle sur l'image de la page (tableau ou texte découpé) : la chercher à l'œil.</span>`}`;
}

function Review({ name, back, useProfile, reload }) {
  const [data, setData] = useState(null);
  const [quote, setQuote] = useState(null);
  const [sel, setSel] = useState(0);
  const [pageN, setPageN] = useState(null);
  const [state, setState] = useState(null);
  const [who, setWho] = useState('');
  const [confirmRisks, setConfirmRisks] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState('');
  const [fills, setFills] = useState({});

  const refresh = () => api(`/api/drafts/${name}/check`).then(setState).catch(e => setError(e.message));
  useEffect(() => { api(`/api/drafts/${name}/review`).then(d => { setData(d); refresh(); }).catch(e => setError(e.message)); }, [name]);
  if (error && !data) return html`<div class="page"><${ErrorLine} error=${error} /><div><button class="btn" onClick=${back}>← Profils</button></div></div>`;
  if (!data) return html`<div class="page"><${Busy} text="Lecture du brouillon…" /></div>`;

  const qs = data.questions, refItem = data.references.length > 0 ? qs.length : -1;
  const decided = qs.filter(q => q.answer).length;
  const q = sel < qs.length ? qs[sel] : null;
  const onDecided = nq => {
    const list = qs.map(x => (x.path === nq.path ? nq : x));
    setData({ ...data, questions: list });
    refresh();
    if (nq.answer) { const nextIdx = list.findIndex((x, i) => i > sel && !x.answer); if (nextIdx >= 0) setSel(nextIdx); }
  };
  const page = pageN || (q && (q.proposal || q.reference || q.findings[0] || {}).page) || 1;
  const shownQuote = quote && q && q.findings.some(x => x.quote === quote.quote) ? quote : (q && (q.proposal || q.reference)) || null;
  const fillMissing = async (path, value) => {
    setError('');
    try { setState(await api(`/api/drafts/${name}/missing`, { method: 'POST', body: { path, value } })); } catch (e) { setError(e.message); }
  };
  const validate = async () => {
    setError('');
    try { setDone(await api(`/api/drafts/${name}/validate`, { method: 'POST', body: { who, confirm_risks: confirmRisks, overwrite } })); reload(); }
    catch (e) { setError(e.message); }
  };
  const ready = state && state.ready && who.trim() && (!state.risks.length || confirmRisks) && (!data.out_exists || overwrite);
  let reason = '';
  if (state) {
    const n = state.pending.length, r = state.pending_references.length;
    reason = n ? `Encore ${n} champ${n > 1 ? 's' : ''} à décider` : r ? `Encore ${r} renvoi${r > 1 ? 's' : ''} à une norme à décider`
      : state.missing.length ? 'Champs obligatoires à compléter' : who.trim() ? 'Tous les champs sont décidés' : 'Tous les champs sont décidés · saisissez votre nom pour signer';
  }
  let group = null;

  return html`<div class="pf">
    <div class="pf-head"><div class="head">
        <span class="kicker" style=${{ color: done ? 'var(--green)' : 'var(--amber)' }}>${done ? 'Profil validé' : 'Profil brouillon · valeurs extraites par l’IA locale, à vérifier'}</span>
        <h1 style="font-size:34px">${data.broadcaster || data.name} — ${data.name}</h1>
        <span class="sub">Source : ${data.source_document}${data.pages ? ` · ${data.pages} pages` : ''} · extraction locale${data.model ? ' (' + data.model + ')' : ''}, rien ne sort de la machine · profil de base ${data.base}</span></div>
      <div class="meter"><div class="split"><span class="sub">Champs décidés</span><span class="mono" style="font-size:12px">${decided} / ${qs.length}</span></div>
        <div class="bars">${qs.map(x => html`<span style=${{ background: x.answer ? 'var(--green)' : x.implausible ? 'oklch(0.7 0.19 27 / .5)' : 'var(--track)' }}></span>`)}</div></div>
      <button class="btn" onClick=${back}>← Profils</button></div>
    <div class="pf-body">
      <div class="fields">
        ${data.capped.pages.length > 0 && html`<div class="note red" style="margin:8px 12px;font-size:12px"><b>Page${data.capped.pages.length > 1 ? 's' : ''} ${data.capped.pages.join(', ')}</b>${data.capped.message} : relire ${data.capped.pages.length > 1 ? 'ces pages' : 'cette page'} du document à la main.</div>`}
        ${qs.map((x, i) => { const head = x.group !== group; group = x.group; return html`
          ${head && html`<div class="fgroup">${x.group}</div>`}
          <button class=${'field' + (i === sel ? ' on' : '') + (x.implausible ? ' red' : '')} onClick=${() => { setSel(i); setPageN(null); setQuote(null); }}>
            <span class="box" style=${{ borderColor: x.answer ? 'var(--green)' : x.implausible ? 'var(--red)' : '', background: x.answer ? 'var(--green)' : 'transparent' }}></span>
            <span class="t"><span>${x.path.split('.').slice(1).join('.') || x.path}</span><span>${x.answer_label || (STATUS[x.status] || [x.status])[0]} · ${x.value ?? '—'}</span></span></button>`; })}
        ${refItem >= 0 && html`<div class="fgroup">Renvois</div><button class=${'field' + (sel === refItem ? ' on' : '')} onClick=${() => setSel(refItem)}>
          <span class="box" style=${{ background: data.references.every(r => r.confirmed !== undefined && r.confirmed !== null) ? 'var(--green)' : 'transparent' }}></span>
          <span class="t"><span>Renvois aux normes</span><span>${data.references.map(r => r.title).join(', ')}</span></span></button>`}
      </div>
      ${q ? html`<${Editor} name=${name} q=${q} pos=${sel + 1} total=${qs.length} onDecided=${onDecided} showPage=${setPageN} setQuote=${setQuote}
          next=${() => setSel((sel + 1) % Math.max(1, qs.length + (refItem >= 0 ? 1 : 0)))} />`
        : html`<${References} name=${name} data=${data} setData=${d => { setData(d); refresh(); }} />`}
      <div class="preview">
        <div class="split"><span class="hint">${data.source_pdf || ''}</span><span class="mono" style="font-size:11px">p. ${page}${data.pages ? ' / ' + data.pages : ''}</span></div>
        ${data.pdf_available ? html`<${PageImage} name=${name} page=${page} quote=${shownQuote} />
          <div class="btn-row"><button class="mini" disabled=${page <= 1} onClick=${() => setPageN(page - 1)}>← page</button>
            <button class="mini" disabled=${data.pages && page >= data.pages} onClick=${() => setPageN(page + 1)}>page →</button></div>`
          : html`<div class="empty">PDF introuvable dans diffuseurs/ : aperçu indisponible.</div>`}
      </div>
    </div>
    <div class="pf-foot">
      ${done ? html`<span class="dot" style="background:var(--green)"></span><span style="margin-right:auto;font:500 14px var(--body)">Profil ${done.name} v${done.version} validé par ${done.validated_by} le ${done.validated_at.split('-').reverse().join('/')} (${done.file}). Il peut désormais produire un verdict CONFORME.</span>
          <button class="btn primary" onClick=${() => useProfile(done.name)}>Utiliser pour une analyse →</button>`
        : html`<div class="col" style="flex:1;gap:10px">
          ${state && state.missing.length > 0 && html`<div class="col"><span class="label">Champs obligatoires manquants (section acceptée en partie)</span>
            ${state.missing.map(m => html`<div class="btn-row"><span class="mono" style="font-size:12px;width:280px">${m.path}</span><span class="fine" style="flex:1">${m.description}</span>
              <input class="input mono" style="width:180px" placeholder="valeur (YAML)" value=${fills[m.path] || ''} onInput=${e => setFills({ ...fills, [m.path]: e.target.value })} aria-label=${m.path} />
              <button class="mini" disabled=${!fills[m.path]} onClick=${() => fillMissing(m.path, fills[m.path])}>Enregistrer</button>
              <button class="mini" onClick=${() => fillMissing(m.path, null)}>Retirer ${m.section}</button></div>`)}</div>`}
          ${state && state.risks.length > 0 && html`<div class="note red"><b>ATTENTION</b>Règles bloquantes ou majeures dont la valeur ne viendrait que d'une norme : elles seront plafonnées à mineur, une erreur réelle ne rendra pas le PAD NON-CONFORME.
            <ul class="bullets">${state.risks.map(x => html`<li>${x}</li>`)}</ul>
            <label class="check"><input type="checkbox" checked=${confirmRisks} onChange=${e => setConfirmRisks(e.target.checked)} />Je valide quand même, en connaissance de cause.</label></div>`}
          ${state && state.ready && state.unsourced > 0 && html`<span class="ok-line amber"><i></i>${state.unsourced} valeur(s) reprise(s) du profil de base sans citation du document (A VERIFIER dans le fichier).</span>`}
          ${data.out_exists && state && state.ready && html`<label class="check"><input type="checkbox" checked=${overwrite} onChange=${e => setOverwrite(e.target.checked)} />Remplacer ${data.out}, qui existe déjà.</label>`}
          <div class="btn-row"><span class="reason">${reason}</span><span class="label">Validé par</span>
            <input class="input" style="width:240px" placeholder="Nom et prénom" value=${who} onInput=${e => setWho(e.target.value)} aria-label="Validé par" />
            <button class="btn primary" disabled=${!ready} onClick=${validate}>Valider le profil</button></div>
          <${ErrorLine} error=${error} /></div>`}
    </div>
  </div>`;
}

export function Profiles({ profiles, drafts, pdf, job, setJob, reload, useProfile }) {
  const [reviewing, setReviewing] = useState(null);
  useEffect(() => { if (job && job.kind === 'draft' && job.state === 'done') reload(); }, [job && job.state]);
  if (reviewing) return html`<${Review} name=${reviewing} back=${() => { setReviewing(null); reload(); }} useProfile=${useProfile} reload=${reload} />`;
  return html`<${List} profiles=${profiles} drafts=${drafts} pdf=${pdf} job=${job} setJob=${setJob} openReview=${setReviewing} useProfile=${useProfile} />`;
}
