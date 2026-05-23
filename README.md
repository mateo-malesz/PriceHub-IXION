
# PriceHub (IXION)

PriceHub to nowoczesny system klasy PIM (Product Information Management) oraz dynamicznego pricingu, stworzony z myślą o centralnym zarządzaniu kosztami, marżami oraz cennikami w ekosystemie e-commerce (SellAssist, SOTE, ERP Nexo).

  

Aplikacja pozwala analitykom ds. wycen na błyskawiczne importowanie kosztów od dostawców, automatyczne pobieranie struktur zestawów (bundles) z API oraz dynamiczne wyliczanie sugerowanych cen sprzedaży w oparciu o pożądany próg marży.

  

# 🚀 Główne Funkcje (Stan Obecny)

Centralna Baza Produktów (Global Catalog): Architektura oddzielająca globalne dane produktu (SKU, nazwa, producent) od cenników przypisanych do konkretnych kanałów sprzedaży (sklepów).

  

Zaawansowany Dashboard AG Grid: Profesjonalna, ultra-wydajna tabela obsługująca 25 kolumn danych (koszty walutowe, przeliczenia PLN, stany magazynowe, marże i ceny docelowe) z pełnym wsparciem dla filtrowania i sortowania po stronie klienta.

  

# Integracja z API SellAssist:

  

Automatyczna synchronizacja katalogu produktów i mapowanie wewnętrznych ID systemu na unikalne kody SKU.

  

Pobieranie i automatyczne mapowanie struktur Zestawów Produktowych (Bundles) bezpośrednio z endpointu /sets_bulk.

  

Responsywny Panel Zestawów: Moduł prezentujący wirtualne pakiety produktów w postaci czytelnych kart, dynamicznie dostosowujący się do ekranów smartfonów, tabletów oraz monitorów stacjonarnych.

  

Panel Administratora (Flask-Admin): Bezpieczny wgląd w surowe tabele bazy danych SQLite z poziomu przeglądarki.

  

# 🛠️ Stos Technologiczny (Tech Stack)

Backend: Python 3.14+, Flask (Flask-Login, Flask-Admin, APScheduler)

  

Baza Danych: SQLite + SQLAlchemy (ORM)

  

Frontend: Jinja2 templates, Bootstrap 5, Vanilla JS (Fetch API / AJAX)

  

Data Grid: AG Grid Community (v31.3)

  

Integracje: REST API (SellAssist), SOAP (SOTE - w przygotowaniu)

  

# 🗄️ Architektura Bazy Danych

System bazuje na relacyjnym modelu danych podzielonym na dwie strefy:

  

Strefa Globalna (Product): Przechowuje unikalne kody SKU, nazwy, producentów oraz dane dostawców, które są niezmienne niezależnie od sklepu.

  

Strefa Projektowa (ProjectPrice, StoreCache): Przechowuje stany magazynowe oraz ceny wyliczone dla konkretnego kanału (np. Arante B2C, Arante B2B).

  

Strefa Relacji (BundleComponent): Tabela asocjacyjna definiująca, z jakich fizycznych pod-produktów (i w jakiej ilości) składa się wirtualny zestaw.

  

# 📦 Instalacja i Konfiguracja

1. Klonowanie repozytorium i wejście do katalogu

Bash

git clone https://github.com/twoj-login/PriceHub-IXION.git

cd PriceHub-IXION

2. Aktywacja środowiska wirtualnego

Bash

source .venv/bin/bin/activate # Linux/MacOS

# lub

.venv\Scripts\activate # Windows

3. Instalacja zależności

Bash

pip install -r requirements.txt

4. Konfiguracja pliku .env

Stwórz plik .env w głównym katalogu projektu i uzupełnij go o swoje dane dostępowe:

  

Fragment kodu

FLASK_SECRET_KEY=twoj_super_tajny_klucz_sesji

DATABASE_URL=sqlite:///database.db

  

# Integracja SellAssist

SELLASSIST_API_KEY=twój_klucz_api_sellassist

SELLASSIST_API_URL=https://arante.sellasist.pl/api/v1/products

🚦 Uruchomienie Aplikacji

Aby odpalić serwer deweloperski, wykonaj komendę:

  

Bash

python app.py

Aplikacja będzie dostępna w przeglądarce pod adresem: http://127.0.0.1:5005

  

# Kluczowe adresy URL systemu:

http://127.0.0.1:5005/projects - Główny panel wyboru projektów.

  

http://127.0.0.1:5005/admin - Panel administratora bazy danych (wymaga logowania).

  

http://127.0.0.1:5005/sync_sellassist - Ręczne wymuszenie pobrania katalogu produktów.

  

# 🗺️ Roadmap (Najbliższe kroki)

[ ] Wdrożenie AJAX Auto-save w AG Grid: Automatyczny zapis zmienionych cen brutto do bazy danych w tle po wciśnięciu Enter.

  

[ ] Moduł Importu Kosztów (Excel): Parser plików .xlsx/.csv od dostawców z elastycznym mechanizmem mapowania kolumn.

  

[ ] Integracja SOTE API: Dwukierunkowa synchronizacja (pobieranie opcji produktów oraz wypychanie gotowych cen docelowych).

  

[ ] Moduł Marżowości Zestawów: Automatyczne sumowanie kosztów składników i wyliczanie marży bazowej dla całego pakietu na podstawie danych z karty zestawu.