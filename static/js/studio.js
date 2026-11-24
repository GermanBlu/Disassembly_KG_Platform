/* ── Pipeline Studio ──────────────────────────────────────────────────────────
 *
 * The STEP→knowledge-graph build flow (#/new). Loaded after graph.js;
 * references app.html globals ($, esc, toast, API, DEMO, pageHeader, go,
 * _libSlug) and graph.js (renderGraph, cyStyle) inside function bodies only.
 *
 * Architecture: a "stage rail" studio — left rail with live per-stage status,
 * center stage canvas (all stage <section>s stay mounted, hidden-toggled),
 * right context panel (parts, pipeline numbers, explosion gauge). The server
 * is stateless between calls: the client holds the Phase-1 result and passes its
 * liaison and interference matrices back to generate-tables unchanged.
 *
 * Phase 1 runs with the standard settings (pipeline.settings.STANDARD_SETTINGS):
 * contacts below 0.5 mm, test directions from the contact surfaces, both visual
 * tests for every pair, automatic two-step releases. "Developer settings" on the
 * Extract stage lets a developer change single values to experiment; the changed
 * values go to /api/step/run and the result records the settings it used. The
 * studio shows the Phase-1 results as delivered; it does not re-threshold them.
 */

/* Mirrors pipeline/part_ids.py — 62 symbols. Never use fromCharCode(65+i). */
const ST_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
const _stL = (i) => ST_ALPHABET[i] || `?${i}`;

const _ST_STORE = 'studio_state';       // storage key; sessions stored under another key are not restored
const _ST_STAGES = [
  { key: 'extract',  label: 'Extract' },
  { key: 'contacts', label: 'Contacts' },
  { key: 'groups',   label: 'Fasteners & Groups' },
  { key: 'rules',    label: 'Rules' },
  { key: 'generate', label: 'Generate & Build' },
];

let ST = null;          // studio state (persisted)
let _stFiles = [];      // File objects — in-memory only, lost on reload
let _stAbort = null;    // AbortController of the in-flight Phase-1 run
let _stTimers = [];     // progress-checklist timers
let _stCy = null;       // preview cytoscape instance

function _stDefault() {
  return {
    step: 0, revision: 0, phase2Rev: -1,
    fileName: null, labels: [],
    phase1: null,
    fasteners: [],            // 0-based part indices
    groups: [],               // [{name, members:[int], why, accepted}]
    dismissed: [],            // dismissed suggestion names
    rules: [],                // [{part, blockers:[letters]}] -> precedence_rules
    sepRules: [],             // [{part1, part2, requires_removed:[letters]}]
    estimates: null,          // {with, without} aog_estimate for the gauge
    phase2: null,
    product: { id: '', name: '' },
    imported: false,
    settings: {},             // {group: {leaf: value}} changed from the standard
  };
}

function _stReset() { ST = _stDefault(); _stFiles = []; sessionStorage.removeItem(_ST_STORE); }

function _stPersist() {
  try {
    sessionStorage.setItem(_ST_STORE, JSON.stringify(ST));
  } catch (e) {
    // Quota: drop the log and retry once
    try {
      const slim = JSON.parse(JSON.stringify(ST));
      if (slim.phase1) delete slim.phase1.log;
      sessionStorage.setItem(_ST_STORE, JSON.stringify(slim));
    } catch (e2) { /* give up silently — session cache is best-effort */ }
  }
}

function _stRestore() {
  try {
    const raw = sessionStorage.getItem(_ST_STORE);
    if (!raw) return false;
    const s = JSON.parse(raw);
    if (!s || (!s.phase1 && !s.imported)) return false;
    ST = Object.assign(_stDefault(), s);
    return true;
  } catch (e) { return false; }
}

/* Any input change bumps revision; stage 5 results are stale when they don't match. */
function _stTouch() { ST.revision++; _stPersist(); _stUpdateRail(); _stStaleUI(); _stEstimate(); }
function _stIsStale() { return ST.phase2 && ST.phase2Rev !== ST.revision; }

/* "Tube (A)" -> "Tube"; keeps arbitrary labels safe. */
function _stPartName(i) {
  const lbl = ST.labels[i] || _stL(i);
  return lbl.replace(/\s*\(([A-Za-z0-9])\)\s*$/, '');
}
function _stPartFull(i) { return `${_stPartName(i)} (${_stL(i)})`; }

/* Part ID as used in connections and transitions ("B") -> display name ("End plate"). */
function _stNameById(id) {
  if (ST.imported && ST.importNames?.[id]) return ST.importNames[id];
  const i = ST_ALPHABET.indexOf(id);
  return i >= 0 && i < ST.labels.length ? _stPartName(i) : id;
}

/* ID badge + name, e.g. [B] End plate — fasteners in orange. */
function _stPartTag(id, fastener) {
  return `<span class="inline-flex items-center gap-1 min-w-0">
    <span class="w-4 h-4 flex-none rounded text-[9px] font-bold inline-flex items-center justify-center ${fastener ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-600'}">${esc(id)}</span>
    <span class="truncate">${esc(_stNameById(id))}</span></span>`;
}

/* ── Phase-1 results (final as delivered by the backend) ───────────────────── */

function _stLiaison() { return ST.phase1?.liaison_matrix || []; }
function _stInterference() { return ST.phase1?.interference_matrices || []; }
function _stThr() { return ST.phase1?.contact_threshold ?? 0.5; }
function _stDirs() { return ST.phase1?.interference_directions || []; }
function _stReleases() { return ST.phase1?.two_step_releases || []; }
function _stOverlaps() { return ST.phase1?.volume_overlaps || []; }

/* ── Developer settings (Phase 1) ─────────────────────────────────────────────
 * A developer feature for trying other settings. The standard values come from
 * the server (/api/pipeline/algorithms); a changed value is sent with the next
 * extraction (the server accepts only pipeline.settings.CLIENT_SETTINGS), and
 * the result echoes the settings used. */

let _stStd = null;   // standard values {group: {leaf: value}}
const _ST_SETTINGS = [
  // [group, leaf, label, kind, options or unit]
  ['contact', 'method', 'Contact rule', 'select',
    [['fixed', 'Fixed distance'], ['auto', 'From the gap distribution']]],
  ['contact', 'fixed_value', 'Contact distance', 'number', 'mm'],
  ['interference', 'directions', 'Test directions', 'select',
    [['contact', 'From the contact surfaces'], ['cardinal', 'Six axis directions (±X, ±Y, ±Z)']]],
  ['interference', 'reverse_check', 'Reverse visual test', 'select',
    [['all', 'For every pair'], ['noncontact', 'Only for pairs without contact'], ['off', 'Off']]],
  ['interference', 'count_region', 'Pixel counting region', 'select',
    [['overlap', 'Bounding-box overlap'], ['image', 'Whole image']]],
  ['interference', 'edge_px', 'Silhouette edge excluded', 'number', 'px'],
  ['interference', 'pixel_tol', 'Pixel tolerance, touching pairs', 'percent', '%'],
  ['interference', 'pixel_tol_noncontact', 'Pixel tolerance, other pairs', 'percent', '%'],
  ['interference', 'two_step', 'Two-step removals', 'select', [['auto', 'Detect automatically'], ['off', 'Off']]],
  ['distance', 'method', 'Distance computation', 'select', [['exact', 'Exact (B-rep)'], ['mesh', 'Mesh approximation']]],
];

async function _stLoadStandard() {
  if (_stStd) return;
  try {
    const r = await (await fetch(API.algorithms())).json();
    _stStd = r.standard || null;
  } catch (e) { /* the panel keeps its loading note */ }
  _stRenderSettings();
}

function _stSettingValue(g, l, settings) {
  const v = (settings || ST.settings)?.[g]?.[l];
  return v != null ? v : _stStd?.[g]?.[l];
}

function _stFmtSetting(kind, opts, v) {
  if (v == null) return '–';
  if (kind === 'select') return (opts.find(o => o[0] === v) || [v, String(v)])[1];
  if (kind === 'percent') return `${Math.round(v * 1000) / 10} %`;
  return `${v} ${opts}`;
}

/* What a changed value does to the analysis (shown next to every changed value). */
const _ST_SETTING_NOTES = {
  'contact.method': () => 'The contact distance is derived from the gap distribution of this assembly, so other part pairs can count as touching. Contacts, test directions and connections can change.',
  'contact.fixed_value': () => 'A smaller distance can miss contacts that the CAD model leaves with a small gap; a larger one adds pairs that only lie close together. Contacts, test directions and connections can change.',
  'interference.directions': () => 'Only the six axis directions are tested, not the directions of the contact surfaces. A part that can only leave at an angle to the axes stays blocked, so removal directions are missing.',
  'interference.reverse_check': () => 'Without the reverse visual test, a blockage that is only visible from the other side is missed, so the graph can contain removals that the standard settings rule out.',
  'interference.count_region': () => 'Covered pixels are counted against the whole image instead of the overlap of the bounding boxes, so a small covered area weighs less against the tolerance.',
  'interference.edge_px': v => v < 1
    ? 'Without the edge exclusion, flush contact faces count as covering each other.'
    : 'A wider edge exclusion ignores more of each silhouette, so small blockages can be missed.',
  'interference.pixel_tol': v => v < 0.01
    ? 'Touching pairs block at a smaller covered share, so a few covered pixels along flush faces can block a removal.'
    : 'Touching pairs need a larger covered share to block, so small blockages can be missed.',
  'interference.pixel_tol_noncontact': () => 'Pairs without contact may cover a share of the pixels without blocking, so a small part in front of a large one can be missed.',
  'interference.two_step': () => 'Parts that can only leave in two straight moves stay blocked.',
  'distance.method': () => 'Distances are measured on a triangulated approximation of the surfaces, so pairs near the contact distance can change.',
};

function _stSettingNote(g, l, v) {
  return _ST_SETTING_NOTES[`${g}.${l}`]?.(v) || '';
}

/* Settings that differ from the standard, as [label, value text, note]. */
function _stSettingsDiff(settings) {
  if (!_stStd || !settings) return [];
  return _ST_SETTINGS.filter(([g, l]) => settings[g]?.[l] != null && settings[g][l] !== _stStd[g]?.[l])
    .map(([g, l, label, kind, opts]) => [label, _stFmtSetting(kind, opts, settings[g][l]), _stSettingNote(g, l, settings[g][l])]);
}

function _stSetSetting(g, l, raw, kind) {
  let v = raw;
  if (kind === 'number' || kind === 'percent') {
    v = parseFloat(String(raw).replace(',', '.'));
    if (!Number.isFinite(v) || v < 0) { toast('Please enter a non-negative number.'); _stRenderSettings(); return; }
    if (kind === 'percent') v = v / 100;
    if (l === 'edge_px') v = Math.round(v);
  }
  ST.settings = ST.settings || {};
  ST.settings[g] = ST.settings[g] || {};
  if (_stStd && v === _stStd[g]?.[l]) delete ST.settings[g][l]; else ST.settings[g][l] = v;
  if (!Object.keys(ST.settings[g]).length) delete ST.settings[g];
  _stPersist();
  _stRenderSettings();
}

function _stResetSettings() { ST.settings = {}; _stPersist(); _stRenderSettings(); }

/* True when the current settings differ from those of the last extraction. */
function _stSettingsChanged() {
  if (!ST.phase1) return false;
  const used = ST.phase1.pipeline_settings_resolved || {};
  return _ST_SETTINGS.some(([g, l]) => _stSettingValue(g, l) !== (used[g]?.[l] ?? _stStd?.[g]?.[l]));
}

function _stSettingsPanel() {
  return `<details id="st-settings" class="mt-4 kg-card px-4 py-3"${Object.keys(ST.settings || {}).length ? ' open' : ''}>
    <summary class="cursor-pointer select-none text-sm font-semibold text-slate-700">Developer settings
      <span id="st-settings-badge" class="ml-2 text-[11px] font-normal"></span></summary>
    <div id="st-settings-body" class="mt-3 text-xs text-slate-400">Loading the standard values…</div>
  </details>`;
}

