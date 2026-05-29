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
                
                try:
                    stock = int(float(item.get('quantity', 0.0)))
                except (ValueError, TypeError):
                    stock = 0
                
                # Inicjalizujemy pustym producentem i standardowym VATem
                product = Product.query.filter_by(sku=sku).first()
                if not product:
                    product = Product(
                        sku=sku, 
                        sellassist_id=sa_id, 
                        title=title, # Tymczasowa nazwa z SellAssist (zostanie nadpisana)
                        producer=None,
                        ean=ean,
                        stock=stock,
                        vat_rate=23,
                        sote_is_active=False
                    )
                    db.session.add(product)
                    added += 1
                else:
                    product.sellassist_id = sa_id
                    product.title = title
                    product.ean = ean
                    product.stock = stock
                    product.sote_is_active = False
                    
            db.session.commit()
            print(f"✅ Zapisano/Zaktualizowano {added} produktów z SA.")
        else:
            print(f"⚠️ Brak pliku {sa_products_path}")


        # --- 2. ŁADOWANIE SŁOWNIKA PRODUCENTÓW SOTE ---
        producers_path = f"{CACHE_DIR}/sote_producers.json"
        producers_map = {}
        if os.path.exists(producers_path):
            with open(producers_path, "r", encoding="utf-8") as f:
                producers_map = json.load(f)
            print(f"\n📖 Wczytano słownik producentów ({len(producers_map)} wpisów).")
        else:
            print(f"\n⚠️ Brak pliku {producers_path}")


        # --- 3. SEEDOWANIE Z SOTE (Ceny, Struktura, VAT, Producent) ---
        sote_path = f"{CACHE_DIR}/sote_dump.json"
        if os.path.exists(sote_path):
            print("\n🔗 Mapowanie SOTE (Nadpisywanie nazw, cen, VAT, marek, aktywności)...")
            with open(sote_path, "r", encoding="utf-8") as f:
                sote_data = json.load(f)
                
            mapped_main = 0
            mapped_options = 0
            
            for p_dict in sote_data:
                main_info = p_dict.get("main", {})
                options = p_dict.get("options", [])
                
                sote_parent_id = main_info.get("id")
                main_code = main_info.get("code")
                
                # Wyciągamy VAT 
                try:
                    vat_rate = int(float(main_info.get("vat", 23)))
                except:
                    vat_rate = 23
                    
                # Wyciągamy Producenta
                producer_id = str(main_info.get("producer_id", ""))
                producer_name = producers_map.get(producer_id)
                
                # --- 3a. Aktualizacja produktu głównego ---
                if main_code:
                    db_main = Product.query.filter_by(sku=main_code).first()
                    if db_main:
                        db_main.sote_id = sote_parent_id
                        db_main.vat_rate = vat_rate
                        
                        if producer_name:
                            db_main.producer = producer_name
                            
                        # NADPISUJEMY NAZWĘ Z SOTE
                        sote_name = main_info.get("name")
                        if sote_name:
                            db_main.title = sote_name
                            
                        # NADPISUJEMY CENY I AKTYWNOŚĆ
                        try:
                            db_main.sote_current_price_gross = float(main_info.get("price", 0.0))
                        except:
                            db_main.sote_current_price_gross = None
                            
                        try:
                            db_main.sote_price_strike = float(main_info.get("old_price", 0.0))
                        except:
                            db_main.sote_price_strike = None
                            
                        db_main.sote_is_active = main_info.get("is_active", True)
                        
                        mapped_main += 1
                
                # --- 3b. Aktualizacja wariantów ---
                for opt in options:
                    opt_code = opt.get("code")
                    if opt_code:
                        db_opt = Product.query.filter_by(sku=opt_code).first()
                        if db_opt:
                            db_opt.sote_id = sote_parent_id
                            db_opt.sote_option_id = opt.get("id")
                            db_opt.vat_rate = vat_rate
                            if producer_name:
                                db_opt.producer = producer_name
                            
                            # CENY I AKTYWNOŚĆ DLA WARIANTU
                            # Warianty dziedziczą status aktywności od rodzica
                            db_opt.sote_is_active = main_info.get("is_active", True)
                            
                            try:
                                db_opt.sote_current_price_gross = float(opt.get("price", 0.0))
                            except:
                                db_opt.sote_current_price_gross = None
                                
                            try:
                                db_opt.sote_price_strike = float(opt.get("old_price", 0.0))
                            except:
                                db_opt.sote_price_strike = None
                                
                            mapped_options += 1
                            
            db.session.commit()
            print(f"✅ Zmapowano i nadpisano! Produkty nadrzędne: {mapped_main} | Warianty: {mapped_options}")
        else:
            print(f"⚠️ Brak pliku {sote_path}")


        # --- 4. SEEDOWANIE ZESTAWÓW (BUNDLES) ---
        bundles_path = f"{CACHE_DIR}/sellassist_bundles.json"
        if os.path.exists(bundles_path):
            print("\n📦 Odtwarzanie relacji zestawów (Bundles)...")
            with open(bundles_path, "r", encoding="utf-8") as f:
                bundles_data = json.load(f)
                
            saved_bundles = 0
            for item in bundles_data:
                main_id = str(item.get('main_product_id'))
                component_sku = item.get('product_symbol')
                
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