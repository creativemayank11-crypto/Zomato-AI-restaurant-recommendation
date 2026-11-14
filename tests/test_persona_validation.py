"""Phase 5 Persona Validation & Frontend Integration Tests.

Validates:
1. Frontend static asset delivery (HTML, CSS, JS).
2. Persona 1: Budget Student Bite (Low budget, fast turnaround, quick bites).
3. Persona 2: Romantic Date Night (Medium/High budget, Italian, cozy ambiance).
4. Persona 3: Family Weekend Dinner (High rating 4.0+, North Indian, spacious).
5. Zero-hallucination verification asserting all recommended restaurants strictly
   exist in the preprocessed Parquet dataset.
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from src.data.preprocessor import load_processed_data


@pytest.fixture(scope="module")
def client():
    """Spin up the FastAPI TestClient with full lifespan context."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="module")
def dataset_df():
    """Load the ground-truth Parquet dataset for anti-hallucination verification."""
    return load_processed_data()


# ---------------------------------------------------------------------------
# 1. UI Assets & Entrypoint Tests
# ---------------------------------------------------------------------------

class TestUIEndpoints:
    def test_root_serves_html(self, client):
        """GET / should serve the Phase 5 HTML5 application."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "zomato" in response.text.lower()
        assert "ai concierge" in response.text.lower()

    def test_static_css_served(self, client):
        """GET /static/style.css should deliver the stylesheet."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ":root" in response.text
        assert "--brand-gold" in response.text

    def test_static_js_served(self, client):
        """GET /static/app.js should deliver the client logic."""
        response = client.get("/static/app.js")
        assert response.status_code == 200
        assert "DOMContentLoaded" in response.text
        assert "/api/v1/recommend" in response.text

    def test_static_tailwind_served(self, client):
        """GET /static/tailwind.css should deliver the precompiled utilities."""
        response = client.get("/static/tailwind.css")
        assert response.status_code == 200
        assert "font-cinzel" in response.text

    def test_non_public_frontend_files_not_served(self, client):
        """Only allow-listed assets are public; other files in frontend/ must 404."""
        for path in (
            "/static/streamlit_app.py",
            "/static/vercel.json",
            "/static/.vercelignore",
            "/static/index.html",
            "/static/../app.py",
            "/static/%2e%2e/app.py",
        ):
            assert client.get(path).status_code == 404, path


# ---------------------------------------------------------------------------
# 2. Persona 1: Budget Student Bite
# ---------------------------------------------------------------------------

class TestPersona1BudgetStudentBite:
    """Test Case 1: Budget Student Bite (BTM / Delhi alias, Low Budget, Fast Food)."""

    def test_student_bite_recommendation_flow(self, client, dataset_df):
        payload = {
            "location": "BTM",
            "cuisines": ["Fast Food", "Street Food"],
            "budget_tier": "low",
            "min_rating": 3.2,
            "max_recommendations": 3,
            "additional_notes": "Quick budget student bite between classes, pocket-friendly cheap eats",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert "query_summary" in data
        assert len(data["recommendations"]) > 0
        assert len(data["recommendations"]) <= 3

        valid_ids = set(dataset_df["restaurant_id"].astype(str))
        for rec in data["recommendations"]:
            assert rec["restaurant_id"] in valid_ids, f"Hallucinated ID: {rec['restaurant_id']}"
            assert len(rec["recommendation_reason"]) > 10
            assert rec["rating"] >= 3.0


# ---------------------------------------------------------------------------
# 3. Persona 2: Romantic Date Night
# ---------------------------------------------------------------------------

class TestPersona2RomanticDateNight:
    """Test Case 2: Romantic Date Night (Indiranagar, Medium Budget, Italian)."""

    def test_romantic_date_recommendation_flow(self, client, dataset_df):
        payload = {
            "location": "Indiranagar",
            "cuisines": ["Italian"],
            "budget_tier": "medium",
            "min_rating": 3.8,
            "max_recommendations": 4,
            "additional_notes": "Romantic cozy candlelit date night with authentic wood-fired pizza and wine",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert len(data["recommendations"]) > 0
        assert len(data["recommendations"]) <= 4

        valid_ids = set(dataset_df["restaurant_id"].astype(str))
        for rec in data["recommendations"]:
            assert rec["restaurant_id"] in valid_ids, f"Hallucinated ID: {rec['restaurant_id']}"
            assert len(rec["recommendation_reason"]) > 10
            assert rec["rating"] >= 3.5


# ---------------------------------------------------------------------------
# 4. Persona 3: Family Weekend Dinner
# ---------------------------------------------------------------------------

class TestPersona3FamilyWeekendDinner:
    """Test Case 3: Family Weekend Dinner (High rating 4.0+, North Indian)."""

    def test_family_dinner_recommendation_flow(self, client, dataset_df):
        payload = {
            "location": "Koramangala",
            "cuisines": ["North Indian"],
            "budget_tier": "medium",
            "min_rating": 4.0,
            "max_recommendations": 3,
            "additional_notes": "Family weekend dinner, comfortable spacious seating with vegetarian options for parents",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert len(data["recommendations"]) > 0

        valid_ids = set(dataset_df["restaurant_id"].astype(str))
        for rec in data["recommendations"]:
            assert rec["restaurant_id"] in valid_ids, f"Hallucinated ID: {rec['restaurant_id']}"
            assert len(rec["recommendation_reason"]) > 10


# ---------------------------------------------------------------------------
# 5. Strict Zero-Hallucination & Schema Integrity
# ---------------------------------------------------------------------------

class TestStrictZeroHallucination:
    """Rigorous verification that all recommended items match exact dataset attributes."""

    def test_zero_hallucination_integrity(self, client, dataset_df):
        dataset_lookup = dataset_df.set_index("restaurant_id").to_dict(orient="index")

        payload = {
            "location": "Whitefield",
            "cuisines": ["Chinese", "Continental"],
            "budget_tier": "medium",
            "min_rating": 3.5,
            "max_recommendations": 5,
            "additional_notes": "Team lunch celebration with outdoor seating",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200

        data = response.json()
        for rec in data["recommendations"]:
            rec_id = rec["restaurant_id"]
            assert rec_id in dataset_lookup, f"Unknown restaurant ID: {rec_id}"
            
            # Verify name matches exactly or closely
            expected_name = dataset_lookup[rec_id]["name"].strip().lower()
            actual_name = rec["restaurant_name"].strip().lower()
            assert actual_name == expected_name or expected_name in actual_name or actual_name in expected_name
