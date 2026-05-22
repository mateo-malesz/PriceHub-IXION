import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SELLASSIST_API_KEY")
# UWAGA: Bazowy URL z Twojego .env (zakładam, że masz tam nadal https://arante.sellasist.pl/api/v1)
BASE_URL = "https://arante.sellasist.pl/api/v1"

# W SellAssist endpoint dla zestawów to zazwyczaj /bundles, /sets lub /product_sets.
# Zaczniemy od najbardziej prawdopodobnego (bundles).
ENDPOINT = f"{BASE_URL}/sets_bulk" 

def fetch_test_bundles():
    if not API_KEY:
        print("❌ Błąd: Brak klucza SELLASSIST_API_KEY w pliku .env!")
        return

    print(f"🔄 Odpytuję API o zestawy produktowe: {ENDPOINT} ...")
    
    headers = {
        "Accept": "application/json",
        "apikey": API_KEY
    }
    
    # Pobieramy tylko 2-3 zestawy na próbę
    params = {
        "limit": 3
    }

    try:
        response = requests.get(ENDPOINT, headers=headers, params=params)
        
        if response.status_code == 200:
            print("✅ Sukces! Odebrano dane o zestawach.\n")
            data = response.json()
            print(json.dumps(data, indent=4, ensure_ascii=False))
        elif response.status_code == 404:
            print("❌ Błąd 404: Taki endpoint nie istnieje.")
            print("💡 Wskazówka: Zobacz w dokuemntacji Swaggera (link, który wysłałeś), jaka jest dokładna nazwa ścieżki (path) dla 'Zestawy produktowe'. Czy to /sets, /bundles, a może coś innego?")
        else:
            print(f"❌ Błąd HTTP {response.status_code}: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"🚨 Błąd połączenia sieciowego: {e}")

if __name__ == "__main__":
    fetch_test_bundles()