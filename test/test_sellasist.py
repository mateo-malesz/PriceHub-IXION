import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SELLASSIST_API_KEY")
API_URL = os.getenv("SELLASSIST_API_URL")

def fetch_test_products():
    if not API_KEY or not API_URL:
        print("❌ Błąd: Brak kluczy w pliku .env!")
        return

    print(f"🔄 Nawiązywanie połączenia z SellAssist API...")
    
    headers = {
        "Accept": "application/json",
        "apikey": API_KEY
    }
    
    params = {
        "limit": 20
    }

    try:
        # Wykonujemy request GET
        response = requests.get(API_URL, headers=headers, params=params)
        
        # Weryfikacja statusu odpowiedzi (200 OK to sukces)
        if response.status_code == 200:
            print("✅ Sukces! Odebrano dane z serwera.\n")
            data = response.json()
            
            # Wypisujemy ładnie sformatowany JSON na konsolę (z polskimi znakami)
            print(json.dumps(data, indent=4, ensure_ascii=False))
        else:
            print(f"❌ Błąd HTTP {response.status_code}")
            print(f"Szczegóły: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"🚨 Błąd połączenia sieciowego: {e}")

if __name__ == "__main__":
    fetch_test_products()