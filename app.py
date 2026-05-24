from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse
from flask_mail import Mail, Message
from flask import make_response
import xml.etree.ElementTree as ET
from flask_apscheduler import APScheduler
from datetime import datetime, date, timezone
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from sote_integration import fetch_sales_for_date
from datetime import timedelta
import requests
import os
import re
import json
import csv
import io
import logging
from logging.handlers import RotatingFileHandler
from sqlalchemy import func, case, or_
from dotenv import load_dotenv
from threading import Thread
from flask import jsonify
from flask import current_app
from zeep import Client
from zeep.helpers import serialize_object
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


load_dotenv()

# --- KONFIGURACJA STREFY CZASOWEJ ---
TIMEZONE = ZoneInfo("Europe/Warsaw")

def get_current_time():
    return datetime.now(TIMEZONE)

# --- KONFIGURACJA LOGOWANIA ---
# Ustawiamy RotatingFileHandler: max 1MB na plik, trzymamy 5 ostatnich plików
file_handler = RotatingFileHandler('app.log', maxBytes=1024 * 1024, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        file_handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# --- KONFIGURACJA MAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_RECIPIENT'] = os.getenv('MAIL_RECIPIENT')

mail = Mail(app)


# --- KONFIGURACJA HARMONOGRAMU ---
class Config:
    SCHEDULER_API_ENABLED = True


app.config.from_object(Config())

scheduler = APScheduler()
scheduler.init_app(app)
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    scheduler.start()

# --- KONFIGURACJA APLIKACJI ---
app.secret_key = os.getenv('SECRET_KEY')
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "connect_args": {
        "timeout": 30,
    }
}

db = SQLAlchemy(app)

from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

