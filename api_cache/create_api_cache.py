import os
import json
import time
import requests
from dotenv import load_dotenv
from zeep import Client
from zeep.helpers import serialize_object

load_dotenv()

# Foldery na nasz cache
CACHE_DIR = "api_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def cache_sellassist():
    print("\n🚀 Rozpoczynam zrzut danych z SellAssist...")
    api_key = os.getenv("SELLASSIST_API_KEY")
    base_url = os.getenv("SELLASSIST_API_URL", "https://arante.sellasist.pl/api/v1")
    
    headers = {"Accept": "application/json", "apikey": api_key}
    
    # 1. Pobieranie produktów (Paginacja)
    all_products = []
    limit = 100
    offset = 0
    
    print("📦 Pobieranie katalogu produktów...")
    while True:
        try:
            response = requests.get(f"{base_url}/products", headers=headers, params={"limit": limit, "offset": offset})
            if response.status_code != 200:
                print(f"❌ Błąd API: {response.status_code}")
                break
                
            data = response.json()
            items = data if isinstance(data, list) else data.get('products', [])
            
            if not items:
                break # Koniec stron
                
            all_products.extend(items)
            print(f"   ➔ Pobrano paczkę ({len(items)} sztuk). Razem: {len(all_products)}")
            
            offset += limit
            time.sleep(0.5) # Bezpiecznik (Rate limit)
        except Exception as e:
            print(f"❌ Błąd: {e}")
            break

    with open(f"{CACHE_DIR}/sellassist_products.json", "w", encoding="utf-8") as f:
        json.dump(all_products, f, indent=4, ensure_ascii=False)

    # 2. Pobieranie zestawów (Zazwyczaj jest to jeden strzał)
    print("\n📦 Pobieranie struktur zestawów...")
    try:
        response = requests.get(f"{base_url}/sets_bulk", headers=headers)
        if response.status_code == 200:
            with open(f"{CACHE_DIR}/sellassist_bundles.json", "w", encoding="utf-8") as f:
                json.dump(response.json(), f, indent=4, ensure_ascii=False)
            print(f"✅ Zapisano zestawy.")
    except Exception as e:
        print(f"❌ Błąd zestawów: {e}")

