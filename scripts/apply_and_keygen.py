import os
import sys
import httpx

MOCK_BASE_URL = "https://pseudogram-api.onrender.com"

def main():
    print("=" * 60)
    print("LinkPlease — Mock Instagram API Key Setup")
    print("=" * 60)
    
    email = input("Enter your email: ").strip()
    if not email:
        print("Email is required.")
        return

    name = input("Enter your full name: ").strip() or "Candidate"
    phone = input("Enter your phone number (e.g. +919876543210): ").strip() or "+919876543210"
    whatsapp = input("Enter WhatsApp (leave empty if same as phone): ").strip() or phone
    linkedin_url = input("Enter LinkedIn URL: ").strip() or "https://linkedin.com/in/candidate"

    apply_payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "whatsapp": whatsapp,
        "linkedin_url": linkedin_url
    }

    print("\n1. Applying to Mock API...")
    with httpx.Client() as client:
        try:
            res_apply = client.post(f"{MOCK_BASE_URL}/v1/apply", json=apply_payload, timeout=15.0)
            print(f"Apply response: HTTP {res_apply.status_code} -> {res_apply.text}")
        except Exception as e:
            print(f"Error during apply: {e}")

        print("\n2. Fetching API Key...")
        try:
            res_keygen = client.post(f"{MOCK_BASE_URL}/v1/keygen", json={"email": email}, timeout=15.0)
            if res_keygen.status_code == 200:
                data = res_keygen.json()
                api_key = data.get("api_key")
                print(f"\nSUCCESS! API Key obtained:\n{api_key}")
                
                # Save to .env
                env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
                env_content = f"API_KEY={api_key}\nMOCK_API_BASE_URL={MOCK_BASE_URL}\nVERIFY_SIGNATURE=True\nDATABASE_PATH=data/linkplease.db\n"
                with open(env_path, "w") as f:
                    f.write(env_content)
                print(f"Saved configuration to {env_path}")
            else:
                print(f"Failed to get key: HTTP {res_keygen.status_code} -> {res_keygen.text}")
        except Exception as e:
            print(f"Error during keygen: {e}")

if __name__ == "__main__":
    main()
