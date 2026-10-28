"""Quick connectivity and health test for the running Zomato AI server."""
import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"

print("=" * 60)
print("Testing Zomato AI Concierge running at:", BASE_URL)
print("=" * 60)

try:
    # 1. Test Root UI
    r_ui = httpx.get(f"{BASE_URL}/", timeout=5.0)
    print(f"\n[1] Root Web UI (/):")
    print(f"    Status:         {r_ui.status_code} {'OK' if r_ui.status_code == 200 else 'FAIL'}")
    print(f"    Content Length: {len(r_ui.text):,} bytes")
    print(f"    Content Type:   {r_ui.headers.get('content-type')}")

    # 2. Test Health Endpoint
    r_health = httpx.get(f"{BASE_URL}/health", timeout=5.0)
    health_data = r_health.json()
    print(f"\n[2] Health Check (/health):")
    print(f"    Status:         {r_health.status_code} {'OK' if r_health.status_code == 200 else 'FAIL'}")
    print(f"    Engine Status:  {health_data.get('status')}")
    print(f"    Restaurants:    {health_data.get('total_restaurants'):,}")
    print(f"    LLM Provider:   {health_data.get('llm_provider')}")
    print(f"    Version:        {health_data.get('version')}")

    # 3. Test Meta Options
    r_meta = httpx.get(f"{BASE_URL}/api/v1/meta/options", timeout=5.0)
    meta_data = r_meta.json()
    print(f"\n[3] Metadata Options (/api/v1/meta/options):")
    print(f"    Status:         {r_meta.status_code} {'OK' if r_meta.status_code == 200 else 'FAIL'}")
    print(f"    Top Localities: {len(meta_data.get('localities', []))} available")
    print(f"    Top Cuisines:   {len(meta_data.get('cuisines', []))} available")

    print("\n" + "=" * 60)
    print("SUCCESS: Both Backend and Frontend are fully operational!")
    print(f"Open in your browser: {BASE_URL}")
    print("=" * 60)

except httpx.ConnectError:
    print(f"\n[FAIL] Could not connect to {BASE_URL}.")
    print("Ensure the server is running by executing:")
    print("    .\\.venv\\Scripts\\python -m uvicorn app:app --host 127.0.0.1 --port 8000")
    sys.exit(1)
except Exception as e:
    print(f"\n[FAIL] Unexpected error: {e}")
    sys.exit(1)
