// Étape 4 · Rapport: rapport.json, written by PAD Guard from the same sections as rapport.md.
// Verdict, score, severities, thresholds, synthesis and qualifications are shown as written;
// the page only lays them out (positions on the timeline are frame / total frames).
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api, url } from '../api.js';
import { Corners, SEV_COLOR, Busy, ErrorLine, Kv } from '../ui.js';

const FILTERS = [['all', 'Tous'], ['blocking', 'Bloquant'], ['major', 'Majeur'], ['minor', 'Mineur'], ['info', 'Info']];
const COUNT_LABELS = [['blocking', 'bloquants'], ['major', 'majeurs'], ['minor', 'mineurs'], ['info', 'info']];
const ST = { 'OK': 'ok', 'ÉCHEC': 'fail' };

function hashKey() {
  const m = /(?:^#|&)a=([^&]*)/.exec(location.hash);
  return m ? decodeURIComponent(m[1]) : null;
}

function Synthesis({ s }) {
  return html`<div class="summary">${s.text.split(/\n\n+/).map(p => html`<p>${p.replace(/\\([#>*+|\-\d])/g, '$1')}</p>`)}
    <div class=${s.by_ai ? 'ai-note' : 'fine'}>${s.note.replace(/^\*|\*$/g, '')}</div>
    ${s.warnings.map(w => html`<div class="ai-note">Attention : ${w}</div>`)}</div>`;
}

function Detail({ e, runId, tc }) {
  if (!e) return html`<div class="detail bp grey"><${Corners} /><div class="empty">Aucune anomalie : rien à afficher.</div></div>`;
  return html`<div class="detail bp grey"><${Corners} />
    <div class=${'thumb' + (e.thumbnail ? '' : ' wide')}>
      ${e.thumbnail ? html`<img src=${url(`/api/runs/${encodeURIComponent(runId)}/thumb/${encodeURIComponent(e.key)}`)} alt=${'Vignette : ' + e.title} />`
        : html`<span class="ph">${e.scope === 'file' ? 'Anomalie portant sur tout le fichier : pas de vignette.' : 'Pas de vignette pour ce type d’anomalie (audio, structure ou format).'}</span>`}
      ${e.scope === 'range' && html`<span class="tcb">${e.tc_start}</span>`}
      <span class="svb" style=${{ background: SEV_COLOR[e.severity] }}>${e.severity_label}</span></div>
    <div class="body">
      <span class="title">${e.title}</span>
      <div class="kv auto" style="font-size:13px">
        <span class="k">Contrôle</span><span>${e.label}</span>
        <span class="k">Mesuré</span><span>${e.value}</span>
        <span class="k">Seuil appliqué</span><span>${e.threshold}</span>
        ${e.area && html`<span class="k">Surface</span><span>${e.area}</span>`}
        <span class="k">Plage</span><span>${e.scope === 'range' ? `${e.tc_start} → ${e.tc_end} · images ${e.frame_start} à ${e.frame_end} · ${e.duration}` : 'fichier entier'}</span>
        <span class="k">Règle</span><span style="color:var(--steel-hi)">${e.severity_source}</span>
        ${e.detail && html`<span class="k">Détail</span><span>${e.detail}</span>`}</div>
      ${(e.qualification || e.qualification_empty_reason) && html`<div class="qualif">
        ${e.qualification ? html`<span>Qualification suggérée par l'IA locale, <b>à relire</b> : <em>${e.qualification}</em></span>
          <span class="fine">${e.qualification_justification}</span>` : html`<span class="fine">Qualification IA laissée vide : ${e.qualification_empty_reason}</span>`}</div>`}
    </div></div>`;
}

export function Report({ runId, job, setJob, goRun }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [sel, setSel] = useState(hashKey());
  const [info, setInfo] = useState('');

  const load = () => { setError(''); api(`/api/runs/${encodeURIComponent(runId)}/report`).then(setData).catch(e => setError(e.message)); };
  useEffect(() => { if (runId) load(); }, [runId]);
  // A rerun of this analysis has ended: read the new report.
  useEffect(() => { if (job && job.kind === 'rerun' && job.run_id === runId && job.state === 'done') load(); }, [job && job.state]);
  useEffect(() => { if (sel) history.replaceState(null, '', `#run=${encodeURIComponent(runId)}&a=${encodeURIComponent(sel)}`); }, [sel, runId]);

  if (!runId) return html`<div class="page"><p class="lead">Aucun rapport ouvert.</p></div>`;
  if (error) return html`<div class="page"><${ErrorLine} error=${error} /></div>`;
  if (!data) return html`<div class="page"><${Busy} text="Lecture du rapport…" /></div>`;

  const run = data.run, r = data.report;
  const busy = job && job.state === 'running';
  const rerun = async step => {
    setInfo('');
    try { setJob(await api(`/api/runs/${encodeURIComponent(runId)}/rerun`, { method: 'POST', body: { from: step } })); setInfo('Relance lancée : suivi dans l’écran Analyse.'); }
    catch (e) { setInfo(e.message); }
  };
  const folder = () => api(`/api/runs/${encodeURIComponent(runId)}/open-folder`, { method: 'POST' }).then(() => setInfo('Dossier ouvert dans l’Explorateur.')).catch(e => setInfo(e.message));
  const fileUrl = (name, dl) => url(`/api/runs/${encodeURIComponent(runId)}/file/${name}${dl ? '?download=1' : ''}`);

  const actions = html`<div class="btn-row">
    <button class="btn" disabled=${busy} onClick=${() => rerun(r ? 'rules' : 'report')}>${r ? 'Relancer les règles' : 'Régénérer le rapport'}</button>
    <button class="btn" onClick=${folder}>Dossier de données</button>
    ${run.files && run.files['rapport.md'] && html`<a class="btn" href=${fileUrl('rapport.md', true)} download>Markdown</a>`}
    ${run.files && run.files['rapport.pdf'] && html`<a class="btn primary" href=${fileUrl('rapport.pdf', true)} download>Télécharger le PDF</a>`}</div>`;

  if (!r) {
    return html`<div class="report"><div class="head-row"><div class="head"><span class="kicker">Étape 4 · Rapport d'analyse</span>
      <h1 class="small">${run.file_name}</h1><span class="sub">${run.profile} · ${run.analyzed_at_text} · ${run.label}</span></div>${actions}</div>
      <div class="note amber"><b>Rapport indisponible</b>${data.missing}</div>${info && html`<span class="hint">${info}</span>`}</div>`;
  }

  const v = r.verdict, h = r.header, events = r.events;
  const visible = events.filter(e => filter === 'all' || e.severity === filter);
  const current = events.find(e => e.key === sel) || events[0];
  const frames = r.timeline.frames;
  const ranged = events.filter(e => e.scope === 'range');
  const wordLong = v.label.length > 14;
  const kicker = v.indicative ? `Résultat indicatif · ${r.profile.name} v${r.profile.version}` : `${r.profile.broadcaster} · ${r.profile.name} v${r.profile.version}`;

  return html`<div class="report">
    <div class="head-row"><div class="head" style="gap:6px"><span class="kicker">Étape 4 · Rapport d'analyse</span><h1 class="small">${h.file_name}</h1>
      <span class="sub">SHA-256 ${h.sha256.slice(0, 6)}…${h.sha256.slice(-6)} · ${r.profile.name} v${r.profile.version} · ${run.analyzed_at_text}${run.duration ? ' · analyse ' + run.duration : ''}</span></div>
      ${actions}</div>
    ${info && html`<span class="hint">${info}</span>`}
    ${h.indicative && html`<div class="note amber"><b>PROFIL NON VALIDÉ — résultat indicatif</b>${h.profile_status}. Aucun verdict CONFORME ne peut être émis avec ce profil.</div>`}

    <div class=${'verdict bp ' + data.tone}><i class="c tl"></i><i class="c br"></i>
      <div class="left"><span class="kicker">${kicker}</span><span class=${'word' + (wordLong ? ' long' : '')}>${v.label}</span><${Synthesis} s=${r.synthesis} /></div>
      <div class="right">
        <div class="counts">${COUNT_LABELS.map(([k, label]) => html`<div><b style=${{ color: v.counts[k] && (k === 'blocking' || k === 'major') ? SEV_COLOR[k] : 'var(--ink)' }}>${v.counts[k]}</b><span>${label}</span></div>`)}
          ${!v.technical && html`<div><b>${v.score_text}</b><span>score</span></div>`}</div>
        ${!v.technical && v.reasons.length > 0 && html`<ul class="bullets">${v.reasons.map(x => html`<li>${x}</li>`)}</ul>`}
        ${v.technical
          ? html`<span class="fine">Contrôle technique sans diffuseur : anomalies listées selon les règles du profil effectif (${[...r.profile.norms, `${r.profile.name} v${r.profile.version}`].join(' + ')}), sans verdict de conformité.</span>`
          : html`<span class="fine">Verdict calculé par les règles du profil effectif (${[...r.profile.norms, `${r.profile.name} v${r.profile.version}`].join(' + ')}). Score = ${v.score_formula}. Aucune IA n'intervient dans le verdict.</span>`}
      </div></div>

    <div class="panel">
      <div class="split"><span class="label">Frise · anomalies</span><span class="hint">${r.timeline.tc_start} → ${r.timeline.tc_end} · ${ranged.length} anomalie(s) situées${events.length > ranged.length ? `, ${events.length - ranged.length} sur tout le fichier` : ''} · cliquez un repère</span></div>
      <div class="timeline">${ranged.map(e => html`<button class=${e.key === (current && current.key) ? 'on' : ''} title=${`${e.tc_start} · ${e.title}`}
        style=${{ left: `${(100 * (e.frame_start + e.frame_end + 1) / 2 / frames).toFixed(3)}%`, width: `${(100 * (e.frame_end - e.frame_start + 1) / frames).toFixed(3)}%`, background: SEV_COLOR[e.severity] }}
        onClick=${() => setSel(e.key)} aria-label=${e.title}></button>`)}</div>
      <div class="ticks">${r.timeline.ticks.map(t => html`<span style=${{ left: t.pct + '%' }}>${t.label}</span>`)}</div>
    </div>

    <div class="anomalies">
      <div class="table">
        <div class="table-head"><span class="label">Anomalies</span>${FILTERS.map(([k, label]) => html`
          <button class=${'filter' + (filter === k ? ' on' : '')} onClick=${() => setFilter(k)}><i style=${{ background: k === 'all' ? 'var(--ink)' : SEV_COLOR[k] }}></i>${label} ${k === 'all' ? events.length : v.counts[k]}</button>`)}</div>
        <div class="row h"><span>Gravité</span><span>Timecode</span><span>Image</span><span>Contrôle</span><span>Mesuré / seuil</span><span>Règle</span></div>
        <div class="rows">${visible.map(e => html`<div class=${'row' + (current && e.key === current.key ? ' on' : '')} onClick=${() => setSel(e.key)}>
          <span class="sev" style=${{ color: SEV_COLOR[e.severity] }}><i style=${{ background: SEV_COLOR[e.severity] }}></i>${e.severity_label}</span>
          <span class=${e.scope === 'range' ? 'tc' : 'fr'}>${e.scope === 'range' ? e.tc_start : 'fichier'}</span>
          <span class="fr">${e.scope === 'range' ? e.frame_start.toLocaleString('fr-FR') : '—'}</span>
          <span class="lb">${e.label}${e.qualification ? html`<br /><em class="fine">${e.qualification} (IA, à relire)</em>` : ''}</span>
          <span class="ms">${e.value} <span>/ ${e.threshold}</span></span><span class="rf">${e.severity_source}</span></div>`)}
          ${visible.length === 0 && html`<div class="empty">Aucune anomalie pour ce filtre.</div>`}</div>
      </div>
      <${Detail} e=${current} runId=${runId} />
    </div>

    ${r.thumbnails_note && html`<div class="note amber"><b>Vignettes</b>${r.thumbnails_note}</div>`}

    <div class="two">
      <div class="panel"><div class="split"><span class="label">Loudness court terme</span><span class="hint">${r.audio.rules}</span></div>
        ${r.charts.loudness ? html`<div class="chart"><img src=${fileUrl('loudness.png')} alt="Loudness court terme par groupe" /></div>` : html`<div class="empty">Pas de piste audio.</div>`}</div>
      <div class="panel"><span class="label">Audio par groupe</span>
        <div class="mini-table" style="grid-template-columns:minmax(0,0.8fr) repeat(3,minmax(0,1fr))">
          <span class="h">Groupe</span><span class="h">Intégrée</span><span class="h">True peak</span><span class="h">LRA</span>
          ${r.audio.groups.map(g => html`<span class="lb">${g.name} ${g.tracks}</span><span>${g.integrated}</span><span>${g.true_peak}</span><span>${g.lra}</span>`)}</div>
        <span class="label" style="margin-top:6px">Pistes</span>
        <div class="mini-table" style="grid-template-columns:50px minmax(0,1fr) repeat(2,minmax(0,1fr))">
          <span class="h">Piste</span><span class="h">Groupe</span><span class="h">True peak</span><span class="h">RMS</span>
          ${r.audio.tracks.map(t => html`<span>${t.track}</span><span class="x">${t.group}</span><span>${t.true_peak}</span><span>${t.rms}</span>`)}</div>
        <span class="fine">${r.audio.program}</span></div>
    </div>

    <div class="panel"><span class="label">Luminance (p1 / p99 par image)</span><div class="chart"><img src=${fileUrl('luminance.png')} alt="Luminance par image" /></div></div>

    <div class="two">
      <div class="panel"><div class="split"><span class="label">Contrôles PAD · format et structure</span><span class="hint">Attendu = valeur du profil</span></div>
        <div class="mini-table" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) minmax(0,1fr) 90px">
          <span class="h">Contrôle</span><span class="h">Attendu</span><span class="h">Mesuré</span><span class="h">Statut</span>
          ${r.checks.map(c => html`<span class="lb">${c.label}</span><span class="x">${c.expected}</span><span style=${{ color: ST[c.status] === 'fail' ? 'var(--red)' : '' }}>${c.actual}</span>
            <span><span class=${'st ' + (ST[c.status] || 'unknown')} style="display:block">${c.status}</span></span>`)}</div></div>
      <div class="col" style="gap:24px">
        <div class="panel"><span class="label">Métadonnées du fichier</span>
          <${Kv} cls="auto" rows=${[['Fichier', h.path], ['Taille', h.size], ['Durée', h.duration], ['Timecode', h.timecode], ['Vidéo', h.video],
            ['SHA-256', h.sha256], ['Profil', h.profile], ['Statut du profil', h.profile_status], ['Outil', 'PAD Guard ' + h.tool_version]]} /></div>
        <div class="panel"><span class="label">Livraison</span><span class="fine" style="color:var(--ink2)">${r.delivery.conclusion}</span>
          <${Kv} cls="auto" rows=${[['Master', r.delivery.master], ['Attendu', r.delivery.expected]]} />
          ${r.delivery.warning && html`<span class="ok-line amber"><i></i>${r.delivery.warning}</span>`}</div>
      </div>
    </div>

    ${r.norm_gaps.length > 0 && html`<div class="panel"><span class="label">Écarts avec les normes (information, sans effet sur le verdict)</span>
      <ul class="bullets">${r.norm_gaps.map(x => html`<li>${x}</li>`)}</ul></div>`}
    <details class="panel"><summary class="label" style="cursor:pointer">Méthodes et limites · paramètres appliqués</summary>
      <ul class="bullets">${[...r.parameters, ...r.notes].map(x => html`<li>${x}</li>`)}</ul>
      <span class="fine">Commande : ${h.command}</span></details>
  </div>`;
}
