/* ── Cytoscape graph renderer ─────────────────────────────────────────────── */

/* Color map by node label */
const LABEL_COLORS = {
  Product:          { bg: '#0E2841', text: '#fff', shape: 'star' },
  Assembly:         { bg: '#156082', text: '#fff', shape: 'round-rectangle' },
  Component:        { bg: '#E97132', text: '#fff', shape: 'round-rectangle' },
  Fastener:         { bg: '#D4540F', text: '#fff', shape: 'diamond' },
  Connection:       { bg: '#888888', text: '#fff', shape: 'ellipse' },
  ConnectionType:   { bg: '#0E6B7A', text: '#fff', shape: 'round-rectangle' },
  Transition:       { bg: '#A855F7', text: '#fff', shape: 'round-rectangle' },
  DisassemblyTask:  { bg: '#7C3AED', text: '#fff', shape: 'round-rectangle' },
  AssemblyTask:     { bg: '#2563EB', text: '#fff', shape: 'round-rectangle' },
  Task:             { bg: '#6D28D9', text: '#fff', shape: 'round-rectangle' },
  DisassemblySkill: { bg: '#06B6D4', text: '#000', shape: 'ellipse' },
  AssemblySkill:    { bg: '#22D3EE', text: '#000', shape: 'ellipse' },
  Skill:            { bg: '#14B8A6', text: '#000', shape: 'ellipse' },
  Agent:            { bg: '#16A34A', text: '#fff', shape: 'ellipse' },
  Tool:             { bg: '#0D9488', text: '#fff', shape: 'diamond' },
};

/* Color per relationship type. Grouped by
 * meaning: structure=slate, connectivity=teal, state-graph=violet, task=indigo,
 * resources=green/cyan. REMOVES is the synthetic
 * condensed-transition edge (view-only, models/product.py condense_transitions). */
const EDGE_COLORS = {
  CONSISTS_OF:     '#94a3b8',
  CONNECTS:        '#0E6B7A',
  OF_TYPE:         '#5eead4',
  USES_FASTENER:   '#D4540F',
  TRANSFORMS:      '#c4b5fd',
  RESULTS_IN:      '#a78bfa',   // dashed → marks AND-arcs (one transition, several results)
  REMOVES:         '#7c3aed',
  DISASSEMBLED_BY: '#818cf8',
  ACTS_ON:         '#6366f1',
  REQUIRES:        '#22d3ee',
  PERFORMED_BY:    '#4ade80',
  USES_TOOL:       '#2dd4bf',
  SUITABLE_FOR:    '#67e8f9',
};
const _EDGE_COLOR_DEFAULT = '#cbd5e1';

/* Reversibility view: transitions/REMOVES edges are colored by how destructive
 * separating the underlying connection is (green = re-assemblable). */
const DESTRUCTIVENESS_COLORS = {
  'Non-destructive':  '#16A34A',
  'Semi-destructive': '#D97706',
  'Destructive':      '#DC2626',
};

/* Determine primary label from multi-label array */
function primaryLabel(labels) {
  // Prefer specific over generic
  const priority = ['Fastener', 'DisassemblyTask', 'AssemblyTask', 'DisassemblySkill',
                    'AssemblySkill', 'Product', 'Assembly', 'Component', 'Connection',
                    'ConnectionType', 'Transition', 'Task', 'Skill', 'Agent', 'Tool'];
  for (const p of priority) {
    if (labels.includes(p)) return p;
  }
  return labels[0] || 'unknown';
}

/* Layout algorithm per view type.
 *
 * - precedence/reversibility: layered DAG (dagre, top-down) — the backend flips
 *   TRANSFORMS edges so the larger assembly sits ABOVE its transitions and the
 *   single parts end up in the bottom ranks (natural disassembly flow).
 * - tasks/full/resources/library/rag: force layout — arbitrary or fan-in
 *   topology where a rank layout degenerates into a line.
 * - structure/connections: concentric rings around the product / connections.
 * - rag: layout for chat-answer subgraphs (arbitrary shape, never rank-ordered).
 */
