import os
import json
from app import app, db, Product, BundleComponent

CACHE_DIR = "api_cache"

def seed_database():
    print("==================================================")
    print(" 🚀 AKTUALIZACJA BAZY DANYCH (SSOT: SA + SOTE)")
    print("==================================================")

    with app.app_context():
        print("🧹 Resetowanie tabel w bazie danych...")
        BundleComponent.query.delete()
        Product.query.delete()
        db.session.commit()

        # --- 1. SEEDOWANIE Z SELLASSIST ---
        sa_products_path = f"{CACHE_DIR}/sellassist_products.json"
        if os.path.exists(sa_products_path):
            print("\n📦 Wgrywanie katalogu (SellAssist)...")
            with open(sa_products_path, "r", encoding="utf-8") as f:
                sa_data = json.load(f)
                
            added = 0
            for item in sa_data:
                sku = str(item.get('symbol', '')).strip()
                if not sku or sku == 'None' or sku == '':
                    continue
                    
                sa_id = str(item.get('id', '')).strip()
                title = str(item.get('name', '')).strip()
                ean = str(item.get('ean', '')).strip() or None
                
                # POPRAWKA: SellAssist używa 'quantity' w formacie string np. "1.000"
                try:
                    stock = int(float(item.get('quantity', 0.0)))
                except (ValueError, TypeError):
                    stock = 0
                
                # Zbiorcze API nie zwraca producenta w tym pliku
                producer = None
                
                product = Product.query.filter_by(sku=sku).first()
                if not product:
                    product = Product(
                        sku=sku, 
                        sellassist_id=sa_id, 
                        title=title,
                        producer=producer,
                        ean=ean,
                        stock=stock
                    )
                    db.session.add(product)
                    added += 1
                else:
                    product.sellassist_id = sa_id
                    product.title = title
                    product.producer = producer
                    product.ean = ean
                    product.stock = stock
                    
            db.session.commit()
            print(f"✅ Zapisano/Zaktualizowano {added} produktów z SA.")
        else:
            print(f"⚠️ Brak pliku {sa_products_path}")

        # --- 2. SEEDOWANIE Z SOTE ---
        sote_path = f"{CACHE_DIR}/sote_dump.json"
        if os.path.exists(sote_path):
            print("\n🔗 Mapowanie struktury wariantów oraz cen bieżących (SOTE)...")
            with open(sote_path, "r", encoding="utf-8") as f:
                sote_data = json.load(f)
                
            mapped_main = 0
            mapped_options = 0
            
            for p_dict in sote_data:
                main_info = p_dict.get("main", {})
                options = p_dict.get("options", [])
                
                sote_parent_id = main_info.get("id")
                main_code = main_info.get("code")
                
                if main_code:
                    db_main = Product.query.filter_by(sku=main_code).first()
                    if db_main:
                        db_main.sote_id = sote_parent_id
                        mapped_main += 1
                
                for opt in options:
                    opt_code = opt.get("code")
                    if opt_code:
                        db_opt = Product.query.filter_by(sku=opt_code).first()
                        if db_opt:
                            db_opt.sote_id = sote_parent_id
                            db_opt.sote_option_id = opt.get("id")
                            
                            try:
                                current_price = float(opt.get("price", 0.0))
                                db_opt.sote_current_price_gross = current_price
                            except:
                                db_opt.sote_current_price_gross = None
                                
                            mapped_options += 1
                            
            db.session.commit()
            print(f"✅ Zmapowano! Produkty nadrzędne: {mapped_main} | Warianty z cenami: {mapped_options}")
        else:
            print(f"⚠️ Brak pliku {sote_path}")

        # --- 3. SEEDOWANIE ZESTAWÓW (BUNDLES) ---
        bundles_path = f"{CACHE_DIR}/sellassist_bundles.json"
        if os.path.exists(bundles_path):
            print("\n📦 Odtwarzanie relacji zestawów (Bundles)...")
            with open(bundles_path, "r", encoding="utf-8") as f:
                bundles_data = json.load(f)
                
            saved_bundles = 0
            for item in bundles_data:
                main_id = str(item.get('main_product_id'))
                component_sku = item.get('product_symbol')
                
                # Ilość u nich też jest przekazywana jako string "1.000"
                try:
                    quantity = float(item.get('quantity', 1.0))
                except:
                    quantity = 1.0

                parent_product = Product.query.filter_by(sellassist_id=main_id).first()

                if parent_product and component_sku:
                    new_component = BundleComponent(
                        bundle_sku=parent_product.sku,
                        component_sku=component_sku,
                        quantity=quantity
                    )
                    db.session.add(new_component)
                    saved_bundles += 1
                    
            db.session.commit()
            print(f"✅ Powiązano {saved_bundles} składników w zestawy.")
        else:
            print(f"⚠️ Brak pliku {bundles_path}")

        print("\n🎉 BAZA DANYCH GOTOWA DO PRACY OFF-LINE!")

if __name__ == "__main__":
    seed_database()