/**
 * Zomato AI Culinary Concierge - Frontend Application Logic
 * Interacts with FastAPI backend: /health, /api/v1/meta/options, /api/v1/recommend
 */

document.addEventListener('DOMContentLoaded', () => {
  // ── State ─────────────────────────────────────────────────────────────────
  let selectedCuisines = new Set();
  let availableLocalities = [];
  let availableCuisines = [];

  // ── DOM References ────────────────────────────────────────────────────────
  const statusText = document.getElementById('status-text');
  const modelBadge = document.getElementById('model-badge');
  const locationSelect = document.getElementById('location-select');
  const cuisineChipsContainer = document.getElementById('cuisine-chips');
  const selectedCuisinesCount = document.getElementById('selected-cuisines-count');
  const budgetCards = document.querySelectorAll('.budget-card');
  const ratingSlider = document.getElementById('min-rating-slider');
  const ratingPreview = document.getElementById('rating-val');
  const userNotesTextarea = document.getElementById('user-notes');
  const charCount = document.getElementById('char-count');
  const maxRecsSelect = document.getElementById('max-recs-select');
  const recForm = document.getElementById('recommendation-form');
  const searchBtn = document.getElementById('search-btn');
  const resetBtn = document.getElementById('reset-btn');

  // Results elements
  const cardsContainer = document.getElementById('cards-container');
  const loadingState = document.getElementById('loading-state');
  const errorState = document.getElementById('error-state');
  const errorTitle = document.getElementById('error-title');
  const errorMessage = document.getElementById('error-message');
  const btnRetry = document.getElementById('btn-retry');
  const relaxedBanner = document.getElementById('relaxed-banner');
  const relaxedMessage = document.getElementById('relaxed-message');
  const telemetryBar = document.getElementById('telemetry-bar');
  const telemetryCandidates = document.getElementById('telemetry-candidates');
  const telemetryTime = document.getElementById('telemetry-time');
  const resultsHeader = document.getElementById('results-header');
  const querySummaryText = document.getElementById('query-summary-text');
  const queryMetaText = document.getElementById('query-meta-text');

  // Presets
  const presetStudent = document.getElementById('preset-student');
  const presetRomantic = document.getElementById('preset-romantic');
  const presetFamily = document.getElementById('preset-family');

  // ── 1. Fetch Backend Health & Meta Options ─────────────────────────────────
  async function initEngine() {
    try {
      const healthRes = await fetch('/health');
      if (healthRes.ok) {
        const health = await healthRes.json();
        statusText.textContent = `Online • ${health.total_restaurants.toLocaleString()} restaurants`;
        modelBadge.textContent = health.llm_provider ? `${health.llm_provider.toUpperCase()} LPU` : 'Groq LPU';
      }
    } catch (e) {
      statusText.textContent = 'Engine Offline (Demo Mode)';
      modelBadge.textContent = 'Degraded';
    }

    try {
      const metaRes = await fetch('/api/v1/meta/options');
      if (metaRes.ok) {
        const meta = await metaRes.json();
        availableLocalities = meta.localities || [];
        availableCuisines = meta.cuisines || [];
        populateLocationDropdown(availableLocalities);
        renderCuisineChips(availableCuisines);
      }
    } catch (e) {
      console.warn('Failed to load metadata options:', e);
      // Fallback default cuisines
      renderCuisineChips(['Italian', 'North Indian', 'Chinese', 'Continental', 'Fast Food', 'Cafe', 'Biryani', 'South Indian', 'Desserts', 'Street Food', 'Asian', 'Bakery']);
    }
  }

  function populateLocationDropdown(localities) {
    const currentVal = locationSelect.value;
    const defaultLoc = (currentVal && (localities.includes(currentVal) || currentVal === 'Bangalore')) 
      ? currentVal 
      : (localities.includes('Indiranagar') ? 'Indiranagar' : (localities[0] || 'Bangalore'));

    locationSelect.innerHTML = '';

    // Citywide option for comprehensive search
    const cityOpt = document.createElement('option');
    cityOpt.value = 'Bangalore';
    cityOpt.textContent = '📍 All Bangalore (Citywide)';
    if (defaultLoc === 'Bangalore') cityOpt.selected = true;
    locationSelect.appendChild(cityOpt);

    // Group for specific localities in dataset
    const optGroup = document.createElement('optgroup');
    optGroup.label = `Available Localities (${localities.length} Areas)`;

    localities.forEach((loc) => {
      const opt = document.createElement('option');
      opt.value = loc;
      opt.textContent = loc;
      if (loc === defaultLoc) opt.selected = true;
      optGroup.appendChild(opt);
    });
    locationSelect.appendChild(optGroup);

    locationSelect.value = defaultLoc;
  }

  function renderCuisineChips(cuisines) {
    cuisineChipsContainer.innerHTML = '';

    // "All Cuisines (Any)" chip for explicit zero-constraint selection
    const allChip = document.createElement('span');
    allChip.className = 'cuisine-chip all-cuisines-chip';
    allChip.textContent = '✨ All Cuisines';
    if (selectedCuisines.size === 0) {
      allChip.classList.add('selected');
    }
    allChip.addEventListener('click', () => {
      selectedCuisines.clear();
      document.querySelectorAll('.cuisine-chip').forEach(c => c.classList.remove('selected'));
      allChip.classList.add('selected');
      updateCuisineCount();
    });
    cuisineChipsContainer.appendChild(allChip);

    cuisines.forEach(cuisine => {
      const chip = document.createElement('span');
      chip.className = 'cuisine-chip';
      chip.textContent = cuisine;
      if (selectedCuisines.has(cuisine)) {
        chip.classList.add('selected');
      }
      chip.addEventListener('click', () => toggleCuisine(cuisine, chip));
      cuisineChipsContainer.appendChild(chip);
    });
    updateCuisineCount();
  }

  function toggleCuisine(cuisine, chipEl) {
    const allChip = cuisineChipsContainer.querySelector('.all-cuisines-chip');
    if (selectedCuisines.has(cuisine)) {
      selectedCuisines.delete(cuisine);
      chipEl.classList.remove('selected');
    } else {
      selectedCuisines.add(cuisine);
      chipEl.classList.add('selected');
      if (allChip) allChip.classList.remove('selected');
    }

    if (selectedCuisines.size === 0 && allChip) {
      allChip.classList.add('selected');
    }

    updateCuisineCount();
  }

  function updateCuisineCount() {
    const allChip = cuisineChipsContainer.querySelector('.all-cuisines-chip');
    if (selectedCuisines.size === 0) {
      selectedCuisinesCount.textContent = 'Optional — All cuisines';
      if (allChip) allChip.classList.add('selected');
    } else {
      selectedCuisinesCount.textContent = `${selectedCuisines.size} selected`;
      if (allChip) allChip.classList.remove('selected');
    }
  }

  // ── 2. Budget Tier Selection ──────────────────────────────────────────────
  budgetCards.forEach(card => {
    card.addEventListener('click', () => {
      budgetCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // ── 3. Slider Live Preview ────────────────────────────────────────────────
  ratingSlider.addEventListener('input', (e) => {
    ratingPreview.textContent = `${parseFloat(e.target.value).toFixed(1)}+`;
  });

  // ── 4. Character Counter ──────────────────────────────────────────────────
  userNotesTextarea.addEventListener('input', (e) => {
    charCount.textContent = e.target.value.length;
  });

  // ── 5. Persona Presets ────────────────────────────────────────────────────
  presetStudent.addEventListener('click', () => {
    applyPreset({
      location: 'BTM',
      cuisines: ['Fast Food', 'Street Food'],
      budget: 'low',
      rating: 3.5,
      notes: 'Quick student bite, pocket-friendly, fast turnaround between classes',
      count: '5'
    });
  });

  presetRomantic.addEventListener('click', () => {
    applyPreset({
      location: 'Indiranagar',
      cuisines: ['Italian', 'Continental'],
      budget: 'medium',
      rating: 4.0,
      notes: 'Cozy romantic candlelit date night, authentic wood-fired pasta, serene ambiance',
      count: '5'
    });
  });

  presetFamily.addEventListener('click', () => {
    applyPreset({
      location: 'Koramangala',
      cuisines: ['North Indian'],
      budget: 'medium',
      rating: 4.0,
      notes: 'Family weekend dinner, comfortable spacious seating, rich curries and breads for 4 people',
      count: '5'
    });
  });

  function applyPreset(preset) {
    locationSelect.value = preset.location;
    selectedCuisines = new Set(preset.cuisines);
    
    // Update chip styling
    document.querySelectorAll('.cuisine-chip').forEach(chip => {
      if (selectedCuisines.has(chip.textContent)) {
        chip.classList.add('selected');
      } else {
        chip.classList.remove('selected');
      }
    });
    updateCuisineCount();

    // Budget
    budgetCards.forEach(card => {
      const radio = card.querySelector('input');
      if (radio && radio.value === preset.budget) {
        card.classList.add('active');
        radio.checked = true;
      } else {
        card.classList.remove('active');
      }
    });

    // Rating
    ratingSlider.value = preset.rating;
    ratingPreview.textContent = `${preset.rating.toFixed(1)}+`;

    // Notes
    userNotesTextarea.value = preset.notes;
    charCount.textContent = preset.notes.length;

    // Count
    maxRecsSelect.value = preset.count;

    // Trigger immediate search
    recForm.dispatchEvent(new Event('submit'));
  }

  // ── 6. Form Reset ─────────────────────────────────────────────────────────
  resetBtn.addEventListener('click', () => {
    locationSelect.value = 'Indiranagar';
    selectedCuisines = new Set();
    renderCuisineChips(availableCuisines);
    ratingSlider.value = 3.8;
    ratingPreview.textContent = '3.8+';
    userNotesTextarea.value = 'Cozy candlelit dinner, romantic outdoor ambience with authentic Italian pasta';
    charCount.textContent = userNotesTextarea.value.length;
    budgetCards.forEach(c => {
      c.classList.toggle('active', c.dataset.tier === 'medium');
      const r = c.querySelector('input');
      if (r) r.checked = (c.dataset.tier === 'medium');
    });
  });

  // ── 7. Submit Recommendation Form ─────────────────────────────────────────
  recForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await executeRecommendationSearch();
  });

  btnRetry.addEventListener('click', async () => {
    await executeRecommendationSearch();
  });

  async function executeRecommendationSearch() {
    const locationVal = locationSelect.value;
    if (!locationVal) {
      alert('Please select a location or locality.');
      return;
    }

    const selectedBudgetRadio = document.querySelector('input[name="budget_tier"]:checked');
    const budgetVal = selectedBudgetRadio ? selectedBudgetRadio.value : 'medium';

    const payload = {
      location: locationVal,
      cuisines: selectedCuisines.size > 0 ? Array.from(selectedCuisines) : [],
      budget_tier: budgetVal,
      min_rating: parseFloat(ratingSlider.value),
      max_recommendations: parseInt(maxRecsSelect.value, 10),
      additional_notes: userNotesTextarea.value.trim() || undefined
    };

    // UI State: Loading
    searchBtn.disabled = true;
    searchBtn.querySelector('.btn-text').textContent = 'Consulting Concierge...';
    loadingState.style.display = 'flex';
    errorState.style.display = 'none';
    relaxedBanner.style.display = 'none';
    telemetryBar.style.display = 'none';
    resultsHeader.style.display = 'none';
    cardsContainer.innerHTML = '';

    const startTime = performance.now();

    try {
      const response = await fetch('/api/v1/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const serverTimeHeader = response.headers.get('X-Response-Time') || `${Math.round(performance.now() - startTime)}ms`;

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const detail = errorData.detail;
        // FastAPI validation errors (422) return detail as an array of {loc, msg}
        const validationMsg = Array.isArray(detail)
          ? detail.map(d => `${(d.loc || []).slice(-1)[0] || 'input'}: ${d.msg}`).join('; ')
          : null;
        throw new Error(detail?.message || validationMsg || `Server returned error HTTP ${response.status}`);
      }

      const data = await response.json();
      renderRecommendations(data, serverTimeHeader);

    } catch (err) {
      console.error('Recommendation request failed:', err);
      loadingState.style.display = 'none';
      errorState.style.display = 'flex';
      errorTitle.textContent = 'Recommendation Request Failed';
      errorMessage.textContent = err.message || 'Unable to retrieve recommendations from the AI engine.';
    } finally {
      searchBtn.disabled = false;
      searchBtn.querySelector('.btn-text').textContent = 'Generate Recommendations';
    }
  }

  // ── 8. Render Results ─────────────────────────────────────────────────────
  function renderRecommendations(data, serverTime) {
    loadingState.style.display = 'none';

    // 1. Check if recommendations exist
    if (!data.recommendations || data.recommendations.length === 0) {
      errorState.style.display = 'flex';
      errorTitle.textContent = 'No Matches Found';
      errorMessage.textContent = 'No restaurants satisfied both the geographic and dietary constraints. Try broadening the locality or lowering the minimum rating.';
      return;
    }

    // 2. Relaxation Banner
    if (data.relaxation_applied) {
      relaxedBanner.style.display = 'flex';
      if (data.relaxation_message) {
        relaxedMessage.textContent = data.relaxation_message;
      }
    } else {
      relaxedBanner.style.display = 'none';
    }

    // 3. Telemetry Bar
    telemetryBar.style.display = 'flex';
    telemetryCandidates.textContent = `${data.total_candidates_analyzed || 0} candidates analyzed`;
    telemetryTime.textContent = serverTime;

    // 4. Header
    resultsHeader.style.display = 'block';
    querySummaryText.textContent = data.query_summary || 'Curated Recommendations';
    queryMetaText.textContent = `${data.recommendations.length} restaurants verified by zero-hallucination guard`;

    // 5. Render Cards
    cardsContainer.innerHTML = '';
    data.recommendations.forEach((rec, idx) => {
      const card = createRecommendationCard(rec, idx + 1);
      cardsContainer.appendChild(card);
    });
  }

  function createRecommendationCard(rec, rank) {
    const card = document.createElement('article');
    card.className = 'rec-card';

    // Rating color classification
    const ratingNum = parseFloat(rec.rating) || 0;
    let ratingClass = 'rating-medium';
    if (ratingNum >= 4.0) ratingClass = 'rating-high';
    else if (ratingNum < 3.5) ratingClass = 'rating-low';

    // Cuisine tags
    const cuisineBadges = (rec.cuisine || '')
      .split(',')
      .map(c => `<span class="meta-pill meta-cuisine">${escapeHtml(c.trim())}</span>`)
      .join(' ');

    card.innerHTML = `
      <div class="card-top">
        <div class="card-name-group">
          <h4 class="restaurant-title">
            <span class="rank-index">#${rank}</span>
            ${escapeHtml(rec.restaurant_name)}
          </h4>
          <div class="restaurant-meta-row">
            ${cuisineBadges}
          </div>
        </div>
        <div class="rating-badge ${ratingClass}">
          <span>⭐</span>
          <span>${ratingNum ? ratingNum.toFixed(1) : 'NEW'}</span>
        </div>
      </div>

      <div class="ai-rationale-box">
        <span class="ai-spark-icon">✨</span>
        <div class="ai-rationale-content">
          <span class="ai-rationale-tag">AI Concierge Rationale</span>
          <p class="ai-rationale-text">${escapeHtml(rec.recommendation_reason)}</p>
        </div>
      </div>

      <div class="card-bottom">
        <div class="cost-info">
          <span>Cost for two:</span>
          <span class="cost-value">${escapeHtml(rec.estimated_cost_for_two || 'Moderate')}</span>
        </div>
        <div class="id-badge">ID: ${escapeHtml(rec.restaurant_id)}</div>
      </div>
    `;

    return card;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ── Initialize ────────────────────────────────────────────────────────────
  initEngine();
});
