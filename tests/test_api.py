"""API integration tests for Phase 4 FastAPI service — all endpoints, mocked Groq client."""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from app import app
from src.models.schema import (
    BudgetTier,
    RecommendationResponse,
    RestaurantRecommendation,
)
import src.api.dependencies as deps


@pytest.fixture(scope="module")
def client():
    """Spin up the FastAPI TestClient with the full lifespan (dataset loaded)."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. /health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_body_schema(self, client):
        data = client.get("/health").json()
        assert "status" in data
        assert "dataset_loaded" in data
        assert "total_restaurants" in data
        assert "version" in data
        assert "llm_provider" in data

    def test_health_dataset_loaded(self, client):
        data = client.get("/health").json()
        assert data["dataset_loaded"] is True
        assert data["total_restaurants"] > 0

    def test_health_response_time_header(self, client):
        response = client.get("/health")
        assert "X-Response-Time" in response.headers
        ms_value = response.headers["X-Response-Time"].rstrip("ms")
        assert float(ms_value) >= 0


# ---------------------------------------------------------------------------
# 2. /api/v1/meta/options endpoint
# ---------------------------------------------------------------------------

class TestMetaOptionsEndpoint:
    def test_meta_options_returns_200(self, client):
        response = client.get("/api/v1/meta/options")
        assert response.status_code == 200

    def test_meta_options_schema(self, client):
        data = client.get("/api/v1/meta/options").json()
        assert "localities" in data
        assert "cuisines" in data
        assert "budget_tiers" in data
        assert "rating_range" in data
        assert "total_restaurants" in data

    def test_meta_options_localities_nonempty(self, client):
        data = client.get("/api/v1/meta/options").json()
        assert len(data["localities"]) > 0

    def test_meta_options_cuisines_nonempty(self, client):
        data = client.get("/api/v1/meta/options").json()
        assert len(data["cuisines"]) > 0

    def test_meta_options_budget_tiers_correct(self, client):
        data = client.get("/api/v1/meta/options").json()
        tier_values = {t["value"] for t in data["budget_tiers"]}
        assert tier_values == {"low", "medium", "high"}

    def test_meta_options_response_time_header(self, client):
        response = client.get("/api/v1/meta/options")
        assert "X-Response-Time" in response.headers


# ---------------------------------------------------------------------------
# 3. /api/v1/recommend endpoint
# ---------------------------------------------------------------------------

def _mock_groq_response() -> RecommendationResponse:
    return RecommendationResponse(
        query_summary="Italian dining in Bangalore",
        total_candidates_analyzed=12,
        relaxation_applied=False,
        recommendations=[
            RestaurantRecommendation(
                restaurant_id="ZOM_MOCK_1",
                restaurant_name="Mock Trattoria",
                cuisine="Italian",
                rating=4.5,
                estimated_cost_for_two="₹1,200 (Medium)",
                recommendation_reason="Authentic wood-fired pasta and romantic ambiance in Indiranagar.",
            )
        ],
    )


class TestRecommendEndpoint:
    def test_recommend_valid_payload_200(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["Italian"],
            "budget_tier": "medium",
            "min_rating": 4.0,
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200

    def test_recommend_response_schema(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["North Indian"],
            "budget_tier": "medium",
            "min_rating": 3.5,
        }
        data = client.post("/api/v1/recommend", json=payload).json()
        assert "query_summary" in data
        assert "total_candidates_analyzed" in data
        assert "relaxation_applied" in data
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    def test_recommend_grounding_all_recs_in_dataset(self, client):
        """All recommendation IDs must exist in the clean dataset."""
        from src.data.preprocessor import load_processed_data
        df = load_processed_data()
        dataset_ids = set(df["restaurant_id"].astype(str).tolist())

        payload = {
            "location": "Bangalore",
            "cuisines": ["Italian"],
            "budget_tier": "medium",
            "min_rating": 4.0,
            "max_recommendations": 3,
        }
        data = client.post("/api/v1/recommend", json=payload).json()
        for rec in data["recommendations"]:
            assert rec["restaurant_id"] in dataset_ids, (
                f"Hallucinated ID {rec['restaurant_id']} not in dataset"
            )

    def test_recommend_with_additional_notes(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["Cafe"],
            "budget_tier": "low",
            "min_rating": 3.8,
            "additional_notes": "quiet wifi spot for laptop work",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200

    def test_recommend_response_time_header(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["all"],
            "budget_tier": "medium",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert "X-Response-Time" in response.headers

    def test_recommend_relaxation_flag_on_impossible_query(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["Ethiopian"],
            "budget_tier": "low",
            "min_rating": 5.0,
        }
        data = client.post("/api/v1/recommend", json=payload).json()
        assert data["relaxation_applied"] is True

    def test_recommend_with_mocked_groq_client(self, client):
        """Verify the pipeline when Groq client is mocked to return a structured response."""
        mock_client = MagicMock()
        mock_completion = MagicMock()
        # Simulate Groq JSON mode response
        import json as _json
        mock_completion.choices[0].message.content = _json.dumps(
            _mock_groq_response().model_dump()
        )
        mock_client.chat.completions.create.return_value = mock_completion

        # Temporarily inject mock client into the singleton
        original_client = deps._llm_client
        original_provider = deps._llm_provider
        deps._llm_client = mock_client
        deps._llm_provider = "groq"

        try:
            payload = {
                "location": "Bangalore",
                "cuisines": ["Italian"],
                "budget_tier": "medium",
                "min_rating": 4.0,
            }
            response = client.post("/api/v1/recommend", json=payload)
            assert response.status_code == 200
        finally:
            deps._llm_client = original_client
            deps._llm_provider = original_provider

    def test_recommend_invalid_budget_422(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["Italian"],
            "budget_tier": "superluxury",  # Invalid
            "min_rating": 4.0,
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 422

    def test_recommend_invalid_rating_422(self, client):
        payload = {
            "location": "Bangalore",
            "cuisines": ["Italian"],
            "budget_tier": "medium",
            "min_rating": 6.0,  # > 5.0, invalid
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 422

    def test_recommend_missing_location_422(self, client):
        payload = {
            "cuisines": ["Italian"],
            "budget_tier": "medium",
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 422

    def test_recommend_compound_location(self, client):
        payload = {
            "location": "Indiranagar, Bangalore",
            "cuisines": ["all"],
            "budget_tier": "medium",
            "min_rating": 3.5,
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["total_candidates_analyzed"] > 0

    def test_recommend_pipeline_error_503(self, client):
        """Verify that unexpected pipeline failures return HTTP 503 with structured error detail."""
        payload = {
            "location": "Bangalore",
            "cuisines": ["Italian"],
            "budget_tier": "medium",
            "min_rating": 4.0,
        }
        with patch("src.api.routes.filter_restaurants", side_effect=RuntimeError("Groq service unreachable")):
            response = client.post("/api/v1/recommend", json=payload)
            assert response.status_code == 503
            data = response.json()
            assert "detail" in data
            assert data["detail"]["error"] == "recommendation_pipeline_error"
            # Internal error text is not leaked; a request ID is returned for log lookup
            assert "Groq service unreachable" not in data["detail"]["message"]
            assert data["detail"]["request_id"] == response.headers["X-Request-ID"]

    @pytest.mark.skipif(not settings.GROQ_API_KEY, reason="Live GROQ_API_KEY not configured")
    def test_recommend_live_groq_endpoint(self, client):
        """Integration test for /api/v1/recommend endpoint hitting live Groq LPU API."""
        payload = {
            "location": "Bangalore",
            "cuisines": ["Italian"],
            "budget_tier": "medium",
            "min_rating": 4.0,
            "additional_notes": "romantic anniversary dinner, quiet table",
            "max_recommendations": 2,
        }
        response = client.post("/api/v1/recommend", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["recommendations"]) == 2
        assert "X-Response-Time" in response.headers
        for rec in data["recommendations"]:
            assert rec["restaurant_id"]
            assert len(rec["recommendation_reason"]) > 10