def cache_sote():
    print("\n🚀 Rozpoczynam błyskawiczny zrzut struktury z SOTE (bez zapytań N+1!)...")
    
    URL = os.getenv("SOTE_URL")
    USER = os.getenv("SOTE_USER")  
    PASS = os.getenv("SOTE_PASSWORD")

    if not URL or not USER or not PASS:
        print("❌ Błąd: Brak kompletnych danych logowania do SOTE w pliku .env!")
        return
    
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        
    try:
        # Logowanie
        client_login = Client(f"{URL}/webapi/soap?wsdl")
        session_hash = client_login.service.doLogin(client_login.get_type("ns0:doLogin")(_culture="pl", username=USER, password=PASS))
        
        # --- 1. POBIERANIE SŁOWNIKA PRODUCENTÓW (Z PAGINACJĄ) ---
        print("📦 Pobieranie kompletnego słownika producentów z SOTE...")
        producers_dict = {}
        try:
            client_producer = Client(f"{URL}/producer/soap?wsdl")
            get_producer_list_type = client_producer.get_type("ns0:GetProducerList")
            
            p_limit = 50
            p_offset = 0
            
            while True:
                producers_response = client_producer.service.GetProducerList(get_producer_list_type(
                    _session_hash=session_hash,
                    _limit=p_limit,
                    _offset=p_offset
                ))
                
                if not producers_response:
                    break
                    
                producers_page = serialize_object(producers_response)
                if not isinstance(producers_page, list): 
                    producers_page = [producers_page]
                    
                for prod in producers_page:
                    if prod and prod.get('id') and prod.get('name'):
                        producers_dict[str(prod.get('id'))] = prod.get('name')
                        
                print(f"   ➔ Pobrano paczkę producentów... Razem w pamięci: {len(producers_dict)}", end="\r")
                p_offset += p_limit
                time.sleep(0.1)
                
            print() # Nowa linia
            with open(f"{CACHE_DIR}/sote_producers.json", "w", encoding="utf-8") as f:
                json.dump(producers_dict, f, indent=4, ensure_ascii=False)
            print(f"✅ Zapisano pełny słownik: {len(producers_dict)} producentów.")
            
        except Exception as e:
            print(f"\n⚠️ Błąd pobierania producentów: {e}")

        # --- 2. POBIERANIE PRODUKTÓW (GŁÓWNA LISTA) ---
        client_product = Client(f"{URL}/product/soap?wsdl")
        get_list_type = client_product.get_type("ns0:GetProductList")
        
        all_products = []
        offset = 0
        limit = 50 
        
        print("\n📦 Pobieranie głównej listy produktów...")
        while True:
            try:
                products_response = client_product.service.GetProductList(get_list_type(
                    _session_hash=session_hash, 
                    _limit=limit, 
                    _offset=offset
                ))
                
                if not products_response:
                    break 
                    
                products_page = serialize_object(products_response)
                if not isinstance(products_page, list): 
                    products_page = [products_page]
                    
                all_products.extend(products_page)
                print(f"   ➔ Pobrano paczkę... Razem w pamięci: {len(all_products)}", end="\r")
                offset += limit
            except Exception as e:
                break

        print(f"\n✅ Zakończono pobieranie. Zebrano łącznie: {len(all_products)} produktów.")

        # --- 3. PARSOWANIE (LOKALNIE, BEZ DODATKOWYCH STRZAŁÓW DO API!) ---
        print("\n⚡ Przetwarzanie i wyciąganie wariantów z surowego tekstu...")
        sote_dump = []
        
        for idx, p in enumerate(all_products):
            p_active = p.get('active')
            
            if p_active in [False, 0, '0', 'false', 'False', None]:
                continue 
                
            p_id = p.get('id')
            p_code = p.get('code')
            
            slim_main = {
                "id": p_id,
                "code": p_code,
                "name": p.get('name'),
                "vat": p.get('vat'),
                "producer_id": p.get('producer_id')
            }
            
            p_dict = {"main": slim_main, "options": []}
            
            # --- TWOJA OPTYMALIZACJA: Tniemy tekst lokalnie ---
            product_options_raw = p.get('product_options')
            
            if isinstance(product_options_raw, str) and '\n' in product_options_raw:
                lines = product_options_raw.split('\n')
                for line in lines:
                    if '{' in line and '"kod"' in line and '"id"' in line:
                        start_idx = line.find('{')
                        end_idx = line.rfind('}') + 1
                        
                        if start_idx != -1 and end_idx != -1:
                            try:
                                opt_data = json.loads(line[start_idx:end_idx])
                                if opt_data.get('kod') and opt_data.get('id'):
                                    p_dict["options"].append({
                                        "id": opt_data.get('id'),
                                        "code": opt_data.get('kod'),
                                        "price": opt_data.get('cena', 0.0)
                                    })
                            except:
                                pass
                
            sote_dump.append(p_dict)
            
        print("✅ Zakończono lokalne skanowanie struktury produktów SOTE.")
        
        with open(f"{CACHE_DIR}/sote_dump.json", "w", encoding="utf-8") as f:
            json.dump(sote_dump, f, indent=4, ensure_ascii=False, default=str)
            
    except Exception as e:
        print(f"❌ Błąd ogólny SOTE: {e}")

if __name__ == "__main__":
    print("========================================")
    print(" GENERATOR OFFLINE CACHE - PRICEHUB API")
    print("========================================")
    cache_sellassist()
    cache_sote()
    print("\n🎉 WSZYSTKO ZAKOŃCZONE! Dane bezpiecznie leżą w folderze /api_cache")