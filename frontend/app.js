/**
 * Sovereign AI Concierge — frontend logic.
 * Talks to the FastAPI backend: /health, /api/v1/meta/options, /api/v1/recommend,
 * /api/v1/top and /api/v1/feedback. Search state lives in the URL so results
 * can be shared, bookmarked and navigated with Back/Forward.
 */

document.addEventListener('DOMContentLoaded', () => {
  // ── Constants ─────────────────────────────────────────────────────────────
  const MAX_NOTES = 300;
  const CITYWIDE_LABEL = 'All Bangalore';
  const CITYWIDE_VALUE = 'Bangalore';
  const DEFAULTS = {
    location: 'Indiranagar', cuisines: [], budget: 'medium', rating: '3.5', notes: '',
    count: '5', bookTable: false, onlineOrder: false, diningType: '', strict: false,
  };
  const BUDGETS = ['low', 'medium', 'high'];
  const BUDGET_LABELS = { low: 'Low', medium: 'Medium', high: 'High' };
  const RATINGS = ['1.0', '3.5', '4.0', '4.5'];
  const FALLBACK_CUISINES = ['North Indian', 'Chinese', 'South Indian', 'Italian', 'Continental', 'Fast Food',
    'Cafe', 'Biryani', 'Desserts', 'Street Food', 'Asian', 'Bakery'];
  // Regional groups for the cuisine dropdown (names as they appear in the data).
  // Only cuisines actually present in /api/v1/meta/options are shown.
  const REGIONAL_CUISINES = {
    'North Indian': ['North Indian', 'Mughlai', 'Rajasthani', 'Kashmiri', 'Lucknowi', 'Awadhi', 'Bihari'],
    'South Indian': ['South Indian', 'Andhra', 'Kerala', 'Mangalorean', 'Hyderabadi', 'Chettinad', 'Tamil'],
  };
  const VIBE_EXAMPLES = ['Quiet place to talk', 'Rooftop with a view', 'Live music', 'Great for groups',
    'Kid-friendly', 'Quick lunch'];
  const STORAGE = { saved: 'sac:saved', recent: 'sac:recent' };

  // ── State ─────────────────────────────────────────────────────────────────
  let selectedCuisines = new Set();
  let localities = [];
  let allCuisines = [];
  let totalRestaurants = null;
  let inFlight = false;
  let lastState = null;
  let lastResults = [];
  let cooldownTimer = null;

  // ── DOM ───────────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const el = {
    statusText: $('status-text'), statusDot: $('status-dot'), statusPing: $('status-ping'), modelBadge: $('model-badge'),
    location: $('location-input'), localityCount: $('locality-count'),
    regionalCuisine: $('regional-cuisine'), cuisineSearch: $('cuisine-search'), cuisineChips: $('cuisine-chips'), cuisineCount: $('selected-cuisines-count'),
    resetChips: $('reset-chips-btn'), notes: $('user-notes'), charCount: $('char-count'), vibeExamples: $('vibe-examples'),
    count: $('max-recs-select'), bookTable: $('book-table'), onlineOrder: $('online-order'), diningType: $('dining-type'),
    form: $('recommendation-form'), reset: $('reset-btn'),
    searchButtons: [$('search-btn'), $('search-btn-mobile')],
    resultsPanel: $('results-panel'), consolePanel: $('console-panel'),
    filtersSummary: $('filters-summary'), filtersSummaryText: $('filters-summary-text'), filtersEdit: $('filters-edit'),
    errorTitle: $('error-title'), errorMessage: $('error-message'), retry: $('btn-retry'), relax: $('btn-relax'),
    noMatchesMessage: $('no-matches-message'),
    relaxedBanner: $('relaxed-banner'), relaxedSteps: $('relaxed-steps'), keepStrict: $('btn-keep-strict'),
    aiFallbackNote: $('ai-fallback-note'),
    summary: $('query-summary-text'), meta: $('query-meta-text'), cards: $('cards-container'),
    refineChips: $('refine-chips'), telemetryCandidates: $('telemetry-candidates'), telemetryTime: $('telemetry-time'),
    copyLink: $('copy-link'), copyLinkText: $('copy-link-text'), loadingTotal: $('loading-total'),
    topRatedArea: $('top-rated-area'), topRatedList: $('top-rated-list'),
    recentWrap: $('recent-searches-wrap'), recent: $('recent-searches'),
    savedToggle: $('saved-toggle'), savedCount: $('saved-count'), savedPanel: $('saved-panel'),
    savedList: $('saved-list'), savedClose: $('saved-close'), toast: $('toast'),
  };
  const states = {
    empty: $('empty-state'), loading: $('loading-state'), error: $('error-state'),
    noMatches: $('no-matches-state'), results: $('results-state'),
  };
  const isMobile = () => window.matchMedia('(max-width: 1023px)').matches;

  // ── Helpers ───────────────────────────────────────────────────────────────
  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  const titleCase = (s) => String(s).replace(/\b\w/g, (c) => c.toUpperCase());
  const formatInr = (n) => (typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : '');

  function storageGet(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (e) { return fallback; }
  }
  function storageSet(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode etc. */ }
  }

  let toastTimer = null;
  function toast(message) {
    el.toast.textContent = message;
    el.toast.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.toast.classList.add('hidden'), 2200);
  }

  function showState(name) {
    Object.entries(states).forEach(([key, node]) => node.classList.toggle('hidden', key !== name));
    el.resultsPanel.setAttribute('aria-busy', name === 'loading' ? 'true' : 'false');
  }

  function setLoading(isLoading) {
    inFlight = isLoading;
    el.searchButtons.forEach((btn) => {
      if (!btn) return;
      btn.disabled = isLoading || Boolean(cooldownTimer);
      btn.querySelector('.btn-text').textContent = isLoading ? 'Finding restaurants…' : 'Find restaurants';
      btn.querySelector('.btn-spinner').classList.toggle('hidden', !isLoading);
    });
  }

  function setStatus(online, text) {
    el.statusText.textContent = text;
    el.statusDot.classList.toggle('bg-[#22D3EE]', online);
    el.statusDot.classList.toggle('bg-red-500', !online);
    el.statusPing.classList.toggle('hidden', !online);
  }

  // ── Location handling ─────────────────────────────────────────────────────
  /** Resolve what the user typed to an API location value, or null if unknown. */
  function resolveLocation(text) {
    const t = String(text || '').trim().toLowerCase();
    if (!t) return null;
    if (t === CITYWIDE_LABEL.toLowerCase() || t === 'bangalore' || t === 'bengaluru') return CITYWIDE_VALUE;
    if (!localities.length) return text.trim(); // options not loaded: let the API decide
    return localities.find((l) => l.toLowerCase() === t)
      || localities.find((l) => l.toLowerCase().startsWith(t))
      || localities.find((l) => l.toLowerCase().includes(t))
      || null;
  }
  const locationLabel = (value) => (value === CITYWIDE_VALUE ? CITYWIDE_LABEL : value);

  // ── Form state <-> controls <-> URL ───────────────────────────────────────
  function readForm() {
    return {
      location: el.location.value.trim(),
      cuisines: Array.from(selectedCuisines),
      budget: document.querySelector('input[name="budget_tier"]:checked')?.value || DEFAULTS.budget,
      rating: document.querySelector('input[name="min_rating"]:checked')?.value || DEFAULTS.rating,
      notes: el.notes.value.trim().slice(0, MAX_NOTES),
      count: el.count.value,
      bookTable: el.bookTable.checked,
      onlineOrder: el.onlineOrder.checked,
      diningType: el.diningType.value,
      strict: lastState?.strict || false,
    };
  }

  function applyState(s) {
    setLocation(s.location || DEFAULTS.location);
    selectedCuisines = new Set(s.cuisines || []);
    renderCuisineChips();
    setRadio('budget_tier', BUDGETS.includes(s.budget) ? s.budget : DEFAULTS.budget, '.budget-card');
    setRadio('min_rating', RATINGS.includes(s.rating) ? s.rating : DEFAULTS.rating, '.rating-option');
    el.notes.value = (s.notes || '').slice(0, MAX_NOTES);
    updateCharCount();
    el.count.value = ['3', '5'].includes(String(s.count)) ? String(s.count) : DEFAULTS.count;
    el.bookTable.checked = Boolean(s.bookTable);
    el.onlineOrder.checked = Boolean(s.onlineOrder);
    syncToggleChips();
    if ([...el.diningType.options].some((o) => o.value === (s.diningType || ''))) el.diningType.value = s.diningType || '';
  }

  function setRadio(name, value, cardSelector) {
    document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
      input.checked = input.value === value;
      input.closest(cardSelector)?.classList.toggle('active', input.checked);
    });
  }

  function stateToQuery(s) {
    const p = new URLSearchParams();
    p.set('loc', s.location);
    if (s.cuisines.length) p.set('c', s.cuisines.join(','));
    p.set('b', s.budget);
    p.set('r', s.rating);
    if (s.notes) p.set('n', s.notes);
    p.set('k', s.count);
    if (s.bookTable) p.set('bt', '1');
    if (s.onlineOrder) p.set('oo', '1');
    if (s.diningType) p.set('t', s.diningType);
    if (s.strict) p.set('s', '1');
    return p.toString();
  }

  function queryToState(search) {
    const p = new URLSearchParams(search);
    if (!p.get('loc')) return null;
    return {
      location: p.get('loc'),
      cuisines: (p.get('c') || '').split(',').map((x) => x.trim()).filter(Boolean).slice(0, 10),
      budget: p.get('b') || DEFAULTS.budget,
      rating: p.get('r') || DEFAULTS.rating,
      notes: (p.get('n') || '').slice(0, MAX_NOTES),
      count: p.get('k') || DEFAULTS.count,
      bookTable: p.get('bt') === '1',
      onlineOrder: p.get('oo') === '1',
      diningType: p.get('t') || '',
      strict: p.get('s') === '1',
    };
  }

  function describeState(s) {
    const parts = [locationLabel(s.location), BUDGET_LABELS[s.budget] + ' budget'];
    if (s.rating !== '1.0') parts.push(`${s.rating}+`);
    if (s.cuisines.length) parts.push(s.cuisines.slice(0, 2).join(', ') + (s.cuisines.length > 2 ? '…' : ''));
    if (s.bookTable) parts.push('table booking');
    if (s.diningType) parts.push(s.diningType);
    return parts.join(' · ');
  }

  // ── 1. Health & options ───────────────────────────────────────────────────
  async function initEngine() {
    try {
      const res = await fetch('/health');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const health = await res.json();
      totalRestaurants = health.total_restaurants;
      const compact = window.matchMedia('(max-width: 639px)').matches;
      setStatus(health.dataset_loaded, health.dataset_loaded
        ? (compact ? 'Online' : `Online · ${totalRestaurants.toLocaleString('en-IN')}`)
        : 'Degraded');
      el.statusText.title = `${totalRestaurants.toLocaleString('en-IN')} restaurants loaded`;
      el.modelBadge.textContent = (health.llm_provider || 'groq').toUpperCase();
      el.loadingTotal.textContent = totalRestaurants.toLocaleString('en-IN');
    } catch (e) {
      setStatus(false, 'Offline');
      el.modelBadge.textContent = 'OFFLINE';
    }

    try {
      const res = await fetch('/api/v1/meta/options');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const meta = await res.json();
      localities = meta.localities || [];
      allCuisines = meta.all_cuisines || meta.cuisines || [];
      (meta.dining_types || []).forEach((t) => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        el.diningType.appendChild(opt);
      });
    } catch (e) {
      allCuisines = FALLBACK_CUISINES;
    }
    populateAreaDropdown();
    el.localityCount.textContent = localities.length ? `${localities.length} areas` : '';
    renderCuisineChips();
  }

  /** Fill the Area dropdown: "All Bangalore" first, then every area A–Z. */
  function populateAreaDropdown() {
    const current = el.location.value || DEFAULTS.location;
    const areas = localities.length ? localities : [DEFAULTS.location];
    el.location.innerHTML = '';

    const city = document.createElement('option');
    city.value = CITYWIDE_VALUE;
    city.textContent = `${CITYWIDE_LABEL} (citywide)`;
    el.location.appendChild(city);

    const group = document.createElement('optgroup');
    group.label = `Areas (${areas.length})`;
    areas.forEach((area) => {
      const opt = document.createElement('option');
      opt.value = area;
      opt.textContent = area;
      group.appendChild(opt);
    });
    el.location.appendChild(group);
    setLocation(current);
  }

  /** Select the dropdown option matching a location (falls back to the default area). */
  function setLocation(value) {
    const resolved = resolveLocation(value) || DEFAULTS.location;
    const exists = [...el.location.options].some((o) => o.value === resolved);
    el.location.value = exists ? resolved : DEFAULTS.location;
  }

  // ── 2. Cuisine chips with search ──────────────────────────────────────────
  function renderCuisineChips() {
    const query = el.cuisineSearch.value.trim().toLowerCase();
    const pool = allCuisines.length ? allCuisines : FALLBACK_CUISINES;
    const selected = pool.filter((c) => selectedCuisines.has(c));
    // Keep selections from URLs/presets visible even if not in the option list
    selectedCuisines.forEach((c) => { if (!selected.includes(c)) selected.push(c); });
    let rest = pool.filter((c) => !selectedCuisines.has(c));
    rest = query ? rest.filter((c) => c.toLowerCase().includes(query)) : rest.slice(0, 36);

    el.cuisineChips.innerHTML = '';
    const make = (label, isSelected, onClick, extraClass = '') => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `cuisine-chip ${extraClass}`.trim();
      chip.textContent = label;
      chip.classList.toggle('selected', isSelected);
      chip.setAttribute('aria-pressed', String(isSelected));
      chip.addEventListener('click', onClick);
      el.cuisineChips.appendChild(chip);
    };
    if (!query) make('Any cuisine', selectedCuisines.size === 0, clearCuisines, 'all-cuisines-chip');
    selected.forEach((c) => make(c, true, () => toggleCuisine(c)));
    rest.forEach((c) => make(c, false, () => toggleCuisine(c)));
    if (query && !rest.length && !selected.length) {
      el.cuisineChips.insertAdjacentHTML('beforeend', '<span class="text-xs text-[#64748B] p-1">No cuisine matches that search.</span>');
    }
    el.cuisineCount.textContent = selectedCuisines.size ? `${selectedCuisines.size} selected` : 'Any cuisine';
    renderRegionalDropdown();
  }

  function toggleCuisine(c) {
    if (selectedCuisines.has(c)) selectedCuisines.delete(c);
    else selectedCuisines.add(c);
    renderCuisineChips();
  }

  function clearCuisines() {
    selectedCuisines.clear();
    el.cuisineSearch.value = '';
    renderCuisineChips();
  }

  // ── 3. Other controls ─────────────────────────────────────────────────────
  function updateCharCount() {
    el.charCount.textContent = `${el.notes.value.length} / ${MAX_NOTES}`;
  }

  function syncToggleChips() {
    document.querySelectorAll('.toggle-chip').forEach((label) => {
      label.classList.toggle('active', label.querySelector('input').checked);
    });
  }

  function appendNote(text) {
    const current = el.notes.value.trim();
    if (current.toLowerCase().includes(text.toLowerCase())) return;
    el.notes.value = (current ? `${current}, ${text.toLowerCase()}` : text).slice(0, MAX_NOTES);
    updateCharCount();
  }

  document.querySelectorAll('input[name="budget_tier"]').forEach((input) =>
    input.addEventListener('change', () => setRadio('budget_tier', input.value, '.budget-card')));
  document.querySelectorAll('input[name="min_rating"]').forEach((input) =>
    input.addEventListener('change', () => setRadio('min_rating', input.value, '.rating-option')));
  [el.bookTable, el.onlineOrder].forEach((cb) => cb.addEventListener('change', syncToggleChips));
  el.notes.addEventListener('input', updateCharCount);
  el.cuisineSearch.addEventListener('input', renderCuisineChips);

  /** North / South Indian dropdown: picking a cuisine adds it to the selection. */
  function renderRegionalDropdown() {
    const available = new Set(allCuisines.length ? allCuisines : FALLBACK_CUISINES);
    const placeholder = el.regionalCuisine.options[0];
    el.regionalCuisine.innerHTML = '';
    el.regionalCuisine.appendChild(placeholder);
    Object.entries(REGIONAL_CUISINES).forEach(([region, names]) => {
      const present = names.filter((n) => available.has(n));
      if (!present.length) return;
      const group = document.createElement('optgroup');
      group.label = `${region} cuisines`;
      present.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = selectedCuisines.has(name) ? `✓ ${name} (selected)` : name;
        group.appendChild(opt);
      });
      el.regionalCuisine.appendChild(group);
    });
    el.regionalCuisine.value = '';
  }

  el.regionalCuisine.addEventListener('change', () => {
    const name = el.regionalCuisine.value;
    if (!name) return;
    if (selectedCuisines.has(name)) {
      toast(`${name} is already selected`);
    } else {
      selectedCuisines.add(name);
      toast(`Added ${name}`);
    }
    el.cuisineSearch.value = '';
    renderCuisineChips();
  });
  el.resetChips.addEventListener('click', clearCuisines);

  VIBE_EXAMPLES.forEach((text) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'vibe-chip';
    chip.textContent = `+ ${text}`;
    chip.addEventListener('click', () => appendNote(text));
    el.vibeExamples.appendChild(chip);
  });

  // Empty-state "Top rated in …" follows the chosen area
  el.location.addEventListener('change', () => {
    const loc = resolveLocation(el.location.value);
    if (loc && !states.empty.classList.contains('hidden')) loadTopRated(loc);
  });

  // ── 4. Presets ────────────────────────────────────────────────────────────
  const PRESETS = {
    'preset-student': {
      location: 'BTM', cuisines: ['Fast Food', 'Street Food'], budget: 'low', rating: '3.5', count: '5',
      notes: 'Quick student bite, pocket-friendly, fast service',
    },
    'preset-romantic': {
      location: 'Indiranagar', cuisines: ['Italian', 'Continental'], budget: 'medium', rating: '4.0', count: '5',
      bookTable: true, notes: 'Cozy romantic date night, candlelit, quiet enough to talk',
    },
    'preset-family': {
      location: 'Koramangala', cuisines: ['North Indian'], budget: 'medium', rating: '4.0', count: '5',
      notes: 'Family weekend dinner, spacious seating, rich curries for 4 people',
    },
  };
  Object.entries(PRESETS).forEach(([id, preset]) => {
    $(id).addEventListener('click', () => {
      applyState({ ...DEFAULTS, ...preset });
      runSearch({ ...DEFAULTS, ...preset });
    });
  });

  // ── 5. Reset ──────────────────────────────────────────────────────────────
  function resetAll() {
    applyState(DEFAULTS);
    lastState = null;
    el.cuisineSearch.value = '';
    renderCuisineChips();
    if (location.search) history.pushState(null, '', location.pathname);
    showEmpty();
  }
  el.reset.addEventListener('click', resetAll);

  // The emblem / title in the header doubles as a reset (no page reload).
  // Ctrl/Cmd/Shift/middle-click still follow the link normally (e.g. new tab).
  $('home-reset').addEventListener('click', (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (inFlight) return;
    resetAll();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    const emblem = e.currentTarget.querySelector('.emblem');
    emblem.classList.remove('emblem-spin');
    void emblem.offsetWidth; // restart the animation on repeated clicks
    emblem.classList.add('emblem-spin');
    toast('Filters reset');
  });

  // ── 6. Search ─────────────────────────────────────────────────────────────
  el.form.addEventListener('submit', (e) => {
    e.preventDefault();
    runSearch({ ...readForm(), strict: false });
  });
  el.retry.addEventListener('click', () => lastState && runSearch(lastState, { push: false }));
  el.keepStrict.addEventListener('click', () => lastState && runSearch({ ...lastState, strict: true }));
  el.relax.addEventListener('click', () => lastState && runSearch({ ...lastState, strict: false }));

  function buildPayload(s, apiLocation) {
    return {
      location: apiLocation,
      cuisines: s.cuisines,
      budget_tier: s.budget,
      min_rating: parseFloat(s.rating),
      max_recommendations: parseInt(s.count, 10),
      additional_notes: s.notes || undefined,
      book_table: s.bookTable,
      online_order: s.onlineOrder,
      dining_type: s.diningType || undefined,
      strict: s.strict,
    };
  }

  async function runSearch(s, { push = true } = {}) {
    if (inFlight || cooldownTimer) return;
    const apiLocation = resolveLocation(s.location);
    if (!apiLocation) {
      showError('Choose an area', `We couldn't find "${s.location}". Pick an area from the list, or "${CITYWIDE_LABEL}".`, false);
      el.location.focus();
      return;
    }
    s = { ...s, location: apiLocation };
    applyState(s);
    lastState = s;

    const query = stateToQuery(s);
    if (push && location.search.slice(1) !== query) history.pushState(s, '', `?${query}`);
    else history.replaceState(s, '', `?${query}`);

    setLoading(true);
    showState('loading');
    if (isMobile()) el.resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const startTime = performance.now();

    try {
      const response = await fetch('/api/v1/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload(s, apiLocation)),
      });
      const serverTime = response.headers.get('X-Response-Time') || `${Math.round(performance.now() - startTime)}ms`;

      if (response.status === 429) {
        const wait = parseInt(response.headers.get('Retry-After') || '30', 10);
        startCooldown(Number.isFinite(wait) ? wait : 30);
        return;
      }
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const detail = errorData.detail;
        const validationMsg = Array.isArray(detail)
          ? detail.map((d) => `${(d.loc || []).slice(-1)[0] || 'input'}: ${d.msg}`).join('; ')
          : null;
        const ref = detail?.request_id ? ` (reference ${detail.request_id})` : '';
        throw new Error((detail?.message || validationMsg || `Server returned HTTP ${response.status}`) + ref);
      }

      const data = await response.json();
      renderRecommendations(data, serverTime, s);
    } catch (err) {
      console.error('Recommendation request failed:', err);
      showError('Something went wrong', err.message || 'Unable to reach the recommendation engine.');
    } finally {
      setLoading(false);
    }
  }

  function showError(title, message, showRetry = true) {
    el.errorTitle.textContent = title;
    el.errorMessage.textContent = message;
    el.retry.classList.toggle('hidden', !showRetry);
    showState('error');
  }

  function startCooldown(seconds) {
    clearInterval(cooldownTimer);
    let remaining = Math.max(1, seconds);
    const tick = () => {
      el.errorMessage.textContent = `You've made a lot of searches in a short time. You can search again in ${remaining}s.`;
      el.retry.textContent = `Try again in ${remaining}s`;
      if (remaining <= 0) {
        clearInterval(cooldownTimer);
        cooldownTimer = null;
        el.retry.textContent = 'Try again';
        el.retry.disabled = false;
        el.errorMessage.textContent = 'Ready — you can search again now.';
        setLoading(false);
      }
      remaining -= 1;
    };
    showError('Slow down a little', '');
    el.retry.disabled = true;
    cooldownTimer = setInterval(tick, 1000);
    tick();
    setLoading(false);
  }

  // ── 7. Results ────────────────────────────────────────────────────────────
  function renderRecommendations(data, serverTime, s) {
    const recs = data.recommendations || [];
    lastResults = recs;

    if (recs.length === 0) {
      el.noMatchesMessage.textContent = s.strict
        ? `Nothing in ${locationLabel(s.location)} matches all of your filters exactly.`
        : 'Nothing matched these filters.';
      el.relax.classList.toggle('hidden', !s.strict);
      showState('noMatches');
      return;
    }

    const steps = data.relaxation_steps || [];
    el.relaxedBanner.classList.toggle('hidden', !(data.relaxation_applied && steps.length));
    el.relaxedSteps.innerHTML = steps.map((t) => `<span class="step-chip">${escapeHtml(t)}</span>`).join('');
    el.aiFallbackNote.classList.toggle('hidden', data.ai_generated !== false);

    el.summary.textContent = data.query_summary || 'Top recommendations';
    el.meta.textContent = `${recs.length} restaurant${recs.length === 1 ? '' : 's'} · ${describeState(s)}`;
    const n = data.total_candidates_analyzed || 0;
    el.telemetryCandidates.textContent = data.ai_generated
      ? `AI compared ${n} shortlisted restaurant${n === 1 ? '' : 's'}`
      : `Ranked ${n} shortlisted restaurant${n === 1 ? '' : 's'}`;
    el.telemetryTime.textContent = serverTime.replace(/ms$/, ' ms');

    el.cards.innerHTML = '';
    recs.forEach((rec, idx) => {
      const card = createRecommendationCard(rec, idx + 1, data.query_summary);
      card.style.animationDelay = `${idx * 50}ms`;
      el.cards.appendChild(card);
    });
    renderRefineChips(s, recs);
    showState('results');
    rememberSearch(s, data.query_summary);

    if (isMobile()) collapseFilters(s);
  }

  // ── Card rendering ────────────────────────────────────────────────────────
  const STAR_PATH = 'M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z';
  const ICONS = {
    glass: 'M8 3h8l-1 9a3 3 0 01-6 0L8 3zM12 15v6M9 21h6',
    cup: 'M4 8h12v5a5 5 0 01-5 5H9a5 5 0 01-5-5V8zm12 2h2a2 2 0 010 4h-2M7 3v2M11 3v2',
    slice: 'M12 3L3 19c6 2 12 2 18 0L12 3zM10 12h.01M14 15h.01M11 16h.01',
    bowl: 'M3 11h18a9 9 0 01-18 0zM9 7l2-4M14 7l3-4',
    cake: 'M4 21h16v-8H4v8zM4 13a4 4 0 018 0 4 4 0 018 0M12 4v4',
    burger: 'M4 11a8 6 0 0116 0H4zM3 14h18M5 17h14v1a2 2 0 01-2 2H7a2 2 0 01-2-2v-1z',
    pot: 'M5 10h14v4a6 6 0 01-6 6h-2a6 6 0 01-6-6v-4zM3 10h18M9 6c0-1 1-1 1-2M14 6c0-1 1-1 1-2',
    utensils: 'M7 3v8M5 3v4a2 2 0 004 0V3M7 11v10M17 3c-2 1-3 4-3 7h3v11',
  };
  function iconFor(rec) {
    const text = `${rec.cuisine || ''} ${rec.rest_type || ''}`.toLowerCase();
    const has = (...words) => words.some((w) => text.includes(w));
    if (has('bar', 'pub', 'brewery', 'lounge')) return ICONS.glass;
    if (has('cafe', 'coffee', 'tea', 'beverage', 'juice')) return ICONS.cup;
    if (has('pizza', 'italian')) return ICONS.slice;
    if (has('dessert', 'bakery', 'ice cream', 'mithai', 'sweet')) return ICONS.cake;
    if (has('burger', 'fast food', 'sandwich', 'roll')) return ICONS.burger;
    if (has('chinese', 'asian', 'thai', 'japanese', 'momo', 'korean', 'sushi')) return ICONS.bowl;
    if (has('indian', 'biryani', 'mughlai', 'kerala', 'andhra', 'chettinad', 'kebab')) return ICONS.pot;
    return ICONS.utensils;
  }

  function ratingBadge(rating) {
    if (!rating) {
      return '<span class="rating-badge rating-new" aria-label="New, not yet rated">NEW</span>';
    }
    const tone = rating >= 4.0 ? 'rating-high' : rating >= 3.5 ? 'rating-mid' : 'rating-low';
    return `<span class="rating-badge ${tone}" aria-label="Rated ${rating.toFixed(1)} out of 5">
      <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true"><path d="${STAR_PATH}"></path></svg>${rating.toFixed(1)}</span>`;
  }

  const safeZomatoUrl = (u) => (typeof u === 'string' && u.startsWith('https://www.zomato.com/') ? u : '');
  const telHref = (p) => (p ? `tel:${p.replace(/[^\d+]/g, '')}` : '');
  const mapsHref = (rec) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    `${rec.restaurant_name}, ${rec.address || rec.locality || ''}, Bangalore`)}`;

  function createRecommendationCard(rec, rank, querySummary) {
    const top = rank === 1;
    const card = document.createElement('article');
    card.className = `rec-card ${top ? 'rec-card-top' : ''}`;
    const rating = parseFloat(rec.rating) || 0;
    const cuisines = (rec.cuisine || '').split(',').map((c) => c.trim()).filter(Boolean).slice(0, 4);
    const tags = [];
    if (rec.book_table) tags.push('Table booking');
    if (rec.online_order) tags.push('Online order');
    (rec.dining_types || []).filter((t) => !['Delivery', 'Dine-out'].includes(t)).slice(0, 2).forEach((t) => tags.push(t));
    const cost = rec.cost_for_two ? `${formatInr(rec.cost_for_two)} for two` : (rec.estimated_cost_for_two || '');
    const metaParts = [rec.locality, rec.rest_type, cost].filter(Boolean).map(escapeHtml);
    const zomato = safeZomatoUrl(rec.zomato_url);
    const tel = telHref(rec.phone);
    const saved = isSaved(rec.restaurant_id);

    card.innerHTML = `
      <div class="flex items-start gap-3">
        <span class="card-icon ${top ? 'card-icon-top' : ''}" aria-hidden="true">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="${iconFor(rec)}"></path></svg>
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-start justify-between gap-3">
            <h4 class="min-w-0 break-words text-base sm:text-lg font-semibold text-[#F1F5F9] leading-snug">
              <span class="text-[#94A3B8] font-mono text-sm mr-1">#${rank}</span>${escapeHtml(rec.restaurant_name)}
              ${top ? '<span class="top-pick-pill">Top pick</span>' : ''}
            </h4>
            ${ratingBadge(rating)}
          </div>
          <p class="text-sm text-[#94A3B8] mt-0.5">${metaParts.join(' · ')}</p>
          <div class="flex flex-wrap gap-1.5 mt-2">
            ${cuisines.map((c) => `<span class="pill">${escapeHtml(titleCase(c))}</span>`).join('')}
            ${tags.map((t) => `<span class="pill pill-feature">${escapeHtml(t)}</span>`).join('')}
          </div>
        </div>
      </div>
      <div class="mt-3 pl-0 sm:pl-12 space-y-2">
        <p class="text-sm text-[#E2E8F0] leading-relaxed"><span class="why-label">Why it fits</span>${escapeHtml(rec.recommendation_reason)}</p>
        ${rec.review_snippet ? `<blockquote class="review-quote">“${escapeHtml(rec.review_snippet)}”<span class="block mt-1 not-italic text-[#64748B]">— a Zomato reviewer</span></blockquote>` : ''}
        <div class="flex flex-wrap items-center gap-2 pt-1">
          <a class="action-btn" href="${mapsHref(rec)}" target="_blank" rel="noopener noreferrer">Directions</a>
          ${tel ? `<a class="action-btn" href="${escapeHtml(tel)}">Call</a>` : ''}
          ${zomato ? `<a class="action-btn" href="${escapeHtml(zomato)}" target="_blank" rel="noopener noreferrer">View on Zomato</a>` : ''}
          <button type="button" class="action-btn save-btn ${saved ? 'is-saved' : ''}" data-id="${escapeHtml(rec.restaurant_id)}" aria-pressed="${saved}">${saved ? '★ Saved' : '☆ Save'}</button>
          <span class="ml-auto flex items-center gap-1" role="group" aria-label="Was this a good pick?">
            <button type="button" class="vote-btn" data-vote="up" aria-label="Good pick">👍</button>
            <button type="button" class="vote-btn" data-vote="down" aria-label="Not a good pick">👎</button>
          </span>
        </div>
      </div>`;

    card.querySelector('.save-btn').addEventListener('click', (e) => toggleSaved(rec, e.currentTarget));
    card.querySelectorAll('.vote-btn').forEach((btn) => btn.addEventListener('click', () => {
      sendFeedback(rec.restaurant_id, btn.dataset.vote, querySummary);
      card.querySelectorAll('.vote-btn').forEach((b) => {
        b.disabled = true;
        b.classList.toggle('voted', b === btn);
        b.setAttribute('aria-pressed', String(b === btn));
      });
      toast('Thanks for the feedback');
    }));
    return card;
  }

  function sendFeedback(restaurantId, vote, querySummary) {
    fetch('/api/v1/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ restaurant_id: restaurantId, vote, query_summary: (querySummary || '').slice(0, 300) }),
      keepalive: true,
    }).catch(() => { /* feedback is best-effort */ });
  }

  // ── Refine chips ──────────────────────────────────────────────────────────
  function renderRefineChips(s, recs) {
    const options = [];
    const bi = BUDGETS.indexOf(s.budget);
    if (bi > 0) options.push(['Cheaper', { budget: BUDGETS[bi - 1] }]);
    if (bi < BUDGETS.length - 1) options.push(['Fancier', { budget: BUDGETS[bi + 1] }]);
    const ri = RATINGS.indexOf(s.rating);
    if (ri < RATINGS.length - 1) options.push([`Rated ${RATINGS[ri + 1]}+`, { rating: RATINGS[ri + 1] }]);
    options.push(['Quieter', { notes: 'quiet and calm' }, true]);
    options.push(['Livelier', { notes: 'lively, buzzing atmosphere' }, true]);
    if (s.cuisines.length) options.push(['Any cuisine', { cuisines: [] }]);
    if (!s.bookTable) options.push(['Takes table bookings', { bookTable: true }]);
    if (recs[0]) options.push([`More like ${recs[0].restaurant_name}`, { notes: `similar vibe to ${recs[0].restaurant_name}` }, true]);

    el.refineChips.innerHTML = '';
    options.forEach(([label, change, isNote]) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'refine-chip';
      chip.textContent = label;
      chip.addEventListener('click', () => {
        const next = { ...s, ...change, strict: false };
        if (isNote) {
          const base = s.notes && !s.notes.toLowerCase().includes(change.notes) ? `${s.notes}, ` : '';
          next.notes = (s.notes?.toLowerCase().includes(change.notes) ? s.notes : base + change.notes).slice(0, MAX_NOTES);
        }
        runSearch(next);
      });
      el.refineChips.appendChild(chip);
    });
  }

  // ── Copy link ─────────────────────────────────────────────────────────────
  el.copyLink.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      toast('Link copied');
    } catch (e) {
      window.prompt('Copy this link:', location.href);
    }
  });

  // ── Saved places (localStorage) ───────────────────────────────────────────
  const getSaved = () => storageGet(STORAGE.saved, []);
  const isSaved = (id) => getSaved().some((r) => r.id === id);

  function toggleSaved(rec, button) {
    let saved = getSaved();
    if (saved.some((r) => r.id === rec.restaurant_id)) {
      saved = saved.filter((r) => r.id !== rec.restaurant_id);
      toast('Removed from saved');
    } else {
      saved.unshift({
        id: rec.restaurant_id, name: rec.restaurant_name, locality: rec.locality, rating: rec.rating,
        cost: rec.cost_for_two, url: safeZomatoUrl(rec.zomato_url), address: rec.address || '',
      });
      saved = saved.slice(0, 30);
      toast('Saved');
    }
    storageSet(STORAGE.saved, saved);
    const nowSaved = isSaved(rec.restaurant_id);
    button.classList.toggle('is-saved', nowSaved);
    button.setAttribute('aria-pressed', String(nowSaved));
    button.textContent = nowSaved ? '★ Saved' : '☆ Save';
    renderSaved();
  }

  function renderSaved() {
    const saved = getSaved();
    el.savedCount.textContent = String(saved.length);
    el.savedToggle.classList.toggle('hidden', saved.length === 0);
    el.savedToggle.classList.toggle('inline-flex', saved.length > 0);
    if (!saved.length) el.savedPanel.classList.add('hidden');
    el.savedList.innerHTML = saved.map((r) => `
      <li class="flex items-center justify-between gap-3 p-2.5 rounded-lg bg-[#0E0E11] border border-[#3A3A44]">
        <span class="min-w-0">
          <span class="block text-sm font-semibold text-[#F1F5F9] truncate">${escapeHtml(r.name)}</span>
          <span class="block text-xs text-[#94A3B8] truncate">${escapeHtml([r.locality, r.rating ? `${Number(r.rating).toFixed(1)}★` : '', r.cost ? `${formatInr(r.cost)} for two` : ''].filter(Boolean).join(' · '))}</span>
        </span>
        <span class="flex items-center gap-2 shrink-0">
          ${r.url ? `<a class="action-btn" href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">Zomato</a>` : ''}
          <button type="button" class="action-btn" data-remove="${escapeHtml(r.id)}" aria-label="Remove ${escapeHtml(r.name)} from saved">Remove</button>
        </span>
      </li>`).join('');
    el.savedList.querySelectorAll('[data-remove]').forEach((btn) => btn.addEventListener('click', () => {
      storageSet(STORAGE.saved, getSaved().filter((r) => r.id !== btn.dataset.remove));
      document.querySelectorAll(`.save-btn[data-id="${CSS.escape(btn.dataset.remove)}"]`).forEach((b) => {
        b.classList.remove('is-saved');
        b.setAttribute('aria-pressed', 'false');
        b.textContent = '☆ Save';
      });
      renderSaved();
    }));
  }

  el.savedToggle.addEventListener('click', () => {
    const open = el.savedPanel.classList.toggle('hidden') === false;
    el.savedToggle.setAttribute('aria-expanded', String(open));
    if (open) el.savedPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  el.savedClose.addEventListener('click', () => {
    el.savedPanel.classList.add('hidden');
    el.savedToggle.setAttribute('aria-expanded', 'false');
  });

  // ── Recent searches (localStorage) ────────────────────────────────────────
  function rememberSearch(s, summary) {
    const query = stateToQuery({ ...s, strict: false });
    const label = describeState(s);
    const recent = storageGet(STORAGE.recent, []).filter((r) => r.query !== query);
    recent.unshift({ query, label, summary: (summary || '').slice(0, 120) });
    storageSet(STORAGE.recent, recent.slice(0, 5));
  }

  function renderRecent() {
    const recent = storageGet(STORAGE.recent, []);
    el.recentWrap.classList.toggle('hidden', recent.length === 0);
    el.recent.innerHTML = '';
    recent.forEach((r) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'refine-chip';
      btn.textContent = r.label;
      btn.title = r.summary || r.label;
      btn.addEventListener('click', () => {
        const s = queryToState(r.query);
        if (s) runSearch(s);
      });
      el.recent.appendChild(btn);
    });
  }

  // ── Empty state: top rated in the chosen area (no AI call) ────────────────
  let topRatedRequest = 0;
  async function loadTopRated(loc) {
    const requestNo = ++topRatedRequest;
    el.topRatedArea.textContent = locationLabel(loc);
    try {
      const res = await fetch(`/api/v1/top?location=${encodeURIComponent(loc)}&limit=4`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (requestNo !== topRatedRequest) return; // a newer request superseded this one
      el.topRatedList.innerHTML = (data.restaurants || []).map((r) => {
        const zomato = safeZomatoUrl(r.zomato_url);
        return `<div class="p-3 rounded-xl bg-[#0E0E11] border border-[#3A3A44]">
          <div class="flex items-start justify-between gap-2">
            <span class="min-w-0 break-words text-sm font-semibold text-[#F1F5F9]">${escapeHtml(r.restaurant_name)}</span>
            ${ratingBadge(parseFloat(r.rating) || 0)}
          </div>
          <p class="text-xs text-[#94A3B8] mt-1">${escapeHtml([r.locality, r.rest_type, r.cost_for_two ? `${formatInr(r.cost_for_two)} for two` : ''].filter(Boolean).join(' · '))}</p>
          ${zomato ? `<a class="inline-block mt-2 text-xs text-[#F87171] hover:underline" href="${escapeHtml(zomato)}" target="_blank" rel="noopener noreferrer">View on Zomato</a>` : ''}
        </div>`;
      }).join('') || '<p class="text-sm text-[#94A3B8]">No restaurants found for this area.</p>';
    } catch (e) {
      if (requestNo === topRatedRequest) el.topRatedList.innerHTML = '<p class="text-sm text-[#94A3B8]">Top-rated list unavailable right now.</p>';
    }
  }

  function showEmpty() {
    renderRecent();
    const loc = resolveLocation(el.location.value) || DEFAULTS.location;
    loadTopRated(loc);
    expandFilters();
    showState('empty');
  }

  // ── Mobile: collapse filters into a summary bar after searching ───────────
  function collapseFilters(s) {
    el.filtersSummaryText.textContent = describeState(s);
    el.filtersSummary.classList.remove('hidden');
    el.filtersSummary.classList.add('flex');
    el.consolePanel.classList.add('hidden');
    el.filtersEdit.setAttribute('aria-expanded', 'false');
  }
  function expandFilters() {
    el.consolePanel.classList.remove('hidden');
    el.filtersSummary.classList.add('hidden');
    el.filtersSummary.classList.remove('flex');
    el.filtersEdit.setAttribute('aria-expanded', 'true');
  }
  el.filtersEdit.addEventListener('click', () => {
    expandFilters();
    el.consolePanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  window.matchMedia('(min-width: 1024px)').addEventListener('change', (e) => { if (e.matches) expandFilters(); });

  // ── History (Back / Forward) ──────────────────────────────────────────────
  window.addEventListener('popstate', () => {
    const s = queryToState(location.search);
    if (s) runSearch(s, { push: false });
    else { applyState(DEFAULTS); lastState = null; showEmpty(); }
  });

  // ── Init ──────────────────────────────────────────────────────────────────
  (async () => {
    applyState(DEFAULTS);
    renderSaved();
    showState('empty');
    await initEngine();
    const fromUrl = queryToState(location.search);
    if (fromUrl) {
      applyState(fromUrl);
      runSearch(fromUrl, { push: false });
    } else {
      showEmpty();
    }
  })();
});
