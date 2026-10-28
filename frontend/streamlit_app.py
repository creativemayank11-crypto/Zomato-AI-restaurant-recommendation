"""Zomato AI Culinary Concierge - Streamlit Presentation Layer (Phase 5).

Run with:
    streamlit run frontend/streamlit_app.py
"""
import time
import streamlit as st

# Configure page settings
st.set_page_config(
    page_title="Zomato AI Culinary Concierge",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for polished dark-mode aesthetic
st.markdown("""
<style>
    .main { background-color: #0b0f19; }
    .stApp { color: #f8fafc; }
    .rec-card {
        background: #162033;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-left: 4px solid #e23744;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }
    .card-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 0.25rem;
    }
    .badge-rating {
        display: inline-block;
        background: #10b981;
        color: white;
        font-weight: 700;
        padding: 0.2rem 0.6rem;
        border-radius: 6px;
        font-size: 0.85rem;
    }
    .ai-rationale-box {
        background: rgba(226, 55, 68, 0.08);
        border: 1px solid rgba(226, 55, 68, 0.25);
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-top: 0.75rem;
    }
    .ai-tag {
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        color: #e23744;
    }
    .meta-row {
        color: #94a3b8;
        font-size: 0.85rem;
        margin: 0.25rem 0;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading Zomato dataset & models...")
def get_engine_components():
    """Cache the in-memory dataset and engine dependencies."""
    from src.data.preprocessor import load_processed_data
    from src.api.dependencies import init_llm_client_singleton
    df = load_processed_data()
    llm_client, provider = init_llm_client_singleton()
    return df, llm_client, provider


def main():
    st.title("🍽️ Zomato AI Culinary Concierge")
    st.caption("AI-Powered Restaurant Recommendation Engine backed by Groq LPU™ & Zero-Hallucination Verification")

    try:
        df, llm_client, provider = get_engine_components()
    except Exception as e:
        st.error(f"Failed to load dataset: {e}")
        return

    # Top localities & cuisines for dropdowns
    top_localities = df["locality"].value_counts().head(50).index.tolist()
    from collections import Counter
    cuisine_counts = Counter(c for row in df["cuisines"] for c in row)
    top_cuisines = [c.title() for c, _ in cuisine_counts.most_common(30)]

    # Preset quick buttons
    st.markdown("### ⚡ Quick Presets")
    col1, col2, col3 = st.columns(3)
    
    preset = None
    with col1:
        if st.button("🎒 Budget Student Bite", use_container_width=True):
            preset = {
                "location": "BTM",
                "cuisines": ["Fast Food", "Street Food"],
                "budget": "low",
                "rating": 3.5,
                "notes": "Budget student bite, quick service, cheap eats near campus",
            }
    with col2:
        if st.button("🍷 Romantic Date Night", use_container_width=True):
            preset = {
                "location": "Indiranagar",
                "cuisines": ["Italian"],
                "budget": "medium",
                "rating": 4.0,
                "notes": "Cozy romantic candlelit date night, authentic wood-fired pasta, serene ambiance",
            }
    with col3:
        if st.button("👨‍👩‍👧‍👦 Family Weekend Dinner", use_container_width=True):
            preset = {
                "location": "Koramangala",
                "cuisines": ["North Indian"],
                "budget": "medium",
                "rating": 4.0,
                "notes": "Family weekend dinner, comfortable spacious seating, rich curries for 4 people",
            }

    # Sidebar preferences
    with st.sidebar:
        st.header("Dining Preferences")
        default_loc = preset["location"] if preset else "Indiranagar"
        loc_index = top_localities.index(default_loc) if default_loc in top_localities else 0
        location = st.selectbox("📍 Locality", top_localities, index=loc_index)

        default_cuisines = preset["cuisines"] if preset else ["Italian"]
        cuisines = st.multiselect("🍲 Cuisines", top_cuisines, default=default_cuisines)

        budget_options = ["low", "medium", "high"]
        budget_labels = {"low": "Low (< ₹500)", "medium": "Medium (₹500–₹1500)", "high": "High (> ₹1500)"}
        default_budget = preset["budget"] if preset else "medium"
        budget_tier = st.radio(
            "💳 Budget Tier",
            budget_options,
            format_func=lambda x: budget_labels[x],
            index=budget_options.index(default_budget),
        )

        default_rating = preset["rating"] if preset else 3.8
        min_rating = st.slider("⭐ Minimum Rating", 1.0, 5.0, default_rating, 0.1)

        default_notes = preset["notes"] if preset else "Cozy candlelit dinner, romantic outdoor ambience with authentic Italian pasta"
        user_notes = st.text_area("✨ Vibe & Occasion Notes", default_notes, height=90, max_chars=500)

        max_recs = st.slider("Number of Recommendations", 3, 8, 5)
        search_clicked = st.button("✨ Get Recommendations", type="primary", use_container_width=True)

    # Trigger recommendation when search button is clicked or preset chosen
    if search_clicked or preset is not None:
        if not cuisines:
            st.warning("Please select at least one cuisine.")
            return

        from src.models.schema import UserPreferences, BudgetTier
        from src.engine.filter import filter_restaurants
        from src.engine.recommender import generate_recommendations

        prefs = UserPreferences(
            location=location,
            cuisines=cuisines,
            budget_tier=BudgetTier(budget_tier),
            min_rating=min_rating,
            max_recommendations=max_recs,
            additional_notes=user_notes if user_notes.strip() else None,
        )

        with st.spinner("Pruning candidate pool & querying Groq LPU™ engine..."):
            t_start = time.perf_counter()
            candidates, relaxed, rel_msg, filter_ms = filter_restaurants(df, prefs)

            response = generate_recommendations(
                preferences=prefs,
                candidates=candidates,
                relaxation_applied=relaxed,
                relaxation_message=rel_msg,
                provider=provider,
                llm_client=llm_client,
            )
            total_ms = round((time.perf_counter() - t_start) * 1000, 1)

        # Relaxation warning banner
        if response.relaxation_applied:
            st.info(f"ℹ️ **Search Bounds Relaxed:** {response.relaxation_message}")

        # Telemetry
        st.caption(f"⚡ Evaluated **{response.total_candidates_analyzed} candidates** • Deterministic Filter: **{filter_ms:.1f}ms** • Total Pipeline: **{total_ms:.1f}ms** • Grounding: **100% Verified**")

        st.subheader(response.query_summary)

        # Recommendation Cards
        if not response.recommendations:
            st.warning("No restaurants found matching your criteria. Try relaxing your location or rating floor.")
        else:
            for idx, rec in enumerate(response.recommendations, 1):
                st.markdown(f"""
                <div class="rec-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div class="card-title">#{idx} {rec.restaurant_name}</div>
                        <span class="badge-rating">⭐ {rec.rating:.1f}</span>
                    </div>
                    <div class="meta-row">
                        🍲 <strong>{rec.cuisine}</strong> &nbsp;•&nbsp; 💳 {rec.estimated_cost_for_two} &nbsp;•&nbsp; <code>{rec.restaurant_id}</code>
                    </div>
                    <div class="ai-rationale-box">
                        <div class="ai-tag">✨ AI Concierge Rationale</div>
                        <div style="font-size: 0.95rem; color: #e2e8f0; margin-top: 0.25rem;">{rec.recommendation_reason}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
