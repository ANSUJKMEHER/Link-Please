import os
import sys
import time
import httpx
from app.config import settings

def main():
    print("=" * 60)
    print("LinkPlease — Simulation Runner & Truth Verification")
    print("=" * 60)
    
    if not settings.API_KEY:
        print("WARNING: API_KEY is not set in .env! Simulation requires a valid API key.")
    
    webhook_url = input("Enter your public webhook URL (e.g. https://your-domain.com/webhook): ").strip()
    if not webhook_url:
        print("Webhook URL is required.")
        return

    count_str = input("Number of comment events to simulate (default: 500): ").strip() or "500"
    duration_str = input("Duration in seconds (default: 10): ").strip() or "10"
    
    count = int(count_str)
    duration_seconds = int(duration_str)

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": settings.API_KEY
    }

    print(f"\nTriggering simulation: {count} events over {duration_seconds}s targeting {webhook_url}...")
    
    with httpx.Client(timeout=30.0) as client:
        start_res = client.post(
            f"{settings.MOCK_API_BASE_URL.rstrip('/')}/v1/simulate/start",
            json={"webhook_url": webhook_url, "count": count, "duration_seconds": duration_seconds},
            headers=headers
        )
        
        if start_res.status_code != 200:
            print(f"Failed to start simulation: HTTP {start_res.status_code} -> {start_res.text}")
            return
            
        start_data = start_res.json()
        run_id = start_data.get("run_id")
        print(f"Simulation started successfully! Run ID: {run_id}")
        
        print("\nPolling live stats from your application...")
        for _ in range(15):
            time.sleep(2)
            try:
                stats_res = client.get("http://localhost:8000/stats")
                if stats_res.status_code == 200:
                    stats = stats_res.json()
                    print(f"Live Stats -> sent: {stats['sent']}, failed: {stats['failed']}, queued: {stats['queued']}, duplicates_blocked: {stats['duplicates_blocked']}")
            except Exception:
                pass

        print(f"\nFetching truth data from mock API for Run ID: {run_id}...")
        try:
            truth_res = client.get(
                f"{settings.MOCK_API_BASE_URL.rstrip('/')}/v1/simulate/{run_id}/truth",
                headers=headers
            )
            if truth_res.status_code == 200:
                truth = truth_res.json()
                print("Mock API Server Truth:")
                print(truth)
            else:
                print(f"Could not fetch truth: HTTP {truth_res.status_code} -> {truth_res.text}")
        except Exception as e:
            print(f"Error fetching truth: {e}")

if __name__ == "__main__":
    main()