function _stRenderSettings() {
  const body = $('st-settings-body'), badge = $('st-settings-badge');
  if (!body) return;
  if (!_stStd) { _stLoadStandard(); return; }
  const changed = Object.keys(ST.settings || {}).length > 0;
  if (badge) badge.innerHTML = changed
    ? '<span class="px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">changed</span>'
    : '<span class="text-slate-400">standard</span>';
  const row = ([g, l, label, kind, opts]) => {
    const v = _stSettingValue(g, l), std = _stStd[g]?.[l], isStd = v === std;
    const disabled = g === 'contact' && l === 'fixed_value' && _stSettingValue('contact', 'method') === 'auto';
    const input = kind === 'select'
      ? `<select class="border border-slate-200 rounded-lg px-1.5 py-1 text-xs text-slate-700 max-w-full" onchange="_stSetSetting('${g}','${l}',this.value,'select')">${opts.map(([k, t]) =>
          `<option value="${k}"${k === v ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`
      : `<span class="inline-flex items-center gap-1"><input class="border border-slate-200 rounded-lg px-1.5 py-1 text-xs text-slate-700 w-20 disabled:opacity-40" inputmode="decimal" ${disabled ? 'disabled' : ''}
          value="${kind === 'percent' ? Math.round(v * 1000) / 10 : v}" onchange="_stSetSetting('${g}','${l}',this.value,'${kind}')"><span class="text-slate-400">${esc(opts)}</span></span>`;
    return `<div class="grid grid-cols-[10.5rem_minmax(0,1fr)_8.5rem] items-center gap-x-3 gap-y-1 py-1">
      <div class="text-slate-600">${esc(label)}</div>
      <div class="min-w-0">${input}</div>
      <div class="text-[11px] leading-snug ${isStd ? 'text-slate-400' : 'text-amber-700'}">${isStd ? 'standard' : `standard: ${esc(_stFmtSetting(kind, opts, std))}`}</div>
      ${isStd ? '' : `<div class="col-start-2 col-span-2 text-[11px] leading-snug text-amber-800">⚠ ${esc(_stSettingNote(g, l, v))}</div>`}
    </div>`;
  };
  body.innerHTML = `
    <p class="text-slate-500 mb-2">For development: the standard values are used unless you change them. Changed values apply to the next extraction, and the result records the settings it used.</p>
    ${changed ? `<p class="mb-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-amber-800">Results with changed settings can differ from those with the standard settings.</p>` : ''}
    ${_ST_SETTINGS.map(row).join('')}
    <div class="mt-2 flex items-center gap-3">
      <button onclick="_stResetSettings()" class="btn btn-ghost text-xs"${changed ? '' : ' disabled'}>Reset to standard</button>
      ${_stSettingsChanged() ? `<span class="text-amber-700">The extraction below used other settings.</span>
        <button onclick="_stReExtract()" class="btn btn-ghost text-xs">Re-extract with these settings</button>` : ''}
    </div>`;
}

/* Box for the Contacts stage: which changed settings produced these results. */
function _stSettingsUsedLine() {
  const diff = _stSettingsDiff(ST.phase1?.pipeline_settings_resolved);
  const server = [...(ST.phase1?.pipeline_settings_warnings || []),
    ...(ST.phase1?.pipeline_settings_ignored || []).map(k => `${k}: not adjustable, ignored`)];
  if (!diff.length && !server.length) return '';
  return `<div class="mb-4 text-xs bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-amber-800">
    <div class="font-semibold mb-1">Changed developer settings</div>
    <div class="mb-2">These results can differ from those with the standard settings.</div>
    <ul class="list-disc pl-4 space-y-1">${diff.map(([k, v, note]) => `<li><strong>${esc(k)}: ${esc(v)}.</strong> ${esc(note)}</li>`).join('')}
      ${server.map(w => `<li>${esc(w)}</li>`).join('')}</ul>
  </div>`;
}

/* (0, -0.574, 0.819) — direction vectors as short, sign-clean text */
function _stFmtDir(v) {
  return '(' + v.map(c => { const r = Math.round(c * 1000) / 1000; return Object.is(r, -0) ? '0' : String(r); }).join(', ') + ')';
}

function _stContactCount(lm) {
  lm = lm || _stLiaison();
  let c = 0;
  for (let i = 0; i < lm.length; i++)
    for (let j = i + 1; j < lm.length; j++) c += lm[i][j];
  return c;
}

function _stConnected(lm) {
  lm = lm || _stLiaison();
  const n = lm.length;
  if (n === 0) return true;
  const seen = new Set([0]); const queue = [0];
  while (queue.length) {
    const u = queue.pop();
    for (let v = 0; v < n; v++) if (lm[u][v] && !seen.has(v)) { seen.add(v); queue.push(v); }
  }
  return seen.size === n;
}

/* ── Shell ──────────────────────────────────────────────────────────────────── */

function renderStudio() {
  if (DEMO) { _stLockedShell('demo'); return; }
  if (!ST) { if (!_stRestore()) _stReset(); }

  $('main').innerHTML = `${pageHeader({
      title: 'Pipeline Studio',
      subtitle: ST.fileName || 'STEP assembly → knowledge graph',
      back: '#/products',
      actions: `<button onclick="_stStartOver()" id="st-startover" class="btn btn-ghost text-xs ${(ST.phase1 || ST.imported) ? '' : 'hidden'}"><i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i> Start over</button>`,
    })}
    <div class="h-[calc(100%-81px)] flex min-h-0">
      <nav class="w-56 flex-none border-r border-slate-200 bg-white/60 py-4 px-3 space-y-1 overflow-y-auto" id="st-rail"></nav>
      <div class="flex-1 min-w-0 overflow-y-auto p-6" id="st-canvas">
        ${_ST_STAGES.map((s, i) => `<section id="st-sec-${s.key}" class="hidden max-w-4xl mx-auto"></section>`).join('')}
      </div>
      <aside class="w-64 flex-none border-l border-slate-200 bg-white/60 p-4 overflow-y-auto" id="st-panel"></aside>
    </div>`;
  lucide.createIcons();

  const restored = !!ST.phase1 || ST.imported;
  _stRenderAllStages();
  _stUpdateRail();
  _stRenderPanel();
  _stGoStep(restored ? Math.max(ST.step, ST.imported ? 4 : 1) : 0);
  if (restored) toast(`Restored session: ${ST.fileName} (${ST.labels.length} parts) — "Start over" (top right) begins a new product`);
}

function _stRenderAllStages() {
  _stRenderExtract();
  _stRenderContacts();
  _stRenderGroups();
  _stRenderRules();
  _stRenderGenerate();
  lucide.createIcons();
}

function _stGoStep(i) {
  ST.step = i;
  _ST_STAGES.forEach((s, k) => $(`st-sec-${s.key}`)?.classList.toggle('hidden', k !== i));
  _stUpdateRail();
  _stPersist();
  if (i === 1) _stAfterContactsVisible();   // canvas needs layout before draw
}

function _stRailStatus(i) {
  const p1 = ST.phase1;
  if (ST.imported) {
    if (i === 0) return `${ST.labels.length} parts (imported)`;
    if (i === 4) return `${(ST.phase2?.transitions || []).length} transitions`;
    return 'skipped — imported data';
  }
  switch (i) {
    case 0: return p1 ? `${ST.labels.length} parts · ${(p1.timing?.total ?? 0).toFixed(1)}s` : (ST.fileName ? 'running…' : 'no file yet');
    case 1: return p1 ? `${_stContactCount()} contacts · ${_stDirs().length} directions` : '—';
    case 2: {
      if (!p1) return '—';
      const g = ST.groups.filter(x => x.accepted).length;
      return `${ST.fasteners.length} fasteners · ${g} group${g === 1 ? '' : 's'}`;
    }
    case 3: return p1 ? `${ST.rules.length + ST.sepRules.length} custom rules` : '—';
    case 4: {
      if (!ST.phase2) return p1 ? 'not generated' : '—';
      return _stIsStale() ? 'stale — regenerate' : `${(ST.phase2.transitions || []).length} transitions`;
    }
  }
  return '';
}

function _stUpdateRail() {
  const rail = $('st-rail'); if (!rail) return;
  const locked = !ST.phase1;
  rail.innerHTML = _ST_STAGES.map((s, i) => {
    const dis = ST.imported ? (i >= 1 && i <= 3) : (locked && i > 0);
    const active = ST.step === i;
    const stale = i === 4 && _stIsStale();
    return `<div class="nav-item ${active ? 'active' : ''} ${dis ? 'opacity-40 pointer-events-none' : ''}"
                 onclick="_stGoStep(${i})" style="display:block">
      <div class="flex items-center gap-2">
        <span class="w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center
              ${active ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-600'}">${i + 1}</span>
        <span class="text-[13px] font-semibold">${s.label}</span>
      </div>
      <div class="text-[10px] ${stale ? 'text-amber-500 font-semibold' : active ? 'text-white/70' : 'text-slate-400'} ml-7 mt-0.5">${esc(_stRailStatus(i))}</div>
    </div>`;
  }).join('');
  $('st-startover')?.classList.toggle('hidden', !(ST.phase1 || ST.imported));
}

/* The page header only renders in renderStudio — keep its file-name subtitle
 * in sync when a run/import happens without a full re-render. */
function _stSubtitle() {
  const p = $('main')?.querySelector('h1 + p');
  if (p) p.textContent = ST.fileName || 'STEP assembly → knowledge graph';
}

function _stStartOver() {
  if ((ST.phase1 || ST.imported) && !confirmTwice('studio:start-over',
      'Click "Start over" again to discard this session (nothing has been written to the database).')) return;
  _stReset();
  renderStudio();
}

function _stStaleUI() {
  const el = $('st-stale');
  if (el) el.classList.toggle('hidden', !_stIsStale());
  const build = $('st-build-btn');
  if (build) build.disabled = _stIsStale() || !ST.phase2 || !(ST.phase2.transitions || []).length;
  _stUpdateRail();
}

/* Right context panel: parts legend, pipeline numbers and the size gauge. */
function _stRenderPanel() {
  const el = $('st-panel'); if (!el) return;
  if (ST.imported) {
    el.innerHTML = `
      <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Imported data</div>
      <div class="text-[11px] text-slate-600 space-y-0.5">
        <div>${ST.labels.length} components</div>
        <div>${(ST.phase2?.connections || []).length} connections</div>
        <div>${(ST.phase2?.transitions || []).length} transitions</div>
      </div>`;
    return;
  }
  if (!ST.phase1) {
    el.innerHTML = `<div class="text-xs text-slate-400 leading-relaxed">Upload a STEP assembly to see parts, contacts and the explosion-risk gauge here.</div>`;
    return;
  }
  const parts = ST.labels.map((l, i) => {
    const isF = ST.fasteners.includes(i);
    return `<div class="flex items-center gap-1.5 text-[11px] py-0.5" title="${esc(l)}">
      <span class="w-4 h-4 rounded text-[9px] font-bold flex items-center justify-center ${isF ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-600'}">${_stL(i)}</span>
      <span class="truncate ${isF ? 'text-orange-800' : 'text-slate-700'}">${esc(_stPartName(i))}</span>
    </div>`;
  }).join('');
  const lm = _stLiaison();
  el.innerHTML = `
    <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Parts (${ST.labels.length})</div>
    <div class="mb-3 max-h-56 overflow-y-auto">${parts}</div>
    <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Pipeline</div>
    <div class="text-[11px] text-slate-600 space-y-0.5 mb-3">
      <div>${ST.labels.length} parts</div>
      <div>${_stContactCount(lm)} contacts (gap &lt; ${_stThr()} mm)</div>
      <div>${_stDirs().length} test directions</div>
      <div>${_stReleases().length} two-step removal${_stReleases().length === 1 ? '' : 's'}</div>
      ${_stOverlaps().length ? `<div class="text-red-600 font-semibold">${_stOverlaps().length} overlapping pair${_stOverlaps().length === 1 ? '' : 's'} — fix the CAD model</div>` : ''}
      <div>${ST.fasteners.length} fasteners · ${ST.groups.filter(g => g.accepted).length} groups</div>
      <div>${ST.rules.length + ST.sepRules.length} custom rules</div>
    </div>
    <div id="st-gauge"></div>`;
  _stRenderGauge();
}

/* ── Locked shells (demo / OCC unavailable) ────────────────────────────────── */

function _stLockedShell(kind, occError) {
  const copy = kind === 'demo'
    ? { icon: 'lock', title: 'Creating products is disabled in this read-only demo.',
        body: 'The Pipeline Studio takes a STEP assembly through contact detection, separability checks along the contact directions, fastener semantics and AND/OR-graph enumeration to a queryable knowledge graph — upload, review contacts and two-step removals, group identical fasteners, add precedence rules, preview the state graph, build.' }
    : { icon: 'server-off', title: 'The geometry pipeline is unavailable on this server.',
        body: `${occError || 'OpenCASCADE is not installed.'} You can still build a product from prepared JSON (components, connections & transitions).` };
  $('main').innerHTML = `${pageHeader({ title: 'Pipeline Studio', subtitle: 'STEP assembly → knowledge graph', back: '#/products' })}
    <div class="h-[calc(100%-81px)] flex min-h-0">
      <nav class="w-56 flex-none border-r border-slate-200 bg-white/60 py-4 px-3 space-y-1 opacity-50">
        ${_ST_STAGES.map((s, i) => `<div class="nav-item" style="display:block">
          <div class="flex items-center gap-2"><span class="w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center bg-slate-200 text-slate-600">${i + 1}</span>
          <span class="text-[13px] font-semibold">${s.label}</span></div></div>`).join('')}
      </nav>
      <div class="flex-1 flex items-center justify-center p-8">
        <div class="kg-card p-8 max-w-lg text-center">
          <div class="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center mx-auto mb-4"><i data-lucide="${copy.icon}" class="w-6 h-6"></i></div>
          <h2 class="font-bold text-slate-900 mb-2">${esc(copy.title)}</h2>
          <p class="text-sm text-slate-500 leading-relaxed mb-5">${esc(copy.body)}</p>
          <div class="flex items-center justify-center gap-2">
            <button onclick="go('#/products')" class="btn btn-primary">Explore an existing product</button>
            ${kind === 'occ' ? `<button onclick="$('st-lock-json').click()" class="btn btn-ghost">Import JSON</button>
              <input id="st-lock-json" type="file" accept=".json,application/json" class="hidden"
                     onchange="const f=this.files[0]; this.value=''; if(f) f.text().then(t=>_stImportJson(t, f.name));">` : ''}
          </div>
        </div>
      </div>
    </div>`;
  lucide.createIcons();
}

/* ── Stage 1: Extract ───────────────────────────────────────────────────────── */

/* Drop zone + JSON import. Rendered in EVERY extract state (full-size when
 * empty, compact below the current-run card otherwise) — a cached session must
 * never block starting a different product. A different file starts a fresh
 * session (reset in _stRunPhase1); the same file re-extracts keeping decisions.
 * The inputs clear their value so re-picking the same file fires onchange. */
function _stUploadArea(compact) {
  return `
    <div id="st-drop" class="drop ${compact ? 'p-6' : 'p-12'} text-center cursor-pointer" onclick="$('st-file').click()">
      <i data-lucide="upload-cloud" class="${compact ? 'w-6 h-6' : 'w-8 h-8'} mx-auto text-slate-300 mb-2"></i>
      <p class="${compact ? 'text-xs' : 'text-sm'} font-medium text-slate-600">Drop a STEP assembly here, or click to browse</p>
      <p class="text-xs text-slate-400 mt-1">${compact
        ? 'A different file starts a fresh session — the same file re-extracts and keeps your decisions.'
        : '.step / .stp — top-level assembly with positioned parts'}</p>
    </div>
    <input id="st-file" type="file" accept=".step,.stp" class="hidden"
           onchange="const f=this.files[0]; this.value=''; if(f) _stOnFile(f);">
    <div class="mt-3 text-xs text-slate-400 text-center">
      ${compact ? 'No STEP file for it?' : 'Already have prepared data?'}
      <button onclick="$('st-json-file').click()" class="text-blue-600 hover:underline">Import JSON</button>
      (components, connections &amp; transitions — skips the pipeline stages)
    </div>
    <input id="st-json-file" type="file" accept=".json,application/json" class="hidden"
           onchange="const f=this.files[0]; this.value=''; if(f) f.text().then(t=>_stImportJson(t, f.name));">`;
}

function _stNewFileArea() {
  return `
    <div class="mt-8 pt-5 border-t border-slate-100">
      <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Different product?</div>
      ${_stUploadArea(true)}
    </div>`;
}

function _stHookDrop() {
  setTimeout(() => {
    const d = $('st-drop'); if (!d) return;
    ['dragover', 'dragenter'].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.remove('drag'); }));
    d.addEventListener('drop', e => { if (e.dataTransfer.files[0]) _stOnFile(e.dataTransfer.files[0]); });
  }, 0);
}

function _stRenderExtract() {
  const el = $('st-sec-extract'); if (!el) return;
  if (ST.imported) {
    el.innerHTML = `
      <h2 class="text-lg font-bold text-slate-900 mb-1">Extract</h2>
      <p class="text-sm text-slate-500 mb-4">Prepared data was imported — the geometry stages are skipped.</p>
      <div class="kg-card p-4 flex items-center gap-4">
        <div class="w-10 h-10 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center"><i data-lucide="file-json" class="w-5 h-5"></i></div>
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-slate-800 truncate">${esc(ST.fileName)}</div>
          <div class="text-xs text-slate-400">${ST.labels.length} components · ${(ST.phase2?.transitions || []).length} transitions</div>
        </div>
        <button onclick="_stStartOver()" class="btn btn-ghost text-xs">Start over</button>
      </div>
      <div class="mt-4 flex justify-end"><button onclick="_stGoStep(4)" class="btn btn-primary">Review &amp; build <i data-lucide="arrow-right" class="w-4 h-4"></i></button></div>
      ${_stNewFileArea()}`;
  } else if (ST.phase1) {
    const t = ST.phase1.timing || {};
    el.innerHTML = `
      <h2 class="text-lg font-bold text-slate-900 mb-1">Extract</h2>
      <p class="text-sm text-slate-500 mb-4">Geometry has been extracted from the STEP file.</p>
      <div class="kg-card p-4 flex items-center gap-4">
        <div class="w-10 h-10 rounded-xl bg-green-50 text-green-600 flex items-center justify-center"><i data-lucide="check" class="w-5 h-5"></i></div>
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-slate-800 truncate">${esc(ST.fileName || 'assembly.step')}</div>
          <div class="text-xs text-slate-400">${ST.labels.length} parts · ${(t.total ?? 0).toFixed(1)}s total${t.geometry != null ? ` (geometry ${t.geometry.toFixed(1)}s)` : ''}</div>
        </div>
        <button onclick="_stReExtract()" class="btn btn-ghost text-xs" title="Run the pipeline again on the same file — decisions are kept when the parts match.">Re-extract</button>
        <button onclick="_stStartOver()" class="btn btn-ghost text-xs">Start over</button>
      </div>
      ${ST.phase1.log?.length ? `<details class="mt-3 text-xs"><summary class="cursor-pointer text-slate-400 select-none">Show extraction log</summary>
        <pre class="mt-2 bg-slate-900 text-slate-200 rounded-xl p-3 overflow-x-auto text-[10px] max-h-64 overflow-y-auto">${esc(ST.phase1.log.join('\n'))}</pre></details>` : ''}
      ${_stSettingsPanel()}
      <div class="mt-4 flex justify-end"><button onclick="_stGoStep(1)" class="btn btn-primary">Review contacts <i data-lucide="arrow-right" class="w-4 h-4"></i></button></div>
      ${_stNewFileArea()}`;
  } else {
    el.innerHTML = `
      <h2 class="text-lg font-bold text-slate-900 mb-1">Extract</h2>
      <p class="text-sm text-slate-500 mb-4">Upload a CAD assembly. The pipeline finds the surfaces the parts share, derives the test directions from them and checks along which directions every part can leave.</p>
      <div id="st-occ" class="text-xs text-slate-400 mb-3">Checking geometry engine…</div>
      <div id="st-run-area">${_stUploadArea(false)}</div>
      ${_stSettingsPanel()}`;
    _stCheckOcc();
  }
  _stRenderSettings();
  _stHookDrop();
  lucide.createIcons();
}

async function _stCheckOcc() {
  try {
    const r = await (await fetch(API.stepCheck())).json();
    const el = $('st-occ'); if (!el) return;
    if (r.available) {
      el.innerHTML = `<span class="text-green-600 font-medium">● Geometry engine ready</span>`;
    } else {
      _stLockedShell('occ', r.error);
    }
  } catch (e) { /* leave the checking note */ }
}

function _stReExtract() {
  if (_stFiles.length) { _stRunPhase1(_stFiles[0]); return; }
  // File objects don't survive reloads — re-pick, decisions are kept if labels match.
  toast('Pick the file again — your decisions are kept if the parts match.');
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.step,.stp';
  inp.onchange = () => { if (inp.files[0]) _stRunPhase1(inp.files[0]); };
  inp.click();
}

function _stOnFile(file) {
  if (!/\.(step|stp)$/i.test(file.name)) { toast('Please choose a .step / .stp file.'); return; }
  _stRunPhase1(file);
}

const _ST_RUN_STEPS = [
  ['Parsing assembly structure', 0.1],
  ['Finding shared contact surfaces', 0.3],
  ['Deriving test directions from the contacts', 0.45],
  ['Checking every pair in every direction', 0.8],
  ['Looking for two-step removals', 0.95],
  ['Detecting fasteners', 1.0],
];

async function _stRunPhase1(file) {
  if (_stAbort) { toast('A run is already in progress.'); return; }
  _stFiles = [file];
  const keepDecisions = ST.phase1 && ST.fileName === file.name;
  const area = $('st-run-area') || $('st-sec-extract');
  const t0 = Date.now();
  area.innerHTML = `
    <div class="kg-card p-5">
      <div class="flex items-center justify-between mb-3">
        <div class="font-semibold text-slate-800 text-sm">Extracting "${esc(file.name)}"</div>
        <div class="text-xs text-slate-400 font-mono" id="st-elapsed">0:00</div>
      </div>
      <div class="space-y-1.5 text-sm" id="st-run-steps">
        ${_ST_RUN_STEPS.map(([label], i) => `<div class="flex items-center gap-2" id="st-rs-${i}">
          <span class="w-4 h-4 flex-none rounded-full border-2 border-slate-200" data-role="dot"></span>
          <span class="text-slate-500">${esc(label)}</span></div>`).join('')}
      </div>
      <div class="text-[11px] text-slate-400 mt-3">A few seconds for small assemblies; larger assemblies take longer, depending on the machine.</div>
      <div class="mt-3"><button onclick="_stCancelRun()" class="btn btn-ghost text-xs">Cancel</button></div>
    </div>`;
  // staged checklist: timers advance the first steps, the last one only
  // completes when the response actually arrives
  const spin = (i) => { const d = $(`st-rs-${i}`)?.querySelector('[data-role=dot]'); if (d) d.outerHTML = `<span class="spin flex-none" style="width:1rem;height:1rem;border-width:2px"></span>`; };
  const check = (i) => { const row = $(`st-rs-${i}`); if (!row) return; row.firstElementChild.outerHTML = `<i data-lucide="check" class="w-4 h-4 flex-none text-green-600"></i>`; lucide.createIcons(); };
  spin(0);
  _stTimers = _ST_RUN_STEPS.slice(0, -1).map(([, frac], i) =>
    setTimeout(() => { check(i); spin(i + 1); }, 1500 + frac * 6000));
  _stTimers.push(setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    const el = $('st-elapsed'); if (el) el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }, 1000));

  const fd = new FormData();
  fd.append('step_files[]', file);
  fd.append('labels[]', file.name.replace(/\.(step|stp)$/i, ''));
  const settings = ST.settings || {};
  if (Object.keys(settings).length) fd.append('pipeline_settings', JSON.stringify(settings));

  _stAbort = new AbortController();
  try {
    const resp = await fetch(API.stepRun(), { method: 'POST', body: fd, signal: _stAbort.signal });
    const res = await resp.json();
    _stClearTimers();
    if (!res.success) {
      area.innerHTML = `<div class="kg-card p-5 border-red-200 bg-red-50">
        <div class="font-semibold text-red-700 text-sm mb-1">Extraction failed</div>
        <div class="text-xs text-red-600 mb-3">${esc(res.error || 'Unknown error')}</div>
        <button onclick="_stRenderExtract()" class="btn btn-ghost text-xs">Try again</button></div>`;
      return;
    }
    const oldLabels = ST.labels;
    const old = keepDecisions ? { fasteners: ST.fasteners, groups: ST.groups,
      rules: ST.rules, sepRules: ST.sepRules, product: ST.product } : null;
    _stReset();
    ST.settings = settings;
    _stFiles = [file];
    ST.fileName = file.name;
    delete res.interference_ratios;   // raw pixel ratios: the matrices are final
    ST.phase1 = res;
    ST.labels = res.parts || [];
    ST.fasteners = (res.suggested_fasteners || []).slice();
    // decisions only carry over when the part list is identical to that of the stored run
    if (old && JSON.stringify(res.parts) === JSON.stringify(oldLabels)) Object.assign(ST, old);
    if (!ST.product.name) {
      ST.product.name = file.name.replace(/\.(step|stp)$/i, '').replace(/[_-]+/g, ' ');
      ST.product.id = _libSlug(ST.product.name, 'Prod_');
    }
    _stTouch();
    _stRenderAllStages(); _stRenderPanel(); _stSubtitle(); _stGoStep(1);
    toast((res.volume_overlaps || []).length
      ? `${ST.labels.length} parts · ${res.volume_overlaps.length} overlapping pair(s) in the CAD model — see Contacts`
      : `${ST.labels.length} parts · ${res.contacts?.length ?? 0} contacts (${(res.timing?.total ?? 0).toFixed(1)}s)`);
  } catch (e) {
    _stClearTimers();
    if (e.name !== 'AbortError') {
      area.innerHTML = `<div class="kg-card p-5 border-red-200 bg-red-50 text-sm text-red-700">Connection error: ${esc(e.message)}
        <div class="mt-3"><button onclick="_stRenderExtract()" class="btn btn-ghost text-xs">Try again</button></div></div>`;
    } else {
      _stRenderExtract();
    }
  } finally {
    _stAbort = null;
  }
}

function _stCancelRun() { if (_stAbort) _stAbort.abort(); }
function _stClearTimers() { _stTimers.forEach(t => { clearTimeout(t); clearInterval(t); }); _stTimers = []; }

/* JSON import: prepared {product, components, connections, transitions} skips
 * the pipeline stages entirely and lands on Generate & Build (validate + graph
 * preview + build). Works with sample_data/*.json. */
function _stImportJson(text, fileName) {
  let data;
  try { data = JSON.parse(text); } catch (e) { toast('Not valid JSON: ' + e.message); return; }
  if (!data.components?.length || !data.transitions) { toast('Expected {product, components, connections, transitions}.'); return; }
  _stReset();
  ST.imported = true;
  ST.importData = data;
  ST.fileName = fileName || 'imported.json';
  ST.importNames = Object.fromEntries((data.components || []).map(c => [c.partId, c.name]));
  ST.labels = (data.components || []).map(c => `${c.name} (${c.partId})`);
  ST.product.name = data.product?.name
    || (fileName || '').replace(/\.json$/i, '').replace(/[_-]+/g, ' ').trim();
  ST.product.id = data.product?.id || _libSlug(ST.product.name, 'Prod_');
  ST.phase2 = { success: true, connections: data.connections || [], transitions: data.transitions || [] };
  ST.phase2Rev = ST.revision;
  _stPersist();
  if (!$('st-rail')) { renderStudio(); return; }  // imported from the OCC locked shell
  _stRenderAllStages(); _stUpdateRail(); _stRenderPanel(); _stSubtitle();
  _stGoStep(4);
  toast(`Imported ${data.components.length} components · ${(data.transitions || []).length} transitions`);
}

/* ── Stage 2: Contacts & separability (read-only, decided by the backend) ──── */

function _stRenderContacts() {
  const el = $('st-sec-contacts'); if (!el) return;
  if (!ST.phase1) { el.innerHTML = _stNeedUpload('Contacts'); return; }
  const thr = _stThr();
  const dirs = _stDirs();
  const rel = _stReleases();
  const overlaps = _stOverlaps();
  const used = ST.phase1.pipeline_settings_resolved?.interference || {};
  const dirText = used.directions === 'cardinal'
    ? 'The six axis directions.'
    : 'Normals and axes of the shared contact surfaces (Prasad et al. 2022).';
  const testText = used.reverse_check === 'off'
    ? 'In each direction every pair is checked in one rendered view.'
    : used.reverse_check === 'noncontact'
      ? 'In each direction every pair is checked in a rendered view, pairs without contact also from the opposite side.'
      : 'In each direction every pair is checked both ways in rendered projections.';
  const overlapCard = overlaps.length ? `
    <div class="mb-4 text-sm bg-red-50 border border-red-200 rounded-xl px-4 py-3">
      <div class="font-semibold text-red-700 mb-1">Overlapping parts in the CAD model</div>
      <div class="text-xs text-red-700 mb-2">Overlapping parts block each other in every direction, so they can never be separated and the assembly cannot be taken apart at all. Correct the model (for example, model threads and press fits without overlap) and extract again.</div>
      <ul class="text-xs text-red-700 list-disc pl-5 space-y-0.5">${overlaps.map(o => `<li>${esc(o.part1)} ↔ ${esc(o.part2)}: ${o.volume} mm³</li>`).join('')}</ul>
    </div>` : '';
  const fastPath = !ST.phase2 && !overlaps.length ? `
    <div class="mb-4 flex items-center gap-3 text-sm bg-green-50 border border-green-200 rounded-xl px-4 py-3">
      <i data-lucide="zap" class="w-4 h-4 text-green-600 flex-none"></i>
      <span class="text-green-800 flex-1">${_stContactCount()} contacts, ${dirs.length} test directions, ${ST.fasteners.length} detected fastener${ST.fasteners.length === 1 ? '' : 's'} — generate now or review the fasteners first.</span>
      <button onclick="_stGoStep(4); _stGenerate();" class="btn btn-primary text-xs flex-none">Generate now</button>
    </div>` : '';
  const relRows = rel.map(r => {
    const i = ST_ALPHABET.indexOf(r.part);
    const blockers = r.ignore.map(id => esc(_stPartFull(ST_ALPHABET.indexOf(id)))).join(', ');
    return `<div class="py-2 border-t border-slate-100 first:border-t-0">
      <div class="text-sm text-slate-700"><b>${esc(_stPartFull(i))}</b> slides ${r.min_shift.toFixed(1)}–${r.free_travel.toFixed(1)} mm along <span class="font-mono text-xs">${_stFmtDir(r.direction)}</span>,
        then leaves along ${r.second_move.map(d => `<span class="font-mono text-xs">${_stFmtDir(d)}</span>`).join(' or ')}.</div>
      <div class="text-[11px] text-slate-400 mt-0.5">The straight-line test sees it blocked along ${_stFmtDir(r.direction)} by ${blockers}; it clears its contact partners after ${r.min_shift.toFixed(1)} mm and reaches the first of them only after ${r.free_travel.toFixed(1)} mm, so that block is released.</div>
    </div>`;
  }).join('');
  el.innerHTML = `
    <h2 class="text-lg font-bold text-slate-900 mb-1">Contacts</h2>
    <p class="text-sm text-slate-500 mb-4">Which parts touch, and along which directions can each part leave? Both come straight from the geometry.</p>
    ${overlapCard}
    ${_stSettingsUsedLine()}
    ${fastPath}
    <div class="flex gap-4 items-start flex-wrap">
      <div class="kg-card p-4 flex-none">
        <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Liaison matrix</div>
        <canvas id="st-mx"></canvas>
        <div class="flex items-center gap-1.5 mt-2 text-[10px] text-slate-400">
          <span class="w-3 h-3 rounded-sm flex-none" style="background:#1d4ed8"></span> contact <span class="text-slate-300">·</span> lighter = larger gap
        </div>
        <div id="st-contact-line" class="mt-2 text-sm font-medium text-slate-700"></div>
      </div>
      <div class="flex-1 min-w-[280px] space-y-3">
        <div class="kg-card p-4">
          <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Contact</div>
          <p class="text-xs text-slate-500 mb-3">Two parts are in contact when their surfaces come within ${thr} mm of each other.${used.directions === 'cardinal' ? '' : ' Only shared surfaces contribute test directions.'}</p>
          <div id="st-histo" class="relative h-24 mb-1 select-none"></div>
          <div class="text-[10px] text-slate-400">Smallest gap of every part pair (log scale); the line marks ${thr} mm.</div>
        </div>
        <div class="kg-card p-4">
          <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Test directions (${dirs.length})</div>
          <p class="text-xs text-slate-500 mb-2">${dirText} ${testText}</p>
          <div class="flex flex-wrap gap-1.5">${dirs.map(d => `<span class="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">${_stFmtDir(d)}</span>`).join('')}</div>
        </div>
        <div class="kg-card p-4">
          <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Two-step removals (${rel.length})</div>
          ${rel.length ? relRows : `<p class="text-xs text-slate-400">${used.two_step === 'off' ? 'Detection of two-step removals is switched off in the analysis settings.' : 'None: no blocked part can slide clear of its contact partners and then leave sideways.'}</p>`}
        </div>
      </div>
    </div>
    <div class="mt-4 flex justify-between items-center">
      <button onclick="_stGoStep(0)" class="btn btn-ghost">Back</button>
      <button onclick="_stGoStep(2)" class="btn btn-primary">Confirm fasteners <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
    </div>`;
}

function _stNeedUpload(stage) {
  return `<h2 class="text-lg font-bold text-slate-900 mb-1">${esc(stage)}</h2>
    <div class="kg-card p-6 text-center text-sm text-slate-400">Upload a STEP file first.
      <div class="mt-3"><button onclick="_stGoStep(0)" class="btn btn-ghost text-xs">Go to Extract</button></div></div>`;
}

function _stAfterContactsVisible() {
  if (!ST.phase1) return;
  requestAnimationFrame(() => { _stDrawMatrix(); _stDrawHisto(); _stContactLine(); });
}

/* Matrix geometry cache for hit-testing */
let _stMx = { cell: 0, head: 0, n: 0 };

function _stGaps() {
  const G = ST.phase1.gap_matrix; const out = [];
  for (let i = 0; i < G.length; i++)
    for (let j = i + 1; j < G.length; j++)
      if (G[i][j] >= 0) out.push(G[i][j]);
  return out.sort((a, b) => a - b);
}

function _stDrawMatrix() {
  const cv = $('st-mx'); if (!cv || !ST.phase1) return;
  const G = ST.phase1.gap_matrix; const n = G.length;
  const lm = _stLiaison();
  const head = 22;
  const cell = Math.max(10, Math.min(26, Math.floor(560 / Math.max(n, 1))));
  const size = head + n * cell;
  const dpr = window.devicePixelRatio || 1;
  cv.width = size * dpr; cv.height = size * dpr;
  cv.style.width = size + 'px'; cv.style.height = size + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);
  _stMx = { cell, head, n };

  // shade scale: up to the upper quartile of all gaps (at least 2× the contact limit)
  const gaps = _stGaps();
  const gmax = Math.max(gaps[Math.floor(gaps.length * 0.75)] || 0, _stThr() * 2, 1e-9);

  ctx.font = '600 9px Inter, sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (let i = 0; i < n; i++) {
    const isF = ST.fasteners.includes(i);
    ctx.fillStyle = isF ? '#c2410c' : '#64748b';
    ctx.fillText(_stL(i), head + i * cell + cell / 2, head / 2);
    ctx.fillText(_stL(i), head / 2, head + i * cell + cell / 2);
  }
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const x = head + j * cell, y = head + i * cell;
      if (i === j) { ctx.fillStyle = '#f1f5f9'; ctx.fillRect(x, y, cell - 1, cell - 1); continue; }
      const contact = lm[i][j] === 1;
      const g = G[i][j];
      let bg;
      if (contact) bg = '#1d4ed8';
      else if (g < 0) bg = '#f8fafc';
      else { const t = Math.min(1, g / gmax); const l = 55 + t * 42; bg = `hsl(215, 60%, ${l}%)`; }
      ctx.fillStyle = bg;
      ctx.fillRect(x, y, cell - 1, cell - 1);
      if ((ST.fasteners.includes(i) || ST.fasteners.includes(j)) && !contact) {
        ctx.fillStyle = 'rgba(168,85,247,0.10)'; ctx.fillRect(x, y, cell - 1, cell - 1);
      }
    }
  }
  cv.onmousemove = _stMxMove; cv.onmouseleave = _stMxLeave;
  const line = $('st-contact-line'); if (line) line.style.maxWidth = size + 'px';
}

function _stMxCellAt(e) {
  const { cell, head, n } = _stMx;
  const i = Math.floor((e.offsetY - head) / cell);
  const j = Math.floor((e.offsetX - head) / cell);
  return (i >= 0 && j >= 0 && i < n && j < n && i !== j) ? [i, j] : null;
}

function _stMxMove(e) {
  const hit = _stMxCellAt(e);
  let tip = document.querySelector('.st-mx-tip');
  if (!hit) { if (tip) tip.style.display = 'none'; return; }
  const [i, j] = hit;
  const g = ST.phase1.gap_matrix[i][j];
  const lm = _stLiaison();
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'kg-tooltip st-mx-tip';
    document.body.appendChild(tip);
  }
  tip.style.display = 'block';
  tip.style.position = 'fixed';
  tip.style.left = (e.clientX + 14) + 'px';
  tip.style.top = (e.clientY + 14) + 'px';
  tip.innerHTML = `<b>${esc(_stPartFull(i))} ↔ ${esc(_stPartFull(j))}</b><br>
    ${g < 0 ? 'no finite gap' : 'gap ' + g.toPrecision(3) + ' mm'} · ${lm[i][j] ? 'contact' : 'no contact'}`;
}
function _stMxLeave() { const tip = document.querySelector('.st-mx-tip'); if (tip) tip.style.display = 'none'; }

/* Histogram of upper-triangle finite gaps on a log axis; the line is the fixed
 * contact limit. */
function _stDrawHisto() {
  const host = $('st-histo'); if (!host || !ST.phase1) return;
  const gaps = _stGaps();
  if (!gaps.length) { host.innerHTML = '<div class="text-xs text-slate-400">no gap data</div>'; return; }
  const thr = _stThr();
  const floor = Math.max(thr, 1e-6) / 100;
  const gmax = Math.max(gaps[gaps.length - 1], thr * 1.5, floor * 10);
  const lo = Math.log(floor), hi = Math.log(gmax * 1.05);
  const W = host.clientWidth || 320;
  const toX = (g) => (Math.log(Math.max(g, floor)) - lo) / (hi - lo) * W;

  const BINS = 30;
  const counts = new Array(BINS).fill(0);
  for (const g of gaps) {
    let b = Math.floor((Math.log(Math.max(g, floor)) - lo) / (hi - lo) * BINS);
    b = Math.max(0, Math.min(BINS - 1, b));
    counts[b]++;
  }
  const cmax = Math.max(...counts, 1);

  host.innerHTML = `
    <div class="absolute inset-x-0 bottom-4 top-2 flex items-end">
      ${counts.map((c, b) => {
        const gMid = Math.exp(lo + ((b + 0.5) / BINS) * (hi - lo));
        return `<div class="flex-1 mx-px rounded-t ${gMid < thr ? 'bg-blue-500' : 'bg-slate-300'}"
                     style="height:${(c / cmax) * 100}%" title="${c} pairs · gap ≈ ${gMid.toPrecision(2)} mm"></div>`;
      }).join('')}
    </div>
    <div class="absolute top-0 bottom-3 w-0.5 bg-blue-700" style="left:${toX(thr)}px">
      <div class="absolute -top-1 -translate-x-1/2 left-1/2 text-[9px] text-blue-700 font-semibold whitespace-nowrap">${thr} mm</div>
    </div>
    <div class="absolute bottom-0 left-0 text-[9px] text-slate-400">${floor.toPrecision(1)}</div>
    <div class="absolute bottom-0 right-0 text-[9px] text-slate-400">${gmax.toPrecision(2)}</div>`;
}

function _stContactLine() {
  const el = $('st-contact-line'); if (!el) return;
  const lm = _stLiaison();
  el.innerHTML = `${_stContactCount(lm)} contacts · ${_stConnected(lm)
    ? '<span class="text-green-600">graph connected ✓</span>'
    : '<span class="text-amber-600">⚠ not all parts are connected — a part that shares no surface with another cannot be placed in the assembly graph; check the CAD model</span>'}`;
}

/* ── Stage 3: Fasteners & Groups ───────────────────────────────────────────── */

/* Live consequence line for a fastener candidate, from the effective liaison
 * row (the backend's 2-neighbour rule: a fastener clamping exactly two
 * non-fastener parts emits one ScrewJoint between them). */
function _stFastenerConsequence(i, lm) {
  const on = ST.fasteners.includes(i);
  if (!on) return `<span class="text-slate-400">stays a Part</span>`;
  const nn = [];
  for (let j = 0; j < lm.length; j++)
    if (j !== i && lm[i][j] === 1 && !ST.fasteners.includes(j)) nn.push(j);
  const names = nn.map(j => esc(_stPartName(j)));
  if (nn.length === 2) return `<span class="text-green-700">clamps ${names[0]} + ${names[1]} → ScrewJoint</span>`;
  if (nn.length === 1) return `<span class="text-slate-500">touches only ${names[0]} — no clamped pair, stays press-fit</span>`;
  if (nn.length === 0) return `<span class="text-amber-600">⚠ touches no structural part — will be skipped</span>`;
  if (nn.length === 3) return `<span class="text-green-700">clamps ${names[0]} + ${names[1]} + ${names[2]} → three ScrewJoints, one task</span>`;
  return `<span class="text-red-600">⚠ touches ${nn.length} parts (${names.slice(0, 3).join(', ')}, …): generation stops for a fastener that clamps four or more parts</span>`;
}

function _stRenderGroups() {
  const el = $('st-sec-groups'); if (!el) return;
  if (!ST.phase1) { el.innerHTML = _stNeedUpload('Fasteners & Groups'); return; }
  const dets = ST.phase1.fastener_detections || [];
  const lm = _stLiaison();
  const rows = ST.labels.map((lbl, i) => {
    const det = dets.find(d => d.index === i) || {};
    const on = ST.fasteners.includes(i);
    return `<label class="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-slate-50 cursor-pointer">
      <input type="checkbox" ${on ? 'checked' : ''} onchange="_stToggleFastener(${i})" class="accent-orange-600 w-4 h-4">
      <span class="w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center flex-none ${on ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-500'}">${_stL(i)}</span>
      <span class="text-sm text-slate-700 w-44 min-w-0 truncate flex-none" title="${esc(lbl)}">${esc(_stPartName(i))}</span>
      ${det.method === 'name' ? `<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-orange-50 text-orange-600 flex-none" title="name-pattern match, confidence ${det.confidence ?? ''}">auto: name pattern</span>` : '<span class="flex-none w-2"></span>'}
      <span class="text-[11px] flex-1 min-w-0 truncate text-right">${_stFastenerConsequence(i, lm)}</span>
    </label>`;
  }).join('');
  el.innerHTML = `
    <h2 class="text-lg font-bold text-slate-900 mb-1">Fasteners & Groups</h2>
    <p class="text-sm text-slate-500 mb-4">Confirm which parts are fasteners. A fastener clamping two parts becomes a ScrewJoint and releases their direct contact.</p>
    <div class="kg-card p-2 mb-4">${rows}</div>
    <div class="flex items-center justify-between mb-2">
      <div>
        <h3 class="font-bold text-slate-800 text-sm">Groups</h3>
        <p class="text-xs text-slate-400">Identical parts removed as one — the lever that keeps the state graph tractable.</p>
      </div>
      <button onclick="_stOpenGroupPicker()" class="btn btn-ghost text-xs"><i data-lucide="plus" class="w-3.5 h-3.5"></i> New group</button>
    </div>
    <div id="st-groups-area"></div>
    <div class="text-[10px] text-slate-400 mt-2">Suggestions match name + contact pattern; structurally identical parts with different names must be grouped manually.</div>
    <div class="mt-4 flex justify-between items-center">
      <button onclick="_stGoStep(1)" class="btn btn-ghost">Back</button>
      <button onclick="_stGoStep(3)" class="btn btn-primary">Review rules <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
    </div>`;
  _stRenderGroupsArea();
  _stFetchSuggestions();
}

function _stToggleFastener(i) {
  const at = ST.fasteners.indexOf(i);
  if (at >= 0) ST.fasteners.splice(at, 1); else ST.fasteners.push(i);
  ST.fasteners.sort((a, b) => a - b);
  _stTouch();
  _stRenderGroups(); _stRenderPanel();
  if (ST.step === 1) _stDrawMatrix();
  lucide.createIcons();
}

let _stSuggestSeq = 0;

/* Fetch suggestions for the Phase-1 liaison matrix. Suggestions the user
 * already accepted or dismissed are filtered out. */
async function _stFetchSuggestions() {
  if (!ST.phase1 || !ST.fasteners.length) { _stRenderGroupsArea(); return; }
  const seq = ++_stSuggestSeq;
  try {
    const resp = await fetch(API.stepSuggestGroups(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fastener_indices: ST.fasteners.slice(),
        part_labels: ST.labels.slice(),
        liaison_matrix: _stLiaison(),
      }),
    });
    const res = await resp.json();
    if (seq !== _stSuggestSeq) return;  // stale response
    const activeKeys = new Set(ST.groups.map(g => g.members.join(',')));
    ST.suggestions = (res.suggested_groups || [])
      .filter(s => !activeKeys.has((s.members || []).slice().sort((a, b) => a - b).join(','))
                && !ST.dismissed.includes(s.name));
    _stRenderGroupsArea();
  } catch (e) { /* suggestions are sugar — stay quiet */ }
}

function _stGroupWhy(members, contactPattern) {
  const base = _stPartName(members[0]).replace(/\s*\d+$/, '');
  const touches = (contactPattern || []).map(j => _stPartName(j)).join(' + ');
  return `same base name "${base}"${touches ? `, all contacting ${touches}` : ''}`;
}

function _stRenderGroupsArea() {
  const el = $('st-groups-area'); if (!el) return;
  const chips = (members) => members.map(m =>
    `<span class="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 text-[10px] font-bold">${_stL(m)}</span>`).join(' ');

  const sugg = (ST.suggestions || []).map((s, k) => `
    <div class="kg-card p-3 mb-2 border-dashed">
      <div class="flex items-center gap-2 flex-wrap">
        <i data-lucide="layers" class="w-4 h-4 text-indigo-500"></i>
        <span class="font-semibold text-sm text-slate-800">${esc(s.name)}</span>
        <span class="flex gap-1">${chips(s.members)}</span>
        <span class="ml-auto flex gap-1.5">
          <button onclick="_stAcceptSuggestion(${k})" class="btn btn-primary text-xs py-1">Accept</button>
          <button onclick="_stDismissSuggestion(${k})" class="btn btn-ghost text-xs py-1">Dismiss</button>
        </span>
      </div>
      <div class="text-[11px] text-slate-400 mt-1 ml-6">Why: ${esc(_stGroupWhy(s.members, s.contact_pattern))}</div>
    </div>`).join('');

  const active = ST.groups.map((g, k) => `
    <div class="kg-card p-3 mb-2 ${g.accepted ? '' : 'opacity-50'}">
      <div class="flex items-center gap-2 flex-wrap">
        <i data-lucide="boxes" class="w-4 h-4 text-indigo-600"></i>
        <span class="font-semibold text-sm text-slate-800">${esc(g.name)}</span>
        <span class="flex gap-1">${chips(g.members)}</span>
        <span class="ml-auto flex gap-1.5 items-center">
          <button onclick="_stRenameGroup(${k})" class="text-slate-300 hover:text-blue-600" title="Rename"><i data-lucide="pencil" class="w-3.5 h-3.5"></i></button>
          <button onclick="_stDissolveGroup(${k})" class="text-slate-300 hover:text-red-500" title="Dissolve"><i data-lucide="x" class="w-4 h-4"></i></button>
        </span>
      </div>
      ${g.why ? `<div class="text-[11px] text-slate-400 mt-1 ml-6">${esc(g.why)}</div>` : ''}
    </div>`).join('');

  const dismissed = ST.dismissed.length
    ? `<div class="text-[11px] text-slate-400">Dismissed (${ST.dismissed.length}) · <button onclick="ST.dismissed=[];_stFetchSuggestions();" class="underline hover:text-blue-600">restore</button></div>`
    : '';

  el.innerHTML = `
    ${sugg ? `<div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Suggested</div>${sugg}` : ''}
    ${active ? `<div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5 mt-2">Active groups (${ST.groups.filter(g => g.accepted).length})</div>${active}` : ''}
    ${!sugg && !active ? `<div class="kg-card p-4 text-xs text-slate-400">No groups yet. ${ST.fasteners.length ? 'No identical-fastener pattern found — create one manually if parts are structurally identical.' : 'Mark fasteners above to get suggestions.'}</div>` : ''}
    ${dismissed}`;
  lucide.createIcons();
}

function _stAcceptSuggestion(k) {
  const s = (ST.suggestions || [])[k]; if (!s) return;
  ST.groups.push({ name: s.name, members: s.members.slice().sort((a, b) => a - b),
                   why: _stGroupWhy(s.members, s.contact_pattern), accepted: true });
  ST.suggestions.splice(k, 1);
  _stTouch(); _stRenderGroupsArea(); _stRenderPanel();
}

function _stDismissSuggestion(k) {
  const s = (ST.suggestions || [])[k]; if (!s) return;
  ST.dismissed.push(s.name);
  ST.suggestions.splice(k, 1);
  _stPersist(); _stRenderGroupsArea();
}

function _stRenameGroup(k) {
  const g = ST.groups[k]; if (!g) return;
  const name = prompt('Group name', g.name);
  if (name && name.trim()) { g.name = name.trim(); _stTouch(); _stRenderGroupsArea(); }
}

function _stDissolveGroup(k) {
  ST.groups.splice(k, 1);
  _stTouch(); _stRenderGroupsArea(); _stRenderPanel(); _stFetchSuggestions();
}

/* Manual group creation: pick parts (fasteners first, expandable to all). */
function _stOpenGroupPicker() {
  const order = [...ST.fasteners, ...ST.labels.map((_, i) => i).filter(i => !ST.fasteners.includes(i))];
  const overlay = document.createElement('div');
  overlay.id = 'st-group-picker';
  overlay.className = 'fixed inset-0 bg-slate-900/40 z-40 flex items-center justify-center p-6';
  overlay.innerHTML = `<div class="kg-card w-[420px] max-h-full overflow-y-auto p-5" onclick="event.stopPropagation()">
    <h3 class="font-bold text-slate-900 mb-1">New group</h3>
    <p class="text-xs text-slate-400 mb-3">Members are removed as one unit. Grouping parts that touch different neighbours can hide valid sequences.</p>
    <label class="block mb-3"><span class="text-[11px] font-medium text-slate-500">Name</span>
      <input id="st-gp-name" class="mt-0.5 w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" placeholder="e.g. 2x M8 screw"></label>
    <div class="border border-slate-100 rounded-xl p-2 max-h-64 overflow-y-auto mb-2">
      ${order.map((i, idx) => `<label class="flex items-center gap-2 text-sm py-1 px-1.5 rounded hover:bg-slate-50 cursor-pointer ${!ST.fasteners.includes(i) ? 'st-gp-struct hidden' : ''}">
        <input type="checkbox" class="st-gp-cb accent-indigo-600" value="${i}">
        <span class="w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center ${ST.fasteners.includes(i) ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-500'}">${_stL(i)}</span>
        <span class="truncate">${esc(_stPartName(i))}</span>
      </label>`).join('')}
      ${order.some(i => !ST.fasteners.includes(i)) ? `<button onclick="document.querySelectorAll('.st-gp-struct').forEach(e=>e.classList.remove('hidden'));this.remove()" class="text-[11px] text-blue-600 hover:underline px-1.5 py-1">Show all parts…</button>` : ''}
    </div>
    <div id="st-gp-warn" class="text-[11px] text-amber-600 mb-2 hidden">⚠ These parts touch different neighbours — grouping forces them to be removed together and can hide valid sequences.</div>
    <div class="flex justify-end gap-2">
      <button onclick="document.getElementById('st-group-picker').remove()" class="btn btn-ghost text-sm">Cancel</button>
      <button onclick="_stCreateGroup()" class="btn btn-primary text-sm">Create</button>
    </div></div>`;
  overlay.addEventListener('click', () => overlay.remove());
  overlay.addEventListener('change', (e) => {
    if (!e.target.classList?.contains('st-gp-cb')) return;
    // soft warning when selected parts have differing non-member contact sets
    const sel = [...overlay.querySelectorAll('.st-gp-cb:checked')].map(cb => +cb.value);
    const lm = _stLiaison();
    const pats = new Set(sel.map(i => lm[i].map((v, j) => (j !== i && !sel.includes(j) && v) ? j : -1).filter(x => x >= 0).join(',')));
    overlay.querySelector('#st-gp-warn').classList.toggle('hidden', sel.length < 2 || pats.size <= 1);
  });
  document.body.appendChild(overlay);
}

function _stCreateGroup() {
  const overlay = $('st-group-picker'); if (!overlay) return;
  const members = [...overlay.querySelectorAll('.st-gp-cb:checked')].map(cb => +cb.value).sort((a, b) => a - b);
  if (members.length < 2) { toast('Pick at least two parts.'); return; }
  const name = (overlay.querySelector('#st-gp-name').value || '').trim()
    || `${members.length}x ${_stPartName(members[0])}`;
  ST.groups.push({ name, members, why: 'manual group', accepted: true });
  overlay.remove();
  _stTouch(); _stRenderGroupsArea(); _stRenderPanel();
}

/* ── Explosion-risk gauge (server-authoritative via estimate_only) ─────────── */

let _stEstTimer = null, _stEstSeq = 0;

function _stEstimate() {
  if (!ST.phase1) return;
  clearTimeout(_stEstTimer);
  _stEstTimer = setTimeout(async () => {
    const seq = ++_stEstSeq;
    const post = (payload) => fetch(API.stepGenerateTables(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json()).catch(() => null);
    const withGroups = _stPhase2Payload(true);
    const noGroups = { ..._stPhase2Payload(true), fastener_groups: null };
    const [a, b] = await Promise.all([post(withGroups), post(noGroups)]);
    if (seq !== _stEstSeq) return;  // stale
    ST.estimates = {
      with: a?.aog_estimate || null, withError: a && !a.success ? a.error : null,
      without: b?.aog_estimate || null,
    };
    _stPersist();
    _stRenderGauge();
    _stUpdateRail();
  }, 300);
}

function _stRenderGauge() {
  const el = $('st-gauge'); if (!el) return;
  const est = ST.estimates?.with;
  if (!ST.phase1 || !est) { el.innerHTML = ''; return; }
  const cap = est.cap_transitions || 200000;
  const t = est.est_transitions ?? 0;
  const frac = t / cap;
  const over = frac > 1 || !!ST.estimates.withError;
  const zone = over ? 'red' : frac > 0.05 ? 'amber' : 'green';
  const color = { green: '#16A34A', amber: '#D97706', red: '#DC2626' }[zone];
  // log-scale position so the green zone doesn't vanish visually
  const pos = Math.min(1, Math.log10(1 + t) / Math.log10(1 + cap));
  const without = ST.estimates?.without;
  const gain = without && without.est_transitions > t
    ? `<div class="text-[10px] text-slate-400 mt-1">without groups: ~${without.est_transitions.toLocaleString('en-US')}</div>` : '';
  const partsLine = `${ST.labels.length} parts${est.parts_after_grouping !== ST.labels.length ? ` → ${est.parts_after_grouping} after grouping` : ''}`;
  const capNodes = (est.cap_nodes || 1000000).toLocaleString('en-US');
  el.innerHTML = `
    <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Explosion risk</div>
    <div class="h-2 rounded-full bg-slate-100 relative overflow-hidden mb-1">
      <div class="absolute inset-y-0 left-0 rounded-full" style="width:${Math.max(3, pos * 100)}%;background:${color}"></div>
    </div>
    <div class="text-[11px] font-semibold" style="color:${color}">
      ~${t.toLocaleString('en-US')} transitions (estimate) ${over ? '· generation will refuse' : ''}
    </div>
    <div class="text-[10px] text-slate-400 mt-0.5">${esc(partsLine)}</div>
    <div class="text-[10px] text-slate-400 mt-1 leading-snug">Rough estimate from the contacts alone: it counts the parts that hang on one shared base, the usual cause of explosive growth. The generated graph can be smaller (blocking) or larger (other branching); densely connected assemblies can still exceed the ${capNodes}-state limit during generation — group identical fasteners first.</div>
    ${gain}
    ${over ? `<button onclick="_stGoStep(2)" class="btn btn-ghost text-xs mt-1.5 w-full">Group identical parts</button>` : ''}`;
}

/* ── Stage 4: Rules ─────────────────────────────────────────────────────────── */

const _ST_GUARDS = [
  ['shield', 'Phantom states', 'States where a fastener is gone but its clamped parts still hang together are rejected.'],
  ['unlink', 'Broken connection', 'Every transition must dissolve at least one defined connection; splits that dissolve nothing are dropped. A screwed joint is dissolved only by removing its fastener.'],
  ['split', 'Disintegration', 'If a removal splits the remainder into pieces, each piece becomes its own assembly.'],
  ['route', 'Reachability', "Transitions that can't be reached from the full assembly are pruned."],
];

function _stPartSelect(value, onchange, extra) {
  return `<select onchange="${onchange}" class="border border-slate-200 rounded-lg px-1.5 py-1 text-sm font-medium text-slate-700 ${extra || ''}">
    ${ST.labels.map((_, i) => `<option value="${_stL(i)}" ${_stL(i) === value ? 'selected' : ''}>${_stL(i)} — ${esc(_stPartName(i))}</option>`).join('')}
  </select>`;
}

/* Category pruning badge: the backend reports totals per check, not per rule,
 * so the badge is labelled "all rules of this kind" and shows a zero count clearly. */
function _stRuleBadge(kind) {
  if (!ST.phase2 || _stIsStale()) return `<span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-400">not yet run</span>`;
  const s = ST.phase2.rule_stats || {};
  const n = kind === 'prec' ? (s.precedence || 0) : (s.separation_precedence || 0);
  if (n === 0) return `<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600" title="This kind of rule never applied in the last generation — check the parts.">0 removed — never applied</span>`;
  return `<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600" title="Transitions removed in the last generation, total across all rules of this kind.">−${n} transitions</span>`;
}

function _stRenderRules() {
  const el = $('st-sec-rules'); if (!el) return;
  if (!ST.phase1) { el.innerHTML = _stNeedUpload('Rules'); return; }

  const precCards = ST.rules.map((r, k) => `
    <div class="kg-card p-3 mb-2">
      <div class="flex items-center gap-2 flex-wrap text-sm text-slate-600">
        <i data-lucide="lock" class="w-4 h-4 text-blue-500 flex-none"></i>
        ${_stPartSelect(r.part, `ST.rules[${k}].part=this.value;_stTouch();`)}
        <span>cannot be removed while</span>
        ${r.blockers.map((b, bi) => `${bi > 0 ? '<span class="text-slate-400">and</span>' : ''}${_stPartSelect(b, `ST.rules[${k}].blockers[${bi}]=this.value;_stTouch();`)}`).join(' ')}
        <span>is mounted.</span>
        <button onclick="ST.rules[${k}].blockers.push(_stL(0));_stTouch();_stRenderRules();" class="text-[10px] text-blue-600 hover:underline">+ and</button>
        <span class="ml-auto flex items-center gap-2">${_stRuleBadge('prec')}
          <button onclick="ST.rules.splice(${k},1);_stTouch();_stRenderRules();_stRenderPanel();" class="text-slate-300 hover:text-red-500"><i data-lucide="x" class="w-4 h-4"></i></button></span>
      </div>
      <div class="text-[10px] text-slate-400 mt-1 ml-6">Removing the blocker by itself is always allowed — the rule only blocks pulling the part out past a mounted blocker.</div>
    </div>`).join('');

  const sepCards = ST.sepRules.map((r, k) => `
    <div class="kg-card p-3 mb-2">
      <div class="flex items-center gap-2 flex-wrap text-sm text-slate-600">
        <i data-lucide="scissors" class="w-4 h-4 text-violet-500 flex-none"></i>
        ${_stPartSelect(r.part1, `ST.sepRules[${k}].part1=this.value;_stTouch();`)}
        <span>and</span>
        ${_stPartSelect(r.part2, `ST.sepRules[${k}].part2=this.value;_stTouch();`)}
        <span>can only separate after removing</span>
        ${r.requires_removed.map((b, bi) => `${bi > 0 ? '<span class="text-slate-400">or</span>' : ''}${_stPartSelect(b, `ST.sepRules[${k}].requires_removed[${bi}]=this.value;_stTouch();`)}`).join(' ')}
        <button onclick="ST.sepRules[${k}].requires_removed.push(_stL(0));_stTouch();_stRenderRules();" class="text-[10px] text-blue-600 hover:underline">+ or</button>
        <span class="ml-auto flex items-center gap-2">${_stRuleBadge('sep')}
          <button onclick="ST.sepRules.splice(${k},1);_stTouch();_stRenderRules();_stRenderPanel();" class="text-slate-300 hover:text-red-500"><i data-lucide="x" class="w-4 h-4"></i></button></span>
      </div>
      <div class="text-[10px] text-slate-400 mt-1 ml-6">Use this when the blocker isn't a direct neighbour — e.g. an end plate blocking a shaft's extraction path.</div>
    </div>`).join('');

  const invalid = _stRuleProblems();

  el.innerHTML = `
    <div class="flex items-center justify-between mb-1">
      <h2 class="text-lg font-bold text-slate-900">Rules</h2>
      <span class="relative">
        <button onclick="$('st-rule-menu').classList.toggle('hidden')" class="btn btn-primary text-xs"><i data-lucide="plus" class="w-3.5 h-3.5"></i> Add rule</button>
        <span id="st-rule-menu" class="hidden absolute right-0 top-9 kg-card p-1.5 w-64 z-20">
          <button onclick="_stAddPrecRule()" class="block w-full text-left px-2.5 py-2 rounded-lg hover:bg-slate-50 text-sm"><b>Removal order</b><br><span class="text-[11px] text-slate-400">"X cannot be removed while Y is mounted"</span></button>
          <button onclick="_stAddSepRule()" class="block w-full text-left px-2.5 py-2 rounded-lg hover:bg-slate-50 text-sm"><b>Blocked separation</b><br><span class="text-[11px] text-slate-400">"A and B can only separate after removing C"</span></button>
        </span>
      </span>
    </div>
    <p class="text-sm text-slate-500 mb-4">Constrain the removal order. Most assemblies don't need custom rules — add one when the generated graph allows an order that is physically impossible.</p>
    ${invalid ? `<div class="mb-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">${esc(invalid)}</div>` : ''}
    <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Your rules (${ST.rules.length + ST.sepRules.length})</div>
    ${precCards}${sepCards}
    ${!ST.rules.length && !ST.sepRules.length ? `<div class="kg-card p-4 text-xs text-slate-400 mb-2">No custom rules — the guards below always apply.</div>` : ''}
    <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5 mt-4">Built-in guards — always active, part of the method</div>
    <div class="grid grid-cols-2 gap-2">
      ${_ST_GUARDS.map(([ic, t, b]) => `<div class="kg-card p-3 opacity-75">
        <div class="flex items-center gap-2 mb-1"><i data-lucide="${ic}" class="w-4 h-4 text-slate-400"></i><span class="font-semibold text-sm text-slate-700">${t}</span></div>
        <div class="text-[11px] text-slate-400 leading-snug">${b}</div></div>`).join('')}
    </div>
    <div class="mt-4 flex justify-between items-center">
      <button onclick="_stGoStep(2)" class="btn btn-ghost">Back</button>
      <button onclick="_stGoStep(4)" class="btn btn-primary">Generate <i data-lucide="arrow-right" class="w-4 h-4"></i></button>
    </div>`;
  lucide.createIcons();
}

function _stRuleProblems() {
  for (const r of ST.rules)
    if (r.blockers.includes(r.part)) return `"${r.part}" cannot block itself — pick two different parts.`;
  for (const r of ST.sepRules) {
    if (r.part1 === r.part2) return 'A separation rule needs two different parts.';
    if (r.requires_removed.includes(r.part1) || r.requires_removed.includes(r.part2))
      return 'The part to remove first must differ from the separating pair.';
  }
  return null;
}

function _stAddPrecRule() {
  $('st-rule-menu')?.classList.add('hidden');
  ST.rules.push({ part: _stL(0), blockers: [_stL(Math.min(1, ST.labels.length - 1))] });
  _stTouch(); _stRenderRules(); _stRenderPanel();
}

function _stAddSepRule() {
  $('st-rule-menu')?.classList.add('hidden');
  ST.sepRules.push({ part1: _stL(0), part2: _stL(Math.min(1, ST.labels.length - 1)),
                     requires_removed: [_stL(Math.min(2, ST.labels.length - 1))] });
  _stTouch(); _stRenderRules(); _stRenderPanel();
}

/* Rules -> generate-tables payload shapes ({X:[Y]} + separation list). */
function _stCollectRules() {
  const prec = {};
  for (const r of ST.rules) {
    if (!r.part || !r.blockers?.length) continue;
    prec[r.part] = (prec[r.part] || []).concat(r.blockers);
  }
  return {
    precedence_rules: Object.keys(prec).length ? prec : null,
    separation_precedence: ST.sepRules.length ? ST.sepRules : null,
  };
}

/* ── Stage 5: Generate & Build ─────────────────────────────────────────────── */

function _stPhase2Payload(estimateOnly) {
  const { precedence_rules, separation_precedence } = _stCollectRules();
  const groups = ST.groups.filter(g => g.accepted)
    .map(g => ({ name: g.name, members: g.members.slice() }));  // 0-based ints!
  return {
    fastener_indices: ST.fasteners.slice(),
    part_labels: ST.labels.slice(),
    liaison_matrix: _stLiaison(),
    interference_matrices: _stInterference(),
    precedence_rules,
    separation_precedence,
    fastener_groups: groups.length ? groups : null,
    ...(estimateOnly ? { estimate_only: true } : {}),
  };
}

function _stRenderGenerate() {
  const el = $('st-sec-generate'); if (!el) return;
  if (!ST.phase1 && !ST.imported) { el.innerHTML = _stNeedUpload('Generate & Build'); return; }
  const nGroups = ST.groups.filter(g => g.accepted).length;
  const nRules = ST.rules.length + ST.sepRules.length;
  const summary = ST.imported
    ? `${ST.labels.length} imported components · ${(ST.phase2?.transitions || []).length} transitions — review and build.`
    : `${ST.labels.length} parts · ${ST.fasteners.length} fasteners${nGroups ? ` in ${nGroups} group${nGroups > 1 ? 's' : ''}` : ''} · ${_stContactCount()} contacts · ${nRules} custom rule${nRules === 1 ? '' : 's'}`;
  el.innerHTML = `
    <h2 class="text-lg font-bold text-slate-900 mb-1">Generate & Build</h2>
    <p class="text-sm text-slate-500 mb-4">${summary}</p>
    <div id="st-stale" class="hidden mb-3 text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">Inputs changed since generation — regenerate before building.</div>
    ${ST.imported ? '' : `<div class="mb-4"><button onclick="_stGenerate()" class="btn btn-primary" id="st-gen-btn"><i data-lucide="play" class="w-4 h-4"></i> Generate transitions</button></div>`}
    <div id="st-results"></div>
    <div class="kg-card p-4 mt-4">
      <div class="grid grid-cols-2 gap-3 mb-3">
        <label class="block"><span class="text-[11px] font-medium text-slate-500">Product name</span>
          <input id="st-pname" value="${esc(ST.product.name)}" oninput="ST.product.name=this.value; const idEl=$('st-pid'); if(idEl && !idEl.dataset.touched){ idEl.value=_libSlug(this.value,'Prod_'); ST.product.id=idEl.value; } _stPersist();"
                 class="mt-0.5 w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm"></label>
        <label class="block"><span class="text-[11px] font-medium text-slate-500">Product ID</span>
          <input id="st-pid" value="${esc(ST.product.id)}" oninput="this.dataset.touched=1; ST.product.id=this.value; _stPersist();"
                 class="mt-0.5 w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm font-mono"></label>
      </div>
      <div class="flex items-center justify-between gap-3">
        <span class="text-[11px] text-slate-400">Nothing is written until you build. Your session survives reloads on this browser.</span>
        <button onclick="_stBuild()" id="st-build-btn" disabled class="btn btn-accent disabled:opacity-40"><i data-lucide="database" class="w-4 h-4"></i> Build knowledge graph</button>
      </div>
      <div id="st-build-msg" class="mt-2"></div>
    </div>`;
  if (ST.phase2) _stRenderResults();
  _stStaleUI();
}

async function _stGenerate() {
  const btn = $('st-gen-btn'); if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin" style="width:0.9rem;height:0.9rem;border-width:2px"></span> Enumerating assembly states…'; }
  try {
    const resp = await fetch(API.stepGenerateTables(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_stPhase2Payload(false)),
    });
    const res = await resp.json();
    ST.phase2 = res;
    ST.phase2Rev = ST.revision;
    _stPersist();
    _stRenderGenerate();
    _stRenderRules();      // refresh the per-rule pruning badges
    _stUpdateRail();
    if (!res.success) toast('Generation refused — see the message below.');
  } catch (e) {
    toast('Generation failed: ' + e.message);
  } finally {
    const b = $('st-gen-btn'); if (b) { b.disabled = false; b.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i> Generate transitions'; lucide.createIcons(); }
  }
}

function _stRenderResults() {
  const el = $('st-results'); if (!el) return;
  const r = ST.phase2;
  if (!r) { el.innerHTML = ''; return; }
  if (!r.success || r.error) {
    el.innerHTML = `<div class="kg-card p-4 border-red-200 bg-red-50">
      <div class="font-semibold text-red-700 text-sm mb-1">Generation refused</div>
      <div class="text-xs text-red-600 leading-relaxed mb-3">${esc(r.error || 'Unknown error')}</div>
      <button onclick="_stGoStep(2)" class="btn btn-ghost text-xs">Back to groups</button></div>`;
    return;
  }
  const trans = r.transitions || [];
  const states = new Set();
  trans.forEach(t => { states.add(t.from_parts); (t.results_in || []).forEach(x => { if (x.length > 1) states.add(x); }); });
  // one task per connection, or per bundle of connections released by one fastener group
  const canonOf = _stBundleOf();
  const tasks = (r.connections || []).filter(c => (canonOf[c.id] || c.id) === c.id).length;
  el.innerHTML = `
    <div class="grid grid-cols-4 gap-3 mb-3">
      ${[[r.connections?.length ?? 0, 'Connections'], [trans.length, 'Transitions'],
         [states.size, 'Assembly states'], [tasks, 'Tasks (derived)']]
        .map(([v, l]) => `<div class="metric"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('')}
    </div>
    <div id="st-rule-stats"></div>
    <div id="st-review"></div>`;
  _stRenderRuleStats();
  _stRenderReview();
  _stStaleUI();
}

/* Compact display of the pruning counters (rule_stats). */
function _stRenderRuleStats() {
  const el = $('st-rule-stats'); if (!el) return;
  const s = ST.phase2?.rule_stats;
  if (!s) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="text-[11px] text-slate-400 mb-3">Guards pruned: ${s.phantom_states} phantom states · ${s.torn_fastener_joints || 0} fastener joints kept · ${s.no_broken_connection} no-joint splits · ${s.duplicates || 0} duplicates · ${s.precedence} precedence · ${s.separation_precedence} separation · ${s.trapped_components || 0} trapped · ${s.reachability} unreachable</div>`;
}

/* Library items for the semantic-review dropdowns (shared taxonomy, cached). */
/* Fetched on every review render (three small GETs), so tools added in the
 * library page in the meantime show up without reloading the studio. */
let _stLib = null;
async function _stLoadLib() {
  const get = (label) => fetch(API.libraryItems(label)).then(r => r.json()).catch(() => []);
  const [types, agents, tools] = await Promise.all([get('ConnectionType'), get('Agent'), get('Tool')]);
  _stLib = { types, agents, tools };
  return _stLib;
}

/* Review: edit semantics (connection type / agent / tool), never structure —
 * endpoints, fastener bindings and transitions are derived from geometry+rules.
 * Plus the client-synthesized condensed state-graph preview. */
function _stRenderReview() {
  const el = $('st-review'); if (!el) return;
  const conns = ST.phase2?.connections || [];
  const trans = ST.phase2?.transitions || [];
  if (!conns.length && !trans.length) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="kg-card p-4 mb-3">
      <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Connections — review joint types and who separates them</div>
      <div id="st-conn-rows" class="max-h-[28rem] overflow-y-auto pr-1"><div class="text-xs text-slate-400">Loading library…</div></div>
    </div>
    <div class="kg-card p-4 mb-3">
      <div class="flex items-center justify-between mb-2">
        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">State graph preview (condensed)</span>
        <span id="st-preview-note" class="text-[10px] text-slate-400"></span>
      </div>
      <div id="st-preview" style="height:340px" class="rounded-xl bg-[#fbfdff] border border-slate-100"></div>
    </div>
    <details class="kg-card p-4 mb-3">
      <summary class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide cursor-pointer select-none">Transitions (${trans.length}, read-only — derived from geometry + rules)</summary>
      <div class="mt-2 space-y-0.5 max-h-56 overflow-y-auto text-xs font-mono text-slate-500">
        ${trans.slice(0, 400).map(t => `<div>${esc(t.id)}  ${esc(t.from_parts)} → ${(t.results_in || []).map(esc).join(' + ')}</div>`).join('')}
        ${trans.length > 400 ? `<div class="text-slate-400">… ${trans.length - 400} more</div>` : ''}
      </div>
    </details>
    <div class="flex justify-end mb-1"><button onclick="_stDownloadJson()" class="btn btn-ghost text-xs"><i data-lucide="download" class="w-3.5 h-3.5"></i> Download JSON</button></div>`;
  _stRenderConnRows();
  _stPreviewGraph();
  lucide.createIcons();
}

/* Connections dissolved by one operation (a screw group, a multi-part screwed
 * joint) form a bundle with one task: only the first row of a bundle is edited,
 * the others show as "same task" and receive its type, agent and tool. */
function _stBundleOf() {
  const canonOf = {};
  for (const [canon, members] of Object.entries(ST.phase2?.connection_bundles || {}))
    for (const m of members) canonOf[m] = canon;
  return canonOf;
}

function _stSetConn(k, field, value) {
  const conns = ST.phase2.connections;
  const id = conns[k].id;
  const members = (ST.phase2.connection_bundles || {})[id] || [id];
  for (const c of conns) if (members.includes(c.id)) c[field] = value;
  _stPersist();
  if (field === 'connectionType_id') _stFetchTaskNames();
}

async function _stRenderConnRows() {
  const host = $('st-conn-rows'); if (!host) return;
  const lib = await _stLoadLib();
  const conns = ST.phase2?.connections || [];
  const canonOf = _stBundleOf();
  const rowOf = Object.fromEntries(conns.map((c, k) => [c.id, k]));
  const opt = (items, cur, idKey) => items.map(it =>
    `<option value="${esc(it.id)}" ${it.id === cur ? 'selected' : ''}>${esc(it.name || it.id)}</option>`).join('');
  const label = (c) => `
      <div class="flex items-center gap-x-2 gap-y-0.5 flex-wrap min-w-0" title="${esc(`${_stNameById(c.part1)} (${c.part1}) ↔ ${_stNameById(c.part2)} (${c.part2})${c.fastener_id ? ` via ${_stNameById(c.fastener_id)} (${c.fastener_id})` : ''}`)}">
        <span class="flex items-center gap-1 text-slate-700 font-medium min-w-0">${_stPartTag(c.part1)}<span class="flex-none text-slate-400">↔</span>${_stPartTag(c.part2)}</span>
        ${c.fastener_id ? `<span class="flex items-center gap-1 text-[10px] text-orange-600 min-w-0"><span class="flex-none">via</span>${_stPartTag(c.fastener_id, true)}</span>` : ''}
      </div>`;
  host.innerHTML = conns.map((c, k) => {
    const canon = canonOf[c.id] || c.id;
    if (canon !== c.id) {
      return `
    <div class="text-xs py-1.5 border-t border-slate-100 first:border-t-0 opacity-70">
      ${label(c)}
      <div class="text-[10px] text-slate-400 mt-0.5 ml-0.5">same task as row ${rowOf[canon] + 1} — type, agent and tool follow that row</div>
    </div>`;
    }
    const n = ((ST.phase2.connection_bundles || {})[c.id] || [c.id]).length;
    return `
    <div class="text-xs py-2.5 border-t border-slate-100 first:border-t-0">
      ${label(c)}
      ${n > 1 ? `<div class="text-[10px] text-slate-500 mt-0.5 ml-0.5">row ${k + 1} · one operation for ${n} connections</div>` : ''}
      <div class="grid grid-cols-3 gap-2 mt-1.5">
        <select onchange="_stSetConn(${k}, 'connectionType_id', this.value)" class="border border-slate-200 rounded-lg px-1.5 py-1 min-w-0" title="Connection type">${opt(lib.types, c.connectionType_id)}</select>
        <select onchange="_stSetConn(${k}, 'agent_id', this.value)" class="border border-slate-200 rounded-lg px-1.5 py-1 min-w-0" title="Agent">${opt(lib.agents, c.agent_id)}</select>
        <select onchange="_stSetConn(${k}, 'tool_id', this.value)" class="border border-slate-200 rounded-lg px-1.5 py-1 min-w-0" title="Tool">${opt(lib.tools, c.tool_id)}</select>
      </div>
      <div class="flex items-center gap-2 mt-1.5">
        <span class="flex-none text-[10px] font-semibold text-slate-400 uppercase tracking-wide w-9">Task</span>
        <input id="st-task-${k}" value="${esc(c.task_name || '')}" placeholder="…"
               oninput="ST.phase2.connections[${k}].task_name=this.value;_stPersist();"
               class="border border-slate-200 rounded-lg px-1.5 py-1 flex-1 min-w-0">
      </div>
    </div>`;
  }).join('');
  _stFetchTaskNames();
}

/* The automatic task names come from the backend (models.kg_builder, the same
 * code the build uses) and are shown as each field's placeholder; typing a name
 * overrides it. Refetched when a connection type changes (it sets the verb). */
let _stTaskSeq = 0;
async function _stFetchTaskNames() {
  const conns = ST.phase2?.connections || [];
  if (!conns.length) return;
  const seq = ++_stTaskSeq;
  let names = {};
  try {
    const res = await (await fetch(API.stepTaskNames(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_stBuildPayloadPreview()),
    })).json();
    names = res.task_names || {};
  } catch (e) { /* suggestion only */ }
  if (seq !== _stTaskSeq) return;  // stale response
  conns.forEach((c, k) => {
    const inp = $(`st-task-${k}`); if (!inp) return;
    const auto = names[c.id];
    inp.placeholder = auto ? `${auto}  (automatic — type to rename)` : 'Task name (automatic)';
    inp.title = auto ? `Automatic name: ${auto}. Type your own name to replace it; clear the field to go back.` : '';
  });
}

/* Synthesize the condensed {nodes,edges} payload from phase2.transitions —
 * mirrors models/product.py:condense_transitions: single-part removals become
 * REMOVES edges, multi-splits keep a compact Transition node. */
function _stPreviewGraph() {
  const host = $('st-preview'); if (!host) return;
  const trans = ST.phase2?.transitions || [];
  const note = $('st-preview-note');
  if (!trans.length) { host.innerHTML = '<div class="text-xs text-slate-400 p-4">no transitions</div>'; return; }

  let shown = trans;
  if (trans.length > 400) {
    // depth-limited BFS from the root so the preview stays paintable
    const root = trans.reduce((a, t) => (t.from_parts.length > a.length ? t.from_parts : a), '');
    const depthOf = new Map([[root, 0]]);
    shown = [];
    let frontier = [root];
    for (let d = 0; d < 3 && frontier.length; d++) {
      const next = [];
      for (const t of trans) {
        if (!frontier.includes(t.from_parts)) continue;
        shown.push(t);
        for (const r of t.results_in || []) if (r.length > 1 && !depthOf.has(r)) { depthOf.set(r, d + 1); next.push(r); }
      }
      frontier = next;
    }
    if (note) note.textContent = `showing the first 3 disassembly levels (${shown.length} of ${trans.length} transitions)`;
  } else if (note) note.textContent = '';

  const nodes = new Map(); const edges = [];
  const partName = _stNameById;
  const addState = (s) => {
    const id = 'st_' + s;
    if (!nodes.has(id)) nodes.set(id, { id, labels: [s.length > 1 ? 'Assembly' : 'Component'],
      display: s.length > 1 ? s : partName(s), properties: { id: s } });
    return id;
  };
  shown.forEach((t, k) => {
    const from = addState(t.from_parts);
    const rs = t.results_in || [];
    const singles = rs.filter(r => r.length === 1);
    const multis = rs.filter(r => r.length > 1);
    if (rs.length === 2 && singles.length === 1) {
      const survivor = addState(multis[0] || singles[1] || singles[0]);
      edges.push({ source: from, target: survivor, type: 'REMOVES',
                   label: `− ${partName(singles[0])}`,
                   properties: { transition_id: t.id, removed_part: partName(singles[0]) } });
    } else {
      const tn = 'tr_' + (t.id || k);
      nodes.set(tn, { id: tn, labels: ['Transition'], display: t.id || 'T', properties: { id: t.id } });
      edges.push({ source: from, target: tn, type: 'TRANSFORMS', properties: {} });
      rs.forEach(r => edges.push({ source: tn, target: addState(r), type: 'RESULTS_IN', properties: {} }));
    }
  });

  host.innerHTML = '';
  _stCy = cytoscape({ container: host, style: cyStyle(), wheelSensitivity: 0.3 });
  renderGraph(_stCy, { nodes: [...nodes.values()], edges }, 'precedence');
  initGraphTooltips(_stCy);
}

function _stDownloadJson() {
  const payload = _stBuildPayloadPreview();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  a.download = (ST.product.id || 'product') + '.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

function _stBuildPayloadPreview() {
  if (ST.imported) {
    return { ...ST.importData,
             product: { ...(ST.importData.product || {}), id: ST.product.id, name: ST.product.name } };
  }
  const components = ST.labels.map((lbl, i) => ({
    partId: _stL(i), name: _stPartName(i),
    type: ST.fasteners.includes(i) ? 'Fastener' : 'Part',
  }));
  const groups = ST.groups.filter(g => g.accepted).map(g => ({ name: g.name, members: g.members.slice() }));
  return {
    product: { id: ST.product.id, name: ST.product.name },
    components,
    connections: ST.phase2?.connections || [],
    transitions: ST.phase2?.transitions || [],
    ...(groups.length ? { fastener_groups: groups } : {}),
    // one disassembly task per bundle (a screw group or a multi-part screwed
    // joint); without it every member connection would get its own task
    ...(Object.keys(ST.phase2?.connection_bundles || {}).length
      ? { connection_bundles: ST.phase2.connection_bundles } : {}),
  };
}

/* onExisting: undefined → check whether the product ID is taken and ask in the
 * page (native confirm() dialogs are suppressed in some embedded browsers);
 * 'replace' → delete the existing product after validation, then build. */
async function _stBuild(onExisting) {
  if (_stIsStale() || !ST.phase2?.success) return;
  const name = (ST.product.name || '').trim();
  const pid = (ST.product.id || '').trim();
  const msg = $('st-build-msg');
  if (!name || !pid) { toast('Product name and ID are required.'); return; }

  const payload = _stBuildPayloadPreview();

  const btn = $('st-build-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spin" style="width:0.9rem;height:0.9rem;border-width:2px"></span> Building…';
  try {
    // The structural stage deletes the product-scoped graph of an existing id
    // before it writes the new one, so building onto an existing id replaces
    // that product, including properties added later. Make it an explicit decision.
    if (!onExisting) {
      try {
        const existing = await (await fetch(API.products())).json();
        if ((existing || []).some(p => p.id === pid)) {
          msg.innerHTML = `<div class="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
            A product with ID <b class="font-mono">${esc(pid)}</b> already exists. Building replaces it, including any properties added to it later.
            Change the product ID above, or:
            <div class="mt-2 flex gap-2">
              <button onclick="_stBuild('replace')" class="btn btn-accent text-xs">Replace the existing product</button>
            </div></div>`;
          return;
        }
      } catch (e) { /* collision check is best-effort */ }
    }
    msg.innerHTML = '';
    const vResp = await fetch(API.validate(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const v = await vResp.json();
    if (v && v.valid === false) {
      msg.innerHTML = `<div class="text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2"><b>Validation failed:</b><ul class="list-disc pl-4 mt-1">${(v.errors || []).map(e => `<li>${esc(e)}</li>`).join('')}</ul></div>`;
      return;
    }
    if (onExisting === 'replace') {
      const dResp = await fetch(API.product(pid), { method: 'DELETE' });
      if (!dResp.ok) {
        const d = await dResp.json().catch(() => ({}));
        msg.innerHTML = `<div class="text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">Could not delete the existing product: ${esc(d.error || dResp.statusText)}</div>`;
        return;
      }
    }
    const bResp = await fetch(API.products(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const b = await bResp.json();
    if (!bResp.ok) {
      msg.innerHTML = `<div class="text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">${esc(b.error || 'Build failed')}${b.details ? `<ul class="list-disc pl-4 mt-1">${b.details.map(d => `<li>${esc(d)}</li>`).join('')}</ul>` : ''}</div>`;
      return;
    }
    sessionStorage.removeItem(_ST_STORE);
    toast('Knowledge graph built.');
    go('#/product/' + encodeURIComponent(b.product_id || pid));
  } catch (e) {
    msg.innerHTML = `<div class="text-xs text-red-600">Build failed: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.innerHTML = '<i data-lucide="database" class="w-4 h-4"></i> Build knowledge graph';
    lucide.createIcons();
    _stStaleUI();
  }
}