# --- FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# --- FLASK-ADMIN ---
class MyModelView(ModelView):
    def is_accessible(self):
        admin_email = os.getenv('ADMIN_EMAIL')
        return current_user.is_authenticated and admin_email and current_user.email == admin_email

    def inaccessible_callback(self, name, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        flash('Brak uprawnień administratora.', category='error')
        return redirect(url_for('home'))

# class ProductModelView(MyModelView):
#     # Aktualizujemy wyszukiwanie po nowych kolumnach
#     column_searchable_list = ['title', 'sku', 'supplier_sku']
    
#     # Aktualizujemy filtry
#     column_filters = ['producer', 'currency']
    
#     # Aktualizujemy listę wyświetlanych kolumn
#     column_list = ['sku', 'title', 'producer', 'currency', 'vat_rate']
    
#     # Aktualizujemy sortowanie
#     column_sortable_list = ['title', 'sku']

class ProductAdminView(ModelView):
    # 1. Kolumny widoczne w głównej tabeli (wybrałem najważniejsze, żeby nie zepsuć responsywności)
    column_list = (
        'sku', 'title', 'stock', 'sote_current_price_gross', 
        'producer', 'ean', 'sellassist_id', 'sote_id', 'sote_option_id',
        'purchase_price_net_currency', 'vat_rate'
    )

    # 2. Pola, po których można swobodnie wyszukiwać w pasku "Search"
    column_searchable_list = ('sku', 'title', 'ean', 'producer', 'sellassist_id')

    # 3. Zestaw filtrów w bocznym menu (pozwala np. wyfiltrować "stock > 0")
    column_filters = ('producer', 'stock', 'sote_id', 'vat_rate')

    # 4. Szybka edycja komórek bezpośrednio z widoku listy (bez wchodzenia w detale)
    column_editable_list = ['stock', 'sote_current_price_gross', 'purchase_price_net_currency']

    # 5. Domyślne sortowanie
    column_default_sort = 'sku'

    # 6. Paginacja
    page_size = 50

    # Ochrona widoku (dostosuj do swojego obecnego mechanizmu logowania w adminie)
    def is_accessible(self):
        from flask_login import current_user
        return current_user.is_authenticated

class UserModelView(MyModelView):
    def on_model_change(self, form, model, is_created):
        if form.password.data:
            # SPRAWDZENIE: Jeśli hasło NIE zaczyna się od 'pbkdf2:',
            # to znaczy, że wpisałeś nowe, czyste hasło i trzeba je zahaszować.
            if not form.password.data.startswith('pbkdf2:sha256'):
                model.password = generate_password_hash(form.password.data, method='pbkdf2:sha256')
            else:
                # Jeśli zaczyna się od pbkdf2, to znaczy, że to stary hash
                # – nie dotykamy go, zostawiamy tak jak jest w modelu.
                pass

        return super(UserModelView, self).on_model_change(form, model, is_created)

class ProjectModelView(MyModelView):
    # W nowym modelu relacja to project_prices, a nie products
    form_excluded_columns = ['project_prices']
    column_list = ['name', 'domain', 'api_type', 'api_url']
class MyAdminIndexView(AdminIndexView):
    def is_accessible(self):
        admin_email = os.getenv('ADMIN_EMAIL')
        return current_user.is_authenticated and admin_email and current_user.email == admin_email

    def inaccessible_callback(self, name, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        flash('Brak uprawnień administratora.', category='error')
        return redirect(url_for('home'))

    @expose('/')
    def index(self):
        user_count = User.query.count()
        project_count = Project.query.count()
        product_count = Product.query.count()
        return self.render('admin/index.html',
                           user_count=user_count,
                           project_count=project_count,
                           product_count=product_count)

admin = Admin(app, name='Panel Administratora', index_view=MyAdminIndexView())

# --- MODELE BAZY DANYCH ---
project_users = db.Table('project_users',
                         db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
                         db.Column('project_id', db.Integer, db.ForeignKey('project.id'), primary_key=True)
                         )

# --- USER ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    image_file = db.Column(db.String(500), nullable=False,
                           default='https://ui-avatars.com/api/?name=User&background=0d6efd&color=fff')
    projects = db.relationship('Project', secondary=project_users, backref=db.backref('users', lazy='dynamic'))

# --- PROJEKT ---
class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    domain = db.Column(db.String(100))
    product_feed_url = db.Column(db.String(500), nullable=True)
    last_feed_sync = db.Column(db.DateTime, nullable=True)
    api_type = db.Column(db.String(50), nullable=True)  # np. 'SOTE'
    api_url = db.Column(db.String(500), nullable=True)
    api_user = db.Column(db.String(100), nullable=True)
    api_password = db.Column(db.String(255), nullable=True)
    project_prices = db.relationship('ProjectPrice', backref='project', lazy=True)

# --- DOSTAWCA (Globalny) ---
class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    products = db.relationship('Product', backref='supplier', lazy=True)

# --- PRODUKT (BAZA GLOBALNA) ---
class Product(db.Model):
    sku = db.Column(db.String(64), primary_key=True)
    sellassist_id = db.Column(db.String(64), unique=True, nullable=True)
    sote_id = db.Column(db.Integer, nullable=True)        # ID produktu nadrzędnego
    sote_option_id = db.Column(db.Integer, nullable=True) # ID konkretnego wariantu (jeśli istnieje)

    title = db.Column(db.String(200), nullable=False)
    producer = db.Column(db.String(128), nullable=True)
    ean = db.Column(db.String(32), nullable=True)
    stock = db.Column(db.Integer, default=0) # Fizyczny stan magazynowy
    supplier_sku = db.Column(db.String(100), nullable=True) # ID u dostawcy
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    
    currency = db.Column(db.String(10), default='PLN')
    vat_rate = db.Column(db.Integer, default=23)
    
    sote_current_price_gross = db.Column(db.Float, nullable=True) # Aktualna cena brutto w sklepie

    purchase_price_net_currency = db.Column(db.Float, nullable=True) # W walucie
    catalog_price_net_currency = db.Column(db.Float, nullable=True)
    
    last_nexo_price_net = db.Column(db.Float, nullable=True)
    last_nexo_price_gross = db.Column(db.Float, nullable=True)

# --- CENY W SKLEPACH (TABELA PROJEKTOWA) ---
class ProjectPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    sku = db.Column(db.String(50), db.ForeignKey('product.sku'), nullable=False)
    
    status = db.Column(db.String(50), default='Aktywny')
    target_price_gross = db.Column(db.Float, nullable=True) # Cena brutto w SOTE
    target_price_strike = db.Column(db.Float, nullable=True) # Cena przekreślona
    min_margin_percent = db.Column(db.Float, default=10.0)

# --- CACHE SOTE (ZASILANE PRZEZ API) ---
class StoreCache(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    sku = db.Column(db.String(50), db.ForeignKey('product.sku'), nullable=False)
    
    stock_quantity = db.Column(db.Integer, default=0) # Stan magazynowy
    current_store_price = db.Column(db.Float, nullable=True) # Do Optimistic Locking
    last_sync = db.Column(db.DateTime, default=get_current_time)

# --- KOMPONENTY ZESTAWÓW (Relacja wiele-do-wielu) ---
class BundleComponent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bundle_sku = db.Column(db.String(50), db.ForeignKey('product.sku'), nullable=False)
    component_sku = db.Column(db.String(50), db.ForeignKey('product.sku'), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    
    # Opcjonalnie relacje, jeśli chcesz łatwo wyciągać składniki
    bundle = db.relationship('Product', foreign_keys=[bundle_sku], backref='components')
    component = db.relationship('Product', foreign_keys=[component_sku])

# --- HISTORIA ZMIAN CEN (Audyt) ---
class PriceLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    sku = db.Column(db.String(50), db.ForeignKey('product.sku'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Kto zmienił
    
    old_price = db.Column(db.Float, nullable=True)
    new_price = db.Column(db.Float, nullable=True)
    change_date = db.Column(db.DateTime, default=get_current_time)
    reason = db.Column(db.String(255), nullable=True) # np. 'Aktualizacja Excel' albo 'Ręczna zmiana'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- ROUTING I LOGIKA ---
@app.route('/')
@login_required
def home():
    return redirect(url_for('projects'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('projects'))
        else:
            flash('Błędny email lub hasło.', category='error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# --- OBSŁUGA BŁĘDÓW ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


# --- ROUTING PROJEKTÓW ---
@app.route('/projects')
@login_required
def projects():
    user_projects = current_user.projects
    return render_template('project_list.html', projects=user_projects)

@app.route('/create_project', methods=['GET', 'POST'])
@login_required
def create_project():
    if request.method == 'POST':
        name = request.form.get('name')
        domain = request.form.get('domain')
        
        # Opcjonalne dane do integracji z SOTE
        api_url = request.form.get('api_url')
        api_user = request.form.get('api_user')
        api_password = request.form.get('api_password')

        if not name:
            flash('Nazwa projektu jest wymagana.', 'error')
            return redirect(url_for('create_project'))

        # Tworzenie nowego obiektu Projektu
        new_project = Project(
            name=name,
            domain=domain,
            api_type='SOTE', # Domyślnie ustawiamy na SOTE dla MVP
            api_url=api_url,
            api_user=api_user,
            api_password=api_password
        )
        
        # Zapisz w bazie
        db.session.add(new_project)
        db.session.commit()
        
        # Powiąż projekt z zalogowanym użytkownikiem
        new_project.users.append(current_user)
        db.session.commit()

        flash(f'Projekt "{name}" został pomyślnie utworzony!', 'success')
        return redirect(url_for('projects'))

    return render_template('create_project.html')

@app.route('/delete_project/<int:project_id>', methods=['POST'])
@login_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    
    # Zabezpieczenie: tylko przypisany użytkownik może usunąć projekt
    if current_user not in project.users:
        flash('Brak uprawnień do usunięcia tego projektu.', 'error')
        return redirect(url_for('projects'))

    try:
        # Usuwamy powiązane rekordy z bazy projektowej (Ceny i Cache SOTE)
        ProjectPrice.query.filter_by(project_id=project.id).delete()
        StoreCache.query.filter_by(project_id=project.id).delete()
        
        # Usuwamy sam projekt
        db.session.delete(project)
        db.session.commit()
        
        flash(f'Projekt "{project.name}" został pomyślnie usunięty.', 'success')
    except Exception as e:
        db.session.rollback() # W razie błędu cofamy transakcję
        logger.error(f"Błąd podczas usuwania projektu {project_id}: {str(e)}")
        flash(f'Wystąpił błąd podczas usuwania projektu: {str(e)}', 'error')

    return redirect(url_for('projects'))

# --- SYNCHRONIZACJA Z SELLASSIST (Katalog Produktów) ---
@app.route('/sync_sellassist', methods=['GET', 'POST'])
@login_required
def sync_sellassist():
    api_key = os.getenv("SELLASSIST_API_KEY")
    api_url = os.getenv("SELLASSIST_API_URL")

    if not api_key or not api_url:
        flash("Brak konfiguracji API SellAssist w pliku .env!", "error")
        return redirect(url_for('projects'))

    headers = {
        "Accept": "application/json",
        "apikey": api_key
    }

    # Pobieramy paczkę produktów
    params = {"limit": 300}

    try:
        response = requests.get(api_url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            products_list = data if isinstance(data, list) else data.get('products', [])
            
            added = 0
            updated = 0

            for item in products_list:
                sku = item.get('symbol')
                if not sku:
                    continue  # Pomijamy produkty bez SKU
                    
                sku = str(sku).strip()
                title = str(item.get('name', '')).strip()
                currency = str(item.get('currency', 'PLN')).strip()
                
                # --- ZMIANA: Wyciągamy z API wewnętrzne ID SellAssista (np. "1540") ---
                sa_id = item.get('id')
                sellassist_id = str(sa_id).strip() if sa_id else None

                # Sprawdzamy, czy produkt z tym SKU już istnieje w naszej bazie SQLite
                product = Product.query.filter_by(sku=sku).first()

                if not product:
                    # Tworzymy nowy produkt i od razu przypisujemy mu sellassist_id
                    product = Product(
                        sku=sku,
                        sellassist_id=sellassist_id,  # <-- TUTAJ ZAPISUJEMY ID
                        title=title,
                        currency=currency
                    )
                    db.session.add(product)
                    added += 1
                else:
                    # Jeśli produkt już istniał, dopisujemy mu ID (uzupełniamy bazę)
                    product.sellassist_id = sellassist_id  # <-- TUTAJ AKTUALIZUJEMY ID
                    product.title = title
                    product.currency = currency
                    updated += 1

            # Zapisujemy wszystko do bazy za jednym zamachem
            db.session.commit()
            flash(f"Pobrano katalog z SellAssist! Nowe: {added}, Zaktualizowane: {updated}.", "success")
            
        else:
            logger.error(f"SellAssist API HTTP {response.status_code}: {response.text}")
            flash(f"Błąd pobierania danych z SellAssist: Kod {response.status_code}", "error")

    except Exception as e:
        db.session.rollback()  # W razie błędu - cofamy zmiany
        logger.error(f"Błąd synchronizacji SellAssist: {str(e)}")
        flash(f"Wystąpił błąd serwera podczas synchronizacji: {str(e)}", "error")

    return redirect(url_for('projects'))

@app.route('/project/<int:project_id>/api/products')
@login_required
def api_project_products(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user not in project.users:
        return jsonify({"error": "Brak dostępu"}), 403

    products = Product.query.all()
    
    # 1. Separujemy produkty główne od wariantów
    roots = []
    variants_by_parent = {}
    
    for p in products:
        if p.sote_option_id is not None:
            if p.sote_id not in variants_by_parent:
                variants_by_parent[p.sote_id] = []
            variants_by_parent[p.sote_id].append(p)
        else:
            roots.append(p)
            
    # 2. Sortujemy główne produkty alfabetycznie
    roots.sort(key=lambda x: x.title.lower() if x.title else "")
    
    # 3. Budujemy ostateczną listę
    data = []
    for root in roots:
        data.append({
            "sku": root.sku,
            "title": root.title,
            "producer": root.producer or "",
            # POPRAWKA: Bezpieczne odwołanie do relacji Supplier
            "supplier_name": root.supplier.name if root.supplier else "",
            "supplier_sku": root.supplier_sku or "",
            "status": "Zsynchronizowano",
            "stock_quantity": root.stock,
            "currency": root.currency or "PLN",
            "vat_rate": root.vat_rate or 23,
            "purchase_price_net_currency": root.purchase_price_net_currency,
            "catalog_price_net_currency": root.catalog_price_net_currency,
            "last_nexo_price_net": root.last_nexo_price_net,
            "last_nexo_price_gross": root.last_nexo_price_gross,
            "target_price_gross": root.sote_current_price_gross,
            "margin_pln": None,
            "margin_percent": None,
            "is_variant": False,
            "sote_id": root.sote_id
        })
        
        if root.sote_id and root.sote_id in variants_by_parent:
            variants = sorted(variants_by_parent[root.sote_id], key=lambda v: v.title if v.title else "")
            for var in variants:
                data.append({
                    "sku": var.sku,
                    "title": var.title,
                    "producer": var.producer or "",
                    # POPRAWKA: Bezpieczne odwołanie do relacji Supplier
                    "supplier_name": var.supplier.name if var.supplier else "",
                    "supplier_sku": var.supplier_sku or "",
                    "status": "Wariant",
                    "stock_quantity": var.stock,
                    "currency": var.currency or "PLN",
                    "vat_rate": var.vat_rate or 23,
                    "purchase_price_net_currency": var.purchase_price_net_currency,
                    "catalog_price_net_currency": var.catalog_price_net_currency,
                    "last_nexo_price_net": var.last_nexo_price_net,
                    "last_nexo_price_gross": var.last_nexo_price_gross,
                    "target_price_gross": var.sote_current_price_gross,
                    "margin_pln": None,
                    "margin_percent": None,
                    "is_variant": True,
                    "sote_id": var.sote_id
                })
                
    return jsonify({"products": data})

@app.route('/project/<int:project_id>/overview')
@login_required
def project_overview(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user not in project.users:
        flash('Brak dostępu.', 'error')
        return redirect(url_for('projects'))
    
    # Docelowo tu zbudujemy kokpit z wykresami marż.
    # Na razie dla MVP przekierowujemy od razu do bazy cenników (AG Grid).
    return redirect(url_for('project_dashboard', project_id=project.id))

@app.route('/project/<int:project_id>/products')
@login_required
def project_dashboard(project_id):
    project = Project.query.get_or_404(project_id)
    
    if current_user not in project.users:
        flash('Brak dostępu.', 'error')
        return redirect(url_for('projects'))
        
    session[f'dashboard_url_{project_id}'] = request.full_path
    
    # Pobieramy ceny (ProjectPrice) połączone z danymi globalnymi (Product)
    # Na razie przekazujemy tylko sam obiekt project, ponieważ dane do 
    # AG Grida będziemy dociągać dynamicznie przez dedykowane API (JSON)
    
    return render_template('products.html', project=project)

# --- PODSTRONA: PODGLĄD ZESTAWÓW ---
@app.route('/project/<int:project_id>/bundles')
@login_required
def project_bundles(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user not in project.users:
        flash('Brak dostępu.', 'error')
        return redirect(url_for('projects'))
    
    # Pobieramy wszystkie relacje składników z bazy
    components = BundleComponent.query.all()
    
    # Grupujemy relacje po SKU zestawu (Rodzica)
    bundles_dict = {}
    for c in components:
        if c.bundle_sku not in bundles_dict:
            # Szukamy nazwy produktu-rodzica w bazie globalnej
            bundle_prod = Product.query.filter_by(sku=c.bundle_sku).first()
            bundles_dict[c.bundle_sku] = {
                'product': bundle_prod,
                'components': []
            }
            
        # Szukamy nazwy produktu-składnika (dziecka)
        comp_prod = Product.query.filter_by(sku=c.component_sku).first()
        bundles_dict[c.bundle_sku]['components'].append({
            'sku': c.component_sku,
            'title': comp_prod.title if comp_prod else "Produkt nieznany (brak w bazie globalnej)",
            'quantity': c.quantity
        })
        
    return render_template('bundles.html', project=project, bundles=bundles_dict)

@app.route('/project/<int:project_id>/sote-variants')
@login_required
def sote_variants(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user not in project.users:
        flash('Brak dostępu.', 'error')
        return redirect(url_for('projects'))
        
    # Pobieramy z bazy globalnej tylko te produkty, które mają nadane ID z SOTE
    sote_products = Product.query.filter(Product.sote_id.isnot(None)).all()
    
    # Grupujemy produkty po nadrzędnym sote_id
    variants_dict = {}
    for p in sote_products:
        sid = p.sote_id
        if sid not in variants_dict:
            variants_dict[sid] = {'main': None, 'variants': []}
        
        # Jeśli nie ma sote_option_id, to jest to produkt główny (rodzic)
        if p.sote_option_id is None:
            variants_dict[sid]['main'] = p
        else:
            # W przeciwnym wypadku to jest wariant (dziecko)
            variants_dict[sid]['variants'].append(p)
            
    # --- TO DODAJEMY: Filtrujemy słownik, zostawiając TYLKO te wpisy, które mają warianty ---
    filtered_dict = {sid: data for sid, data in variants_dict.items() if len(data['variants']) > 0}
            
    return render_template('sote_variants.html', project=project, variants_dict=filtered_dict)

# --- SYNCHRONIZACJA ZESTAWÓW (Z SellAssist do SQLite) ---
@app.route('/project/<int:project_id>/sync-bundles')
@login_required
def sync_bundles(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user not in project.users:
        flash('Brak dostępu.', 'error')
        return redirect(url_for('projects'))

    api_key = os.getenv("SELLASSIST_API_KEY")
    base_url = "https://arante.sellasist.pl/api/v1"
    
    headers = {
        "Accept": "application/json",
        "apikey": api_key
    }

    try:
        response = requests.get(f"{base_url}/sets_bulk", headers=headers)
        
        if response.status_code != 200:
            flash(f"Błąd API SellAssist: Kod {response.status_code}", "error")
            return redirect(url_for('project_bundles', project_id=project.id))

        bundle_data = response.json()
        
        # Czyścimy stare powiązania, aby uniknąć duplikatów przy ponownym kliknięciu
        BundleComponent.query.delete()
        
        saved_count = 0
        skipped_count = 0

        for item in bundle_data:
            main_id = str(item.get('main_product_id'))
            component_sku = item.get('product_symbol')
            quantity = float(item.get('quantity', 1.0))

            # Mapujemy wewnętrzne ID SellAssista na SKU z naszej bazy globalnej
            parent_product = Product.query.filter_by(sellassist_id=main_id).first()

            if parent_product and component_sku:
                new_component = BundleComponent(
                    bundle_sku=parent_product.sku,
                    component_sku=component_sku,
                    quantity=quantity
                )
                db.session.add(new_component)
                saved_count += 1
            else:
                skipped_count += 1

        db.session.commit()
        flash(f"Zsynchronizowano zestawy! Zapisano {saved_count} relacji składników.", "success")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Błąd podczas syncu zestawów: {str(e)}")
        flash(f"Wystąpił błąd serwera podczas synchronizacji: {str(e)}", "error")

    # Po zakończeniu syncu przekierowujemy użytkownika od razu na podstronę zestawów, by widział efekt
    return redirect(url_for('project_bundles', project_id=project.id))

@app.route('/project/<int:project_id>/sync-sote')
@login_required
def sync_sote_options(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user not in project.users:
        flash('Brak dostępu.', 'error')
        return redirect(url_for('projects'))

    # Sprawdzamy czy projekt ma wpisane dane do SOTE
    if not project.api_url or not project.api_user or not project.api_password:
        flash("Uzupełnij dane dostępowe do SOTE w ustawieniach projektu!", "error")
        return redirect(url_for('project_dashboard', project_id=project.id))

    WSDL_LOGIN = f"{project.api_url}/webapi/soap?wsdl"
    WSDL_PRODUCT = f"{project.api_url}/product/soap?wsdl"

    try:
        # 1. Logowanie do SOTE
        client_login = Client(WSDL_LOGIN)
        login_type = client_login.get_type("ns0:doLogin")
        session_hash = client_login.service.doLogin(login_type(
            _culture="pl", 
            username=project.api_user, 
            password=project.api_password
        ))
        
        # 2. Pobieranie głównej listy produktów
        client_product = Client(WSDL_PRODUCT)
        get_list_type = client_product.get_type("ns0:GetProductList")
        products_response = client_product.service.GetProductList(get_list_type(_session_hash=session_hash))
        
        products = serialize_object(products_response)
        if not isinstance(products, list):
            products = [products]

        updated_main = 0
        updated_options = 0

        # 3. Iteracja i mapowanie do SQLite
        for p in products:
            p_id = p.get('id')
            p_code = p.get('code')
            
            # Mapowanie produktu płaskiego (bez opcji)
            if p_code:
                db_prod = Product.query.filter_by(sku=p_code).first()
                if db_prod:
                    db_prod.sote_id = p_id
                    updated_main += 1

            # Sprawdzanie opcji (wariantów)
            try:
                get_options_type = client_product.get_type("ns0:GetProductOptionsList")
                options_response = client_product.service.GetProductOptionsList(
                    get_options_type(_session_hash=session_hash, product_id=p_id)
                )
                
                if options_response:
                    options = serialize_object(options_response)
                    if not isinstance(options, list):
                        options = [options]
                        
                    for opt in options:
                        opt_id = opt.get('id')
                        opt_code = opt.get('code') or opt.get('sku') or opt.get('name')
                        
                        if opt_code:
                            # Szukamy tego wariantu w naszej bazie po SKU
                            db_opt = Product.query.filter_by(sku=opt_code).first()
                            if db_opt:
                                db_opt.sote_id = p_id          # ID rodzica z SOTE
                                db_opt.sote_option_id = opt_id # Własne ID wariantu
                                updated_options += 1
            except Exception as e:
                logger.error(f"Błąd przy pobieraniu opcji dla produktu SOTE {p_id}: {e}")
                continue

        db.session.commit()
        flash(f"Zmapowano z SOTE! Produkty główne: {updated_main}, Warianty: {updated_options}.", "success")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Błąd synchronizacji SOTE: {e}")
        flash(f"Błąd komunikacji z SOTE SOAP: {e}", "error")

    return redirect(url_for('project_dashboard', project_id=project.id))

# TWORZENIE ADMINA - inicjalizacja tylko przy pierwszym uruchomieniu
@app.route('/create-admin')
def create_admin():
    db.create_all()
    email = os.getenv('ADMIN_EMAIL')
    password = os.getenv('ADMIN_PASSWORD')

    if not email or not password:
        return "Błąd: Brak danych admina w pliku .env!"
    if not User.query.filter_by(email=email).first():
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return f"Stworzono admina ({email})! Teraz możesz się zalogować."
    return "Admin już istnieje."


# --- REJESTRACJA WIDOKÓW W FLASK-ADMIN ---
admin.add_view(UserModelView(User, db.session, name='Użytkownicy'))
admin.add_view(ProjectModelView(Project, db.session, name='Projekty'))
# admin.add_view(ProductModelView(Product, db.session, name='Produkty'))
admin.add_view(ProductAdminView(Product, db.session))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(host='0.0.0.0', port=5005, debug=True, use_reloader=False)