const _COSE = { name: 'cose', animate: false, padding: 30, nodeRepulsion: 9000,
                idealEdgeLength: 60, componentSpacing: 100, nodeOverlap: 24,
                gravity: 0.3, numIter: 1200, randomize: false };
// fcose (vendored) — better force layout than the built-in cose; the layout
// fallback in renderGraph reverts to _COSE if the extension failed to load.
const _FCOSE = { name: 'fcose', quality: 'proof', animate: false, padding: 30,
                 nodeRepulsion: 12000, idealEdgeLength: 70, nodeSeparation: 90,
                 packComponents: true, randomize: true };
const _DAGRE_TB = { name: 'dagre', rankDir: 'TB', rankSep: 70, nodeSep: 18, edgeSep: 10 };
const VIEW_LAYOUTS = {
  full:           _FCOSE,
  reversibility:  _DAGRE_TB,
  structure:      { name: 'concentric', minNodeSpacing: 40, concentric: n => n.data('label') === 'Product' ? 3 : n.data('label') === 'Assembly' ? 2 : 1, levelWidth: () => 1 },
  connections:    { name: 'concentric', minNodeSpacing: 40, concentric: n => n.data('label') === 'Connection' ? 2 : 1, levelWidth: () => 1 },
  precedence:     _DAGRE_TB,
  // tasks: 114 transitions fan into 6 tasks — dagre stacks the transition rank
  // into a 3000px line, so this view stays force-directed.
  tasks:          _FCOSE,
  resources:      _FCOSE,
  library:        Object.assign({}, _FCOSE, { idealEdgeLength: 100 }),
  rag:            _FCOSE,
};

/**
 * Render graph data {nodes, edges} into a Cytoscape instance.
 * @param {Object} cy - Cytoscape instance
 * @param {Object} data - {nodes: [{id, labels, display, properties}], edges: [{source, target, type}]}
 * @param {string} viewType - layout key
 */
function renderGraph(cy, data, viewType) {
  cy.elements().remove();
  _clearLegend(cy);
  if (!data || !data.nodes || data.nodes.length === 0) return;

  // Add nodes — size tiers give visual hierarchy (Product > root Assembly > rest);
  // Transition nodes render compact (small dot, label only when zoomed in) so the
  // state graph reads as assemblies-connected-by-steps instead of a label soup.
  for (const n of data.nodes) {
    const lbl = primaryLabel(n.labels || []);
    const colors = LABEL_COLORS[lbl] || { bg: '#999', text: '#fff', shape: 'ellipse' };
    const full = String(n.display || n.properties?.name || n.properties?.id || n.id);
    const short = full.length > 22 ? full.slice(0, 21) + '…' : full;
    const isRoot = n.properties?.isRoot === true || n.properties?.isRoot === 'true';
    let pad = 11, fs = 11;
    if (lbl === 'Product') { pad = 16; fs = 13; }
    else if (lbl === 'Assembly' && isRoot) { pad = 14; fs = 12; }
    let bg = colors.bg;
    if (viewType === 'reversibility' && lbl === 'Transition') {
      bg = DESTRUCTIVENESS_COLORS[n.properties?.destructiveness] || '#64748b';
    }
    const el = cy.add({
      group: 'nodes',
      data: {
        id: n.id,
        label: lbl,
        display: short,     // truncated for on-node rendering
        full: full,         // full name (tooltip / detail panel)
        properties: n.properties || {},
        bgColor: bg,
        textColor: colors.text,
        nodeShape: colors.shape,
        pad: pad + 'px',
        fs: fs + 'px',
      }
    });
    if (lbl === 'Transition') el.addClass('kg-compact');
  }

  // Add edges (type = relationship type; label may differ, e.g. REMOVES edges
  // carry "− <part>" from the condensed precedence mode)
  for (const e of data.edges) {
    // Only add if both source and target exist
    if (cy.getElementById(e.source).length && cy.getElementById(e.target).length) {
      let ec = EDGE_COLORS[e.type] || _EDGE_COLOR_DEFAULT;
      if (viewType === 'reversibility' && e.type === 'REMOVES') {
        ec = DESTRUCTIVENESS_COLORS[e.properties?.destructiveness] || '#64748b';
      }
      cy.add({
        group: 'edges',
        data: {
          source: e.source,
          target: e.target,
          type: e.type || '',
          label: e.label || e.type || '',
          properties: e.properties || {},
          edgeColor: ec,
          dashed: e.type === 'RESULTS_IN' ? 1 : 0,
        }
      });
    }
  }

  // Apply layout — a missing/broken layout extension must never blank the
  // graph, so fall back to the built-in cose on any failure.
  const layout = VIEW_LAYOUTS[viewType] || VIEW_LAYOUTS.full;
  try {
    cy.layout({ ...layout, animate: false, fit: true, padding: 40 }).run();
  } catch (err) {
    console.warn(`layout '${layout.name}' failed (${err}); falling back to cose`);
    cy.layout({ ..._COSE, animate: false, fit: true, padding: 40 }).run();
  }

  // Legend overlay (node types present in this view)
  renderLegend(cy, data, viewType);
}

/* Remove the legend overlay from a graph container. */
function _clearLegend(cy) {
  const host = cy && cy.container && cy.container();
  if (!host) return;
  const old = host.querySelector('.kg-legend');
  if (old) old.remove();
}

/**
 * Render a clickable legend of the node types present in `data`, as an overlay
 * inside the Cytoscape container. Clicking a type dims/restores its nodes;
 * clicking the title collapses the legend. Uses the .kg-legend* classes from
 * static/css/app.css.
 */
function renderLegend(cy, data, viewType) {
  const host = cy && cy.container && cy.container();
  if (!host) return;
  _clearLegend(cy);
  if (getComputedStyle(host).position === 'static') host.style.position = 'relative';

  const present = [];
  const seen = new Set();
  for (const n of (data.nodes || [])) {
    const lbl = primaryLabel(n.labels || []);
    if (!seen.has(lbl)) { seen.add(lbl); present.push(lbl); }
  }
  if (!present.length) return;

  const legend = document.createElement('div');
  legend.className = 'kg-legend';
  legend.setAttribute('role', 'group');
  legend.setAttribute('aria-label', 'Graph legend');

  const title = document.createElement('div');
  title.className = 'kg-legend-title';
  const caret = document.createElement('span');
  caret.textContent = '–';
  title.append(Object.assign(document.createElement('span'), { textContent: 'Legend' }), caret);
  legend.appendChild(title);

  const body = document.createElement('div');
  body.className = 'kg-legend-body';
  for (const lbl of present) {
    const c = LABEL_COLORS[lbl] || { bg: '#999' };
    const item = document.createElement('div');
    item.className = 'kg-legend-item';
    item.setAttribute('role', 'button');
    item.setAttribute('tabindex', '0');
    item.title = 'Click to hide/show nodes of this type';
    const sw = document.createElement('span');
    sw.className = 'kg-legend-swatch';
    sw.style.background = c.bg;
    item.append(sw, Object.assign(document.createElement('span'), { textContent: lbl }));
    const toggle = () => {
      const dim = !item.classList.contains('is-dimmed');
      item.classList.toggle('is-dimmed', dim);
      cy.nodes().filter(n => n.data('label') === lbl).toggleClass('kg-faded', dim);
    };
    item.addEventListener('click', toggle);
    item.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
    body.appendChild(item);
  }

  // Reversibility section: what the green/amber/red coloring means. Click dims
  // all transitions/REMOVES edges with that rating.
  if (viewType === 'reversibility') {
    const sep = document.createElement('div');
    sep.className = 'kg-legend-sep';
    body.appendChild(sep);
    for (const [d, col] of Object.entries(DESTRUCTIVENESS_COLORS)) {
      const item = document.createElement('div');
      item.className = 'kg-legend-item';
      item.setAttribute('role', 'button');
      item.setAttribute('tabindex', '0');
      item.title = 'Click to hide/show this destructiveness rating';
      const sw = document.createElement('span');
      sw.className = 'kg-legend-swatch';
      sw.style.background = col;
      item.append(sw, Object.assign(document.createElement('span'), { textContent: d }));
      const toggle = () => {
        const dim = !item.classList.contains('is-dimmed');
        item.classList.toggle('is-dimmed', dim);
        cy.elements().filter(el => (el.data('properties') || {}).destructiveness === d)
          .toggleClass('kg-faded', dim);
      };
      item.addEventListener('click', toggle);
      item.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
      body.appendChild(item);
    }
  }

  // Relationship-type section (line swatches, same click-to-dim behaviour)
  const edgeTypes = [];
  const seenE = new Set();
  for (const e of (data.edges || [])) {
    if (e.type && !seenE.has(e.type)) { seenE.add(e.type); edgeTypes.push(e.type); }
  }
  if (edgeTypes.length) {
    const sep = document.createElement('div');
    sep.className = 'kg-legend-sep';
    body.appendChild(sep);
    for (const t of edgeTypes) {
      const item = document.createElement('div');
      item.className = 'kg-legend-item';
      item.setAttribute('role', 'button');
      item.setAttribute('tabindex', '0');
      item.title = 'Click to hide/show edges of this type';
      const sw = document.createElement('span');
      sw.className = 'kg-legend-line';
      sw.style.background = EDGE_COLORS[t] || _EDGE_COLOR_DEFAULT;
      item.append(sw, Object.assign(document.createElement('span'), { textContent: t }));
      const toggle = () => {
        const dim = !item.classList.contains('is-dimmed');
        item.classList.toggle('is-dimmed', dim);
        cy.edges().filter(e => e.data('type') === t).toggleClass('kg-faded', dim);
      };
      item.addEventListener('click', toggle);
      item.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
      body.appendChild(item);
    }
  }
  legend.appendChild(body);

  title.addEventListener('click', () => {
    const collapsed = body.style.display === 'none';
    body.style.display = collapsed ? '' : 'none';
    caret.textContent = collapsed ? '–' : '+';
  });

  host.appendChild(legend);
}

/**
 * Search/filter: dim graph nodes whose display name or type does not match the
 * query (and edges not touching a match); matches get a highlight border. An
 * empty query restores everything.
 */
function filterGraphNodes(cy, query) {
  if (!cy) return;
  const q = (query || '').trim().toLowerCase();
  cy.batch(() => {
    if (!q) {
      cy.elements().removeClass('kg-search-dim kg-search-hit');
      return;
    }
    cy.nodes().forEach((n) => {
      const hit = String(n.data('display') || '').toLowerCase().includes(q)
               || String(n.data('label') || '').toLowerCase().includes(q);
      n.toggleClass('kg-search-hit', hit);
      n.toggleClass('kg-search-dim', !hit);
    });
    cy.edges().forEach((e) => {
      const keep = e.source().hasClass('kg-search-hit') || e.target().hasClass('kg-search-hit');
      e.toggleClass('kg-search-dim', !keep);
    });
  });
}

/* Plain-language explanation per relationship type — shown in tooltips and the
 * edge detail panels. REMOVES is the synthetic condensed-transition edge. */
const EDGE_META = {
  CONSISTS_OF:     { label: 'consists of',      explain: 'Structural containment: the product or assembly state is made up of this part.' },
  CONNECTS:        { label: 'connects',          explain: 'This connection physically joins the two components.' },
  OF_TYPE:         { label: 'of type',           explain: 'Categorizes the connection (screw joint, press fit, …) — the type defines how destructive separation is.' },
  USES_FASTENER:   { label: 'uses fastener',     explain: 'The connection is held by this fastener (e.g. a screw).' },
  TRANSFORMS:      { label: 'transforms',        explain: 'Disassembly step: this transition takes the larger assembly state apart.' },
  RESULTS_IN:      { label: 'results in',        explain: 'Output of the transition. Several dashed arrows from one transition appear together (AND) — alternatives branch from the state itself (OR).' },
  REMOVES:         { label: 'removes',           explain: 'Condensed disassembly step: performing it removes the named part from the assembly state.' },
  DISASSEMBLED_BY: { label: 'disassembled by',   explain: 'The work instruction (task) that executes this transition.' },
  ACTS_ON:         { label: 'acts on',           explain: 'The connection this task separates.' },
  REQUIRES:        { label: 'requires',          explain: 'The skill needed to perform this task.' },
  PERFORMED_BY:    { label: 'performed by',      explain: 'The agent assigned to carry out this task.' },
  USES_TOOL:       { label: 'uses tool',         explain: 'The tool assigned to this task.' },
  SUITABLE_FOR:    { label: 'suitable for',      explain: 'This skill can separate connections of this type.' },
};

