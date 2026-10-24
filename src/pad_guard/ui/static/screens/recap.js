// Étape 2 · Récapitulatif: what will be analysed, with which profile, and the exact command.
// Requirements, groups and checks come from the server (effective profile, probe); the audio map
// is built and checked by PAD Guard (audio_map), never here.
import { html, useState, useEffect } from '../vendor/preact-htm.module.js';
import { api } from '../api.js';
import { Corners, Kv, Busy, ErrorLine } from '../ui.js';

const STATUS_CLS = { ok: 'ok', fail: 'fail', unknown: 'unknown' };
const STATUS_TXT = { ok: 'OK', fail: 'ÉCHEC', unknown: '?' };

export function Recap({ form, setForm, job, back, started, toProfiles }) {
  const [prof, setProf] = useState(null);
  const [map, setMap] = useState(null);
  const [cmd, setCmd] = useState(null);
  const [error, setError] = useState('');
  const [mapError, setMapError] = useState('');
  const [launching, setLaunching] = useState(false);
  const pv = form.preview;
  const tracks = pv && pv.tracks ? pv.tracks : [];

  useEffect(() => { api(`/api/profiles/${encodeURIComponent(form.profile)}/summary`).then(setProf).catch(e => setError(e.message)); }, [form.profile]);

  // Audio map, then the command of the CLI, from the server.
  useEffect(() => {
    if (!form.assign || !tracks.length) { setMap(null); return; }
    setMapError('');
    api('/api/audio-map', { method: 'POST', body: { profile: form.profile, assign: form.assign, tracks: tracks.length } })
      .then(setMap).catch(e => { setMap(null); setMapError(e.message); });
  }, [JSON.stringify(form.assign), form.profile]);

  const launchBody = { master: form.master.path, profile: form.profile, audio_map: map ? map.spec : null, llm: !!form.llm };
  useEffect(() => {
    if (tracks.length && !map) { setCmd(null); return; }
    api('/api/jobs/analyze/preview', { method: 'POST', body: launchBody }).then(setCmd).catch(e => setCmd({ error: e.message }));
  }, [map && map.spec, map && map.shown, form.llm, form.profile, form.master.path]);

  const busy = job && job.state === 'running';
  const canLaunch = !!(cmd && cmd.command && !cmd.problems.length && pv && pv.accepted && (!tracks.length || map) && !busy && !launching);
  const launch = async () => {
    setError(''); setLaunching(true);
    try { started(await api('/api/jobs/analyze', { method: 'POST', body: launchBody })); }
    catch (e) { setError(e.message); }
    finally { setLaunching(false); }
  };
  const assign = (track, group) => setForm(f => ({ ...f, assign: { ...f.assign, [track]: group } }));
  const failing = pv && pv.checks ? pv.checks.filter(c => c.status !== 'ok') : [];
  const draft = prof && prof.status !== 'validated';

  return html`<div class="page">
    <div class="head-row"><div class="head"><span class="kicker">Étape 2 · Récapitulatif</span><h1>Vérifiez avant de lancer l'analyse</h1></div>
      <button class="btn" onClick=${back}>← Modifier les fichiers</button></div>
    <${ErrorLine} error=${error} />
    <div class="grid2" style="gap:28px">
      <div class="frame bp grey"><${Corners} />
        <div class="frame-title"><span>Film master</span><span class="tag steel">Format lu dans le fichier</span></div>
        ${pv && pv.rows ? html`<${Kv} rows=${pv.rows} />` : html`<${Busy} text="Lecture du format…" />`}
        ${failing.length > 0 && html`<span class="label" style="margin-top:8px">Contrôles du format à signaler (aperçu)</span>
          <div class="mini-table" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) minmax(0,1fr) 80px">
            <span class="h">Contrôle</span><span class="h">Attendu</span><span class="h">Trouvé</span><span class="h">Statut</span>
            ${failing.map(c => html`<span class="lb">${c.label}</span><span class="x">${c.expected}</span><span>${c.actual}</span>
              <span><span class=${'st ' + STATUS_CLS[c.status]} style="display:block">${STATUS_TXT[c.status]}</span></span>`)}</div>
          <span class="hint">La gravité de ces écarts est décidée par les règles du profil, à la fin de l'analyse.</span>`}
      </div>
      <div class="frame bp grey"><${Corners} />
        <div class="frame-title"><span>Diffuseur</span>${prof && html`<span class=${'tag ' + (draft ? 'amber' : 'green')}>Profil ${draft ? 'brouillon' : 'validé'}</span>`}</div>
        ${prof ? html`<${Kv} rows=${[['Chaîne', prof.broadcaster], ['Document', prof.source_document],
            ['Profil appliqué', `${prof.name} v${prof.version}`], ['Fichier profil', prof.file],
            ['Statut', draft ? 'brouillon (draft)' : `validé par ${prof.validated_by} le ${(prof.validated_at || '').split('-').reverse().join('/')}`],
            ['Normes héritées', prof.norms.join(', ') || 'aucune']]} />
          <span class="label" style="margin-top:8px">Exigences principales du profil</span>
          <${Kv} cls="ref" rows=${prof.requirements.map(r => [r.label, r.value, r.ref])} />
          ${draft && html`<div class="note amber" style="display:flex;align-items:center;gap:12px"><span style="flex:1"><b>Profil brouillon</b>Résultat indicatif, jamais « CONFORME ».</span>
            <button class="btn link" onClick=${toProfiles}>Valider le profil →</button></div>`}`
          : html`<${Busy} text="Lecture du profil…" />`}
      </div>
    </div>
    ${tracks.length > 0 && prof && html`<div class="panel">
      <div class="split"><span class="label">Correspondance audio</span><span class="hint">Groupe de chaque piste (groupes du profil ${prof.name})</span></div>
      <div class="tracks">${tracks.map(t => html`<div class="track"><span>PISTE ${t}</span>
        <div class="seg">${[...prof.groups.map(g => g.name), '—'].map(g => html`
          <button class=${(form.assign && (form.assign[t] || '—') === g) ? 'on' : ''} onClick=${() => assign(t, g === '—' ? null : g)}>${g}</button>`)}</div></div>`)}</div>
      ${map && html`<span class="ok-line"><i></i>${map.describe}${map.spec ? ' (remplace la correspondance du profil pour cette analyse)' : ' (correspondance du profil)'}</span>`}
      ${map && map.missing_required.length > 0 && html`<span class="ok-line amber"><i></i>Groupe(s) requis par le profil sans piste : ${map.missing_required.join(', ')}</span>`}
      <${ErrorLine} error=${mapError} />
    </div>`}
    <label class="check"><input type="checkbox" checked=${!!form.llm} onChange=${e => setForm(f => ({ ...f, llm: e.target.checked }))} />
      <span>Synthèse et qualifications suggérées par l'IA locale (Ollama, rien ne sort de la machine). À relire : le verdict, le score et les gravités n'en dépendent pas.</span></label>
    <div class="launch">
      <div class="cmd">${cmd && cmd.command ? html`<span class="p">$ </span>${cmd.command}` : cmd && cmd.error ? html`<span class="error">${cmd.error}</span>` : '…'}
        ${cmd && cmd.workdir && html`<div class="hint" style="margin-top:6px">Dossier de l'analyse : ${cmd.workdir}</div>`}
        ${cmd && cmd.problems && cmd.problems.length > 0 && html`<div class="error" style="margin-top:6px">Profil incomplet pour cette analyse :\n- ${cmd.problems.join('\n- ')}</div>`}</div>
      <button class="btn primary huge" disabled=${!canLaunch} onClick=${launch}>${launching ? 'Lancement…' : "Lancer l'analyse"}</button>
    </div>
    ${busy && html`<div class="note amber"><b>Une analyse tourne déjà</b>${job.title}</div>`}
  </div>`;
}
