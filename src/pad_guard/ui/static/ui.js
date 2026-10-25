// Shared pieces of the screens. Display only: colours follow the severity written by PAD Guard.
import { html, useEffect, useState } from './vendor/preact-htm.module.js';
import { api } from './api.js';

export { html };

export const SEV_COLOR = { blocking: 'var(--red)', major: 'var(--amber)', minor: 'var(--steel)', info: 'var(--mute)' };

export function Corners() {
  return html`<i class="c tl"></i><i class="c tr"></i><i class="c bl"></i><i class="c br"></i>`;
}

// LogoMark of the mockup (design/maquette/project/LogoMark.dc.html).
export function Logo({ width = 34, variant = 'solid', ink = '#e4e7ea', paper = '#14191e', accent = 'oklch(0.72 0.17 150)' }) {
  const small = width < 40, stroke = variant === 'bare' ? 0 : (small ? 6 : 2), sq = small ? 11 : 9;
  const h = +(width * 82 / 110).toFixed(2);
  return html`<svg width=${width} height=${h} viewBox="0 0 110 82" style="display:block;overflow:visible" aria-hidden="true">
    <rect x=${stroke / 2} y=${stroke / 2} width=${110 - stroke} height=${82 - stroke} fill=${variant === 'solid' ? ink : 'none'}
      stroke=${variant === 'outline' ? ink : 'none'} stroke-width=${stroke}></rect>
    <text x="15" y="63.5" textLength="62" lengthAdjust="spacingAndGlyphs" font-family="Barlow Condensed, sans-serif" font-weight="700"
      font-size="64" fill=${variant === 'solid' ? paper : ink}>PG</text>
    <rect x="83" y=${small ? 24 : 26} width=${sq} height=${sq} fill=${accent}></rect>
    <rect x="83" y=${small ? 46 : 47} width=${sq} height=${sq} fill=${accent}></rect>
  </svg>`;
}

export function Dialog({ title, children, onClose }) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape' && onClose) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return html`<div class="backdrop" onClick=${e => { if (e.target === e.currentTarget && onClose) onClose(); }}>
    <div class="dialog bp" role="dialog" aria-modal="true" aria-label=${title}><${Corners} />
      <div class="title">${title}</div>${children}</div></div>`;
}

export function Busy({ text }) {
  return html`<div class="busy"><span>${text}</span><i></i></div>`;
}

export function Kv({ rows, cls = '' }) {
  return html`<div class=${'kv ' + cls}>${rows.map(([k, v, r]) => html`
    <span class="k">${k}</span><span>${v ?? '—'}</span>${cls.includes('ref') ? html`<span class="r">${r || ''}</span>` : ''}`)}</div>`;
}

export function ErrorLine({ error }) {
  return error ? html`<div class="error" role="alert">${error}</div>` : null;
}

// Model of the local AI used by the next launch, among those Ollama has (ollama list); the server
// says which one is preselected (PAD Guard's default model).
export function ModelPicker({ value, onChange }) {
  const [models, setModels] = useState(null);
  useEffect(() => {
    api('/api/llm/models').then(m => { setModels(m); if (!value && m.selected) onChange(m.selected); })
      .catch(e => setModels({ installed: [], error: e.message }));
  }, []);
  if (!models) return html`<${Busy} text="Modèles installés dans Ollama…" />`;
  return html`<div class="btn-row" style="align-items:center">
    <span class="label">Modèle utilisé</span>
    ${models.installed.length > 0
      ? html`<select class="input mono" value=${value || ''} onChange=${e => onChange(e.target.value)} aria-label="Modèle de l'IA locale">
          ${models.installed.map(m => html`<option value=${m}>${m}${m === models.default ? ' (défaut)' : ''}</option>`)}</select>`
      : html`<span class="mono">aucun modèle installé</span>`}
    ${models.error && html`<span class="hint" style="color:var(--amber)">${models.error}</span>`}</div>`;
}