/**
 * Human-readable summary of an edge for tooltips / detail panels:
 * {type, color, title ("Source → Target"), explain, extra ([{k,v}] rows)}.
 */
function edgeSummary(edge) {
  const type = edge.data('type') || edge.data('label') || '';
  const meta = EDGE_META[type] || {};
  const src = edge.source(), tgt = edge.target();
  const sName = src.data('full') || src.data('display') || '';
  const tName = tgt.data('full') || tgt.data('display') || '';
  const extra = [];
  if (type === 'OF_TYPE') {
    const d = tgt.data('properties')?.destructiveness;
    if (d) extra.push({ k: 'Destructiveness', v: d });
  }
  if (type === 'TRANSFORMS' || type === 'RESULTS_IN') {
    const trans = (src.data('label') === 'Transition' ? src : tgt);
    if (trans.data('label') === 'Transition') extra.push({ k: 'Transition', v: trans.data('full') });
  }
  const props = edge.data('properties') || {};
  if (type === 'REMOVES') {
    if (props.removed_part) extra.push({ k: 'Removed part', v: props.removed_part });
    if (props.transition_name) extra.push({ k: 'Transition', v: props.transition_name });
    if (props.destructiveness) extra.push({ k: 'Destructiveness', v: props.destructiveness });
  } else {
    for (const [k, v] of Object.entries(props)) extra.push({ k, v });
  }
  return {
    type,
    color: EDGE_COLORS[type] || _EDGE_COLOR_DEFAULT,
    title: `${sName} → ${tName}`,
    explain: meta.explain || '',
    extra,
  };
}

/**
 * Lightweight hover tooltips for nodes and edges — one absolutely-positioned
 * div inside the cy container, no extension dependencies. Shows the full node
 * name (labels are truncated on-node) resp. the edge type + explanation.
 */
