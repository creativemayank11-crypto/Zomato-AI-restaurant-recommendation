/**
 * Doom AI Concierge — frontend logic.
 * Talks to the FastAPI backend: /health, /api/v1/meta/options, /api/v1/recommend
 */

document.addEventListener('DOMContentLoaded', () => {
  // ── Constants ─────────────────────────────────────────────────────────────
  const MAX_NOTES = 300;
  const CITYWIDE_VALUE = 'Bangalore';
  const DEFAULT_LOCATION = 'Indiranagar';
  const DEFAULT_NOTES = 'Cozy candlelit dinner, romantic outdoor ambience with authentic Italian pasta';
  const FALLBACK_CUISINES = ['North Indian', 'Chinese', 'South Indian', 'Italian', 'Continental', 'Fast Food',
    'Cafe', 'Biryani', 'Desserts', 'Street Food', 'Asian', 'Bakery'];
  const TIER_NAMES = { low: 'Modest', medium: 'Imperial', high: 'Sovereign' };

  // ── State ─────────────────────────────────────────────────────────────────
  let selectedCuisines = new Set();
  let availableLocalities = [];
  let availableCuisines = [];
  let totalRestaurants = null;
  let inFlight = false;

  // ── DOM ───────────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const statusText = $('status-text');
  const statusDot = $('status-dot');
  const statusPing = $('status-ping');
  const modelBadge = $('model-badge');
  const locationSelect = $('location-select');
  const localityCount = $('locality-count');
  const cuisineChipsContainer = $('cuisine-chips');
  const selectedCuisinesCount = $('selected-cuisines-count');
  const budgetCards = document.querySelectorAll('.budget-card');
  const ratingSlider = $('min-rating-slider');
  const ratingPreview = $('rating-val');
  const userNotesTextarea = $('user-notes');
  const charCount = $('char-count');
  const maxRecsSelect = $('max-recs-select');
  const recForm = $('recommendation-form');
  const searchBtn = $('search-btn');
  const resetBtn = $('reset-btn');
  const resetChipsBtn = $('reset-chips-btn');
  const resultsPanel = $('results-panel');

  const states = {
    empty: $('empty-state'),
    loading: $('loading-state'),
    error: $('error-state'),
    noMatches: $('no-matches-state'),
    results: $('results-state'),
  };
  const errorTitle = $('error-title');
  const errorMessage = $('error-message');
  const btnRetry = $('btn-retry');
  const btnRelax = $('btn-relax');
  const relaxedBanner = $('relaxed-banner');
  const relaxedMessage = $('relaxed-message');
  const relaxedDismiss = $('relaxed-dismiss');
  const telemetryCandidates = $('telemetry-candidates');
  const telemetryTime = $('telemetry-time');
  const querySummaryText = $('query-summary-text');
  const queryMetaText = $('query-meta-text');
  const cardsContainer = $('cards-container');
  const loadingTotal = $('loading-total');
  const loadingProvider = $('loading-provider');

  // ── Helpers ───────────────────────────────────────────────────────────────
  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function titleCase(s) {
    return String(s).replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function showState(name) {
    Object.entries(states).forEach(([key, el]) => el.classList.toggle('hidden', key !== name));
    resultsPanel.setAttribute('aria-busy', name === 'loading' ? 'true' : 'false');
  }

  function setLoading(isLoading) {
    inFlight = isLoading;
    searchBtn.disabled = isLoading;
    searchBtn.querySelector('.btn-text').textContent = isLoading ? 'Executing Decree…' : 'Mandate Recommendations';
    searchBtn.querySelector('.btn-icon').classList.toggle('hidden', isLoading);
    searchBtn.querySelector('.btn-spinner').classList.toggle('hidden', !isLoading);
  }

  function setStatus(online, text) {
    statusText.textContent = text;
    const ok = ['bg-[#059669]', 'shadow-[0_0_8px_#10B981]'];
    const bad = ['bg-red-500', 'shadow-[0_0_8px_#ef4444]'];
    statusDot.classList.remove(...(online ? bad : ok));
    statusDot.classList.add(...(online ? ok : bad));
    statusPing.classList.toggle('hidden', !online);
  }

  function updateCharCount() {
    charCount.textContent = `${userNotesTextarea.value.length} / ${MAX_NOTES}`;
  }

  function updateRatingPreview() {
    ratingPreview.textContent = `${parseFloat(ratingSlider.value).toFixed(1)}+`;
  }

  function setBudget(tier) {
    budgetCards.forEach((card) => {
      const isActive = card.dataset.tier === tier;
      card.classList.toggle('active', isActive);
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = isActive;
    });
  }

  // ── 1. Health & metadata ──────────────────────────────────────────────────
  async function initEngine() {
    try {
      const healthRes = await fetch('/health');
      if (!healthRes.ok) throw new Error(`HTTP ${healthRes.status}`);
      const health = await healthRes.json();
      totalRestaurants = health.total_restaurants;
      const provider = (health.llm_provider || 'groq').toUpperCase();
      setStatus(health.dataset_loaded, health.dataset_loaded
        ? `SOVEREIGN NETWORK • ${totalRestaurants.toLocaleString('en-IN')} VERIFIED VENUES`
        : 'DEGRADED • DATASET NOT LOADED');
      modelBadge.textContent = provider;
      loadingProvider.textContent = provider;
      loadingTotal.textContent = totalRestaurants.toLocaleString('en-IN');
    } catch (e) {
      console.warn('Health check failed:', e);
      setStatus(false, 'ENGINE OFFLINE');
      modelBadge.textContent = 'OFFLINE';
    }

    try {
      const metaRes = await fetch('/api/v1/meta/options');
      if (!metaRes.ok) throw new Error(`HTTP ${metaRes.status}`);
      const meta = await metaRes.json();
      availableLocalities = meta.localities || [];
      availableCuisines = meta.cuisines || [];
    } catch (e) {
      console.warn('Failed to load metadata options:', e);
      availableCuisines = FALLBACK_CUISINES;
    }
    populateLocationDropdown(availableLocalities);
    renderCuisineChips(availableCuisines);
  }

  function populateLocationDropdown(localities) {
    const current = locationSelect.value;
    const fallback = localities.includes(DEFAULT_LOCATION) ? DEFAULT_LOCATION : (localities[0] || CITYWIDE_VALUE);
    const target = (current === CITYWIDE_VALUE || localities.includes(current)) ? current : fallback;

    locationSelect.innerHTML = '';
    const cityOpt = document.createElement('option');
    cityOpt.value = CITYWIDE_VALUE;
    cityOpt.textContent = 'All Bangalore (Citywide)';
    locationSelect.appendChild(cityOpt);

    if (localities.length) {
      const group = document.createElement('optgroup');
      group.label = `Localities (${localities.length})`;
      localities.forEach((loc) => {
        const opt = document.createElement('option');
        opt.value = loc;
        opt.textContent = loc;
        group.appendChild(opt);
      });
      locationSelect.appendChild(group);
      localityCount.textContent = `${localities.length} SECTORS`;
    } else {
      // Keep the default locality selectable even if metadata failed to load
      const opt = document.createElement('option');
      opt.value = DEFAULT_LOCATION;
      opt.textContent = DEFAULT_LOCATION;
      locationSelect.appendChild(opt);
    }
    locationSelect.value = target;
  }

  // ── 2. Cuisine chips ──────────────────────────────────────────────────────
  function renderCuisineChips(cuisines) {
    cuisineChipsContainer.innerHTML = '';

    const allChip = document.createElement('button');
    allChip.type = 'button';
    allChip.className = 'cuisine-chip all-cuisines-chip';
    allChip.textContent = 'All Cuisines';
    allChip.addEventListener('click', clearCuisines);
    cuisineChipsContainer.appendChild(allChip);

    cuisines.forEach((cuisine) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'cuisine-chip';
      chip.dataset.cuisine = cuisine;
      chip.textContent = cuisine;
      chip.addEventListener('click', () => toggleCuisine(cuisine));
      cuisineChipsContainer.appendChild(chip);
    });
    syncCuisineChips();
  }

  function toggleCuisine(cuisine) {
    if (selectedCuisines.has(cuisine)) selectedCuisines.delete(cuisine);
    else selectedCuisines.add(cuisine);
    syncCuisineChips();
  }

  function clearCuisines() {
    selectedCuisines.clear();
    syncCuisineChips();
    cuisineChipsContainer.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function syncCuisineChips() {
    cuisineChipsContainer.querySelectorAll('.cuisine-chip').forEach((chip) => {
      const isAll = chip.classList.contains('all-cuisines-chip');
      const selected = isAll ? selectedCuisines.size === 0 : selectedCuisines.has(chip.dataset.cuisine);
      chip.classList.toggle('selected', selected);
      chip.setAttribute('aria-pressed', String(selected));
    });
    selectedCuisinesCount.textContent = selectedCuisines.size === 0
      ? 'Optional — All cuisines'
      : `${selectedCuisines.size} selected`;
  }

  // ── 3. Form controls ──────────────────────────────────────────────────────
  budgetCards.forEach((card) => {
    const radio = card.querySelector('input[type="radio"]');
    radio.addEventListener('change', () => setBudget(card.dataset.tier));
  });
  ratingSlider.addEventListener('input', updateRatingPreview);
  userNotesTextarea.addEventListener('input', updateCharCount);
  resetChipsBtn.addEventListener('click', clearCuisines);
  relaxedDismiss.addEventListener('click', () => {
    relaxedBanner.classList.add('hidden');
    relaxedBanner.classList.remove('flex');
  });

  // ── 4. Presets ────────────────────────────────────────────────────────────
  const PRESETS = {
    'preset-student': {
      location: 'BTM', cuisines: ['Fast Food', 'Street Food'], budget: 'low', rating: 3.5, count: '5',
      notes: 'Quick student bite, pocket-friendly, fast turnaround between classes',
    },
    'preset-romantic': {
      location: 'Indiranagar', cuisines: ['Italian', 'Continental'], budget: 'medium', rating: 4.0, count: '5',
      notes: 'Cozy romantic candlelit date night, authentic wood-fired pasta, serene ambiance',
    },
    'preset-family': {
      location: 'Koramangala', cuisines: ['North Indian'], budget: 'medium', rating: 4.0, count: '5',
      notes: 'Family weekend dinner, comfortable spacious seating, rich curries and breads for 4 people',
    },
  };

  Object.entries(PRESETS).forEach(([id, preset]) => {
    $(id).addEventListener('click', () => applyPreset(preset));
  });

  function applyPreset(preset) {
    if ([...locationSelect.options].some((o) => o.value === preset.location)) {
      locationSelect.value = preset.location;
    }
    selectedCuisines = new Set(preset.cuisines);
    syncCuisineChips();
    setBudget(preset.budget);
    ratingSlider.value = preset.rating;
    updateRatingPreview();
    userNotesTextarea.value = preset.notes;
    updateCharCount();
    maxRecsSelect.value = preset.count;
    executeRecommendationSearch();
  }

  // ── 5. Reset ──────────────────────────────────────────────────────────────
  resetBtn.addEventListener('click', () => {
    if ([...locationSelect.options].some((o) => o.value === DEFAULT_LOCATION)) {
      locationSelect.value = DEFAULT_LOCATION;
    }
    clearCuisines();
    setBudget('medium');
    ratingSlider.value = 3.8;
    updateRatingPreview();
    userNotesTextarea.value = DEFAULT_NOTES;
    updateCharCount();
    maxRecsSelect.value = '5';
    showState('empty');
  });

  // ── 6. Submit ─────────────────────────────────────────────────────────────
  recForm.addEventListener('submit', (e) => {
    e.preventDefault();
    executeRecommendationSearch();
  });
  btnRetry.addEventListener('click', executeRecommendationSearch);
  btnRelax.addEventListener('click', () => {
    ratingSlider.value = Math.max(1.0, parseFloat(ratingSlider.value) - 0.5).toFixed(1);
    updateRatingPreview();
    executeRecommendationSearch();
  });

  function buildPayload() {
    const budgetRadio = document.querySelector('input[name="budget_tier"]:checked');
    const notes = userNotesTextarea.value.trim().slice(0, MAX_NOTES);
    return {
      location: locationSelect.value,
      cuisines: Array.from(selectedCuisines),
      budget_tier: budgetRadio ? budgetRadio.value : 'medium',
      min_rating: parseFloat(ratingSlider.value),
      max_recommendations: parseInt(maxRecsSelect.value, 10),
      additional_notes: notes || undefined,
    };
  }

  async function executeRecommendationSearch() {
    if (inFlight) return;
    if (!locationSelect.value) {
      showError('Choose a Locality', 'Pick a locality (or All Bangalore) before generating recommendations.');
      return;
    }

    const payload = buildPayload();
    setLoading(true);
    showState('loading');
    if (window.matchMedia('(max-width: 1023px)').matches) {
      resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    const startTime = performance.now();

    try {
      const response = await fetch('/api/v1/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const serverTime = response.headers.get('X-Response-Time')
        || `${Math.round(performance.now() - startTime)}ms`;

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const detail = errorData.detail;
        // FastAPI validation errors (422) return detail as an array of {loc, msg}
        const validationMsg = Array.isArray(detail)
          ? detail.map((d) => `${(d.loc || []).slice(-1)[0] || 'input'}: ${d.msg}`).join('; ')
          : null;
        throw new Error(detail?.message || validationMsg || `Server returned HTTP ${response.status}`);
      }

      const data = await response.json();
      renderRecommendations(data, serverTime, payload);
    } catch (err) {
      console.error('Recommendation request failed:', err);
      showError('Protocol Interrupted', err.message || 'Unable to retrieve recommendations from the AI engine.');
    } finally {
      setLoading(false);
    }
  }

  function showError(title, message) {
    errorTitle.textContent = title;
    errorMessage.textContent = message;
    showState('error');
  }

  // ── 7. Render results ─────────────────────────────────────────────────────
  function renderRecommendations(data, serverTime, payload) {
    const recs = data.recommendations || [];

    if (recs.length === 0) {
      $('no-matches-location').textContent = payload.location === CITYWIDE_VALUE ? 'Bangalore' : payload.location;
      $('no-matches-rating').textContent = `${payload.min_rating.toFixed(1)}+ rating`;
      $('no-matches-budget').textContent = `${TIER_NAMES[payload.budget_tier] || payload.budget_tier} budget`;
      showState('noMatches');
      return;
    }

    if (data.relaxation_applied && data.relaxation_message) {
      relaxedMessage.textContent = data.relaxation_message;
      relaxedBanner.classList.remove('hidden');
      relaxedBanner.classList.add('flex');
    } else {
      relaxedBanner.classList.add('hidden');
      relaxedBanner.classList.remove('flex');
    }

    const candidates = data.total_candidates_analyzed || 0;
    telemetryCandidates.textContent = `${candidates} candidate${candidates === 1 ? '' : 's'} scrutinized`;
    telemetryTime.textContent = serverTime.replace(/ms$/, ' ms');

    querySummaryText.textContent = data.query_summary || 'Curated Recommendations';
    queryMetaText.textContent =
      `${recs.length} establishment${recs.length === 1 ? '' : 's'} verified • Grounded against ${candidates} shortlisted candidates`;

    cardsContainer.innerHTML = '';
    recs.forEach((rec, idx) => {
      const card = createRecommendationCard(rec, idx + 1);
      card.style.animationDelay = `${idx * 60}ms`;
      cardsContainer.appendChild(card);
    });
    showState('results');
  }

  const STAR_PATH = 'M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z';
  const SPARK_PATH = 'M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z';

  function ratingBadge(rating) {
    if (!rating) {
      return `<div class="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-[#182230] border border-[#3D5066] font-bold font-mono text-xs shrink-0" aria-label="New restaurant, no rating yet">
        <span class="text-[#10B981]">NEW</span></div>`;
    }
    let tone;
    if (rating >= 4.0) tone = 'bg-[#064E3B] border-[#10B981] text-[#34D399] shadow-[0_0_10px_rgba(16,185,129,0.3)]';
    else if (rating >= 3.5) tone = 'bg-[#78350F]/40 border-[#F59E0B]/50 text-[#FBBF24]';
    else tone = 'bg-red-950/50 border-red-500/50 text-red-300';
    return `<div class="flex items-center gap-1.5 px-3 py-1 rounded-lg border ${tone} font-bold font-mono text-xs shrink-0" aria-label="Rated ${rating.toFixed(1)} out of 5">
      <svg class="w-3.5 h-3.5 fill-current text-[#FBBF24]" viewBox="0 0 20 20" aria-hidden="true"><path d="${STAR_PATH}"></path></svg>
      <span>${rating.toFixed(1)}</span></div>`;
  }

  /** Split "₹1,200 (Medium)" into amount and tier name. */
  function parseCost(costStr) {
    const m = /^(.*?)\s*\((\w+)\)\s*$/.exec(costStr || '');
    if (!m) return { amount: costStr || '—', tier: '' };
    const tierKey = m[2].toLowerCase();
    return { amount: m[1], tier: TIER_NAMES[tierKey] || m[2] };
  }

  function createRecommendationCard(rec, rank) {
    const top = rank === 1;
    const card = document.createElement('article');
    card.className = top
      ? 'rec-card group bg-gradient-to-b from-[#182230] to-[#131B24] border-2 border-[#F59E0B] rounded-2xl p-5 sm:p-6 transition-all duration-200 shadow-xl shadow-[#059669]/10 hover:shadow-2xl hover:shadow-[#F59E0B]/20 hover:-translate-y-0.5 relative overflow-hidden ring-1 ring-[#F59E0B]/40'
      : 'rec-card group bg-[#131B24] hover:bg-[#182230] border border-[#2E3E50] hover:border-[#3D5066] rounded-2xl p-5 sm:p-6 transition-all duration-200 shadow-md hover:shadow-xl hover:-translate-y-0.5 relative';

    const rating = parseFloat(rec.rating) || 0;
    const cuisines = (rec.cuisine || '').split(',').map((c) => c.trim()).filter(Boolean);
    const pillBg = top ? 'bg-[#131B24]' : 'bg-[#0D131A]';
    const pills = cuisines
      .map((c) => `<span class="px-2.5 py-0.5 rounded-md ${pillBg} text-[#CBD5E1] text-[11px] font-mono border border-[#2E3E50]">${escapeHtml(titleCase(c))}</span>`)
      .join('');
    const { amount, tier } = parseCost(rec.estimated_cost_for_two);

    card.innerHTML = `
      ${top ? '<div class="absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl from-[#F59E0B]/10 via-[#10B981]/10 to-transparent pointer-events-none"></div>' : ''}
      <div class="flex items-start justify-between gap-3 mb-2.5 relative">
        <div class="flex items-start gap-3 min-w-0">
          <span class="${top
            ? 'bg-gradient-to-br from-[#F59E0B] to-[#D97706] text-[#070A0E] font-black shadow-lg shadow-[#F59E0B]/30 border-[#FDE68A]'
            : 'bg-[#182230] text-[#CBD5E1] font-bold border-[#2E3E50]'} w-8 h-8 rounded-lg font-cinzel text-xs flex items-center justify-center border shrink-0">#${rank}</span>
          <div class="min-w-0">
            <h4 class="font-cinzel text-base sm:text-lg font-bold text-[#F1F5F9] ${top ? 'group-hover:text-[#FBBF24]' : 'group-hover:text-[#34D399]'} transition-colors flex items-center gap-2 flex-wrap">
              <span class="break-words">${escapeHtml(rec.restaurant_name)}</span>
              ${top ? '<span class="text-[10px] font-mono tracking-widest text-[#F59E0B] uppercase px-1.5 py-0.5 rounded bg-[#070A0E] border border-[#F59E0B]/40">Premier Pick</span>' : ''}
            </h4>
            ${rec.locality ? `<span class="text-xs font-mono text-[#94A3B8]">${escapeHtml(rec.locality)}</span>` : ''}
          </div>
        </div>
        ${ratingBadge(rating)}
      </div>

      ${pills ? `<div class="flex flex-wrap items-center gap-1.5 mb-3.5 relative">${pills}</div>` : ''}

      <div class="${top
        ? 'p-4 bg-gradient-to-r from-[#064E3B]/40 via-[#131B24] to-[#182230] border-[#10B981]/50 shadow-inner'
        : 'p-3.5 bg-[#0D131A] border-[#2E3E50]'} rounded-xl border mb-3.5 relative">
        <div class="flex items-center gap-2 text-[11px] font-cinzel font-bold uppercase tracking-widest text-[#FBBF24] mb-1.5">
          <svg class="w-4 h-4 text-[#10B981]" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24" aria-hidden="true"><path d="${SPARK_PATH}" stroke-linecap="round" stroke-linejoin="round"></path></svg>
          Doom Sovereign Rationale
        </div>
        <p class="text-xs sm:text-sm ${top ? 'text-[#F1F5F9]' : 'text-[#CBD5E1]'} leading-relaxed">${escapeHtml(rec.recommendation_reason)}</p>
      </div>

      <div class="flex items-center justify-between gap-2 flex-wrap pt-2.5 border-t border-[#2E3E50] text-xs relative">
        <div class="flex items-center gap-1.5 text-[#CBD5E1] font-mono">
          <span class="text-[#94A3B8]">Treasury:</span>
          <span class="${top ? 'text-[#FBBF24] font-bold' : 'text-[#F1F5F9] font-semibold'}">${escapeHtml(amount)}</span>
          ${tier ? `<span class="text-[11px] text-[#94A3B8]">(${escapeHtml(tier)}${top ? ' Tier' : ''})</span>` : ''}
        </div>
        <div class="font-mono text-[11px] ${top ? 'text-[#10B981]' : 'text-[#94A3B8]'}">SECTOR_ID: ${escapeHtml(rec.restaurant_id)}</div>
      </div>`;
    return card;
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  updateCharCount();
  updateRatingPreview();
  showState('empty');
  initEngine();
});