function initGraphTooltips(cy) {
  const host = cy && cy.container && cy.container();
  if (!host || host.querySelector('.kg-tooltip')) return;
  if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
  const tip = document.createElement('div');
  tip.className = 'kg-tooltip';
  tip.style.display = 'none';
  host.appendChild(tip);

  const show = (html, pos) => {
    tip.innerHTML = html;
    tip.style.display = 'block';
    const w = tip.offsetWidth, hw = host.clientWidth;
    let x = pos.x + 12, y = pos.y + 12;
    if (x + w > hw - 8) x = Math.max(8, pos.x - w - 12);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  };
  const hide = () => { tip.style.display = 'none'; };
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  cy.on('mouseover', 'node', (e) => {
    const n = e.target;
    const name = n.data('full') || n.data('display') || '';
    show(`<b>${esc(name)}</b><span class="kg-tooltip-type">${esc(n.data('label') || '')}</span>`,
         n.renderedPosition());
  });
  cy.on('mouseover', 'edge', (e) => {
    const s = edgeSummary(e.target);
    show(`<b style="color:${s.color}">${esc(s.type)}</b><br>${esc(s.title)}` +
         (s.explain ? `<div class="kg-tooltip-explain">${esc(s.explain)}</div>` : ''),
         e.target.renderedMidpoint());
  });
  cy.on('mouseout', 'node edge', hide);
  cy.on('pan zoom drag tap', hide);
}

/* Highlight a node and its immediate neighbourhood, dim the rest. */
function highlightNeighborhood(cy, node) {
  if (!cy || !node) return;
  const hood = node.closedNeighborhood();
  cy.batch(() => {
    cy.elements().addClass('kg-search-dim').removeClass('kg-search-hit');
    hood.removeClass('kg-search-dim');
    node.addClass('kg-search-hit');
  });
}

/* Clear any neighbourhood / search highlight. */
function clearHighlight(cy) {
  if (cy) cy.elements().removeClass('kg-search-dim kg-search-hit');
}

/* Build default Cytoscape style sheet */
function cyStyle() {
  return [
    {
      selector: 'node',
      style: {
        'label': 'data(display)',
        'background-color': 'data(bgColor)',
        'color': 'data(textColor)',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': 'data(fs)',
        'font-weight': 600,
        'font-family': 'Inter, Calibri, Arial, sans-serif',
        'width': 'label',
        'height': 'label',
        'padding': 'data(pad)',
        'shape': 'data(nodeShape)',
        'text-wrap': 'ellipsis',
        'text-max-width': '110px',
        'min-zoomed-font-size': 6,
        'border-width': 0,
      }
    },
    {
      // Compact rendering for Transition nodes: small fixed dot, name below the
      // node and only visible once zoomed in (tooltip/detail carry it otherwise).
      selector: 'node.kg-compact',
      style: {
        'width': 16,
        'height': 16,
        'padding': '2px',
        'text-valign': 'bottom',
        'text-margin-y': 3,
        'color': '#475569',
        'font-size': '9px',
        'font-weight': 400,
        'min-zoomed-font-size': 10,
        'text-outline-width': 2,
        'text-outline-color': '#ffffff',
      }
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 3,
        'border-color': '#E97132',
      }
    },
    {
      selector: '.kg-faded',
      style: { 'opacity': 0.12 },
    },
    {
      selector: '.kg-search-dim',
      style: { 'opacity': 0.08 },
    },
    {
      selector: 'node.kg-search-hit',
      style: { 'border-width': 3, 'border-color': '#E97132' },
    },
    {
      selector: 'edge',
      style: {
        'label': 'data(label)',
        'width': 1.5,
        'line-color': 'data(edgeColor)',
        'target-arrow-color': 'data(edgeColor)',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.9,
        'curve-style': 'bezier',
        'font-size': '9px',
        'font-family': 'Inter, Calibri, Arial, sans-serif',
        'color': '#475569',
        'text-outline-width': 2,
        'text-outline-color': '#ffffff',
        'text-rotation': 'autorotate',
        'text-margin-y': -8,
        'min-zoomed-font-size': 7,
      }
    },
    {
      // AND-arc marker: several RESULTS_IN edges leaving one transition mean
      // "these parts appear together" — dashed to distinguish from OR branching.
      selector: 'edge[dashed = 1]',
      style: { 'line-style': 'dashed', 'line-dash-pattern': [6, 3] },
    },
    {
      selector: 'edge[type = "REMOVES"]',
      style: { 'width': 2.2, 'font-weight': 600 },
    },
  ];
}
