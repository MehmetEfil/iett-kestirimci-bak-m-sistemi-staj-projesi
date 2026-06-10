import os, sys, io
try:
    from dotenv import load_dotenv  # .env dosyasındaki kimlik bilgilerini yükler
    load_dotenv()
except ImportError:
    pass
from flask import Flask, render_template, request
import urllib.parse
from extensions import db

if (sys.stdout.encoding or "").lower() != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception as e:
        print(f"Encoding ayarlanamadi: {e}")

# Flask varsayilan olarak templates/ klasorune bakar — index.html oraya koy
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/panel/2025')
def panel_2025():
    return render_template('index.html')

@app.route('/panel/2025_q3')
@app.route('/panel/v6_5')
def panel_v6_5():
    return render_template('v6_5_tahminleme.html')

# Eski /panel/2026 rotasi V6.5'e yonlendiriyor (geriye uyumluluk)
@app.route('/panel/2026')
def panel_2026_redirect():
    from flask import redirect
    return redirect('/panel/v6_5', code=301)

@app.route('/panel/canli')
def panel_canli():
    return render_template('index.html')

# SQL Server adı makineye özeldir — .env dosyasından okunur (yalnız fallback SQL sorguları için; panel çoğunlukla JSON/CSV ile çalışır)
SUNUCU_ADI = os.environ.get("SQL_SERVER", r"localhost\SQLEXPRESS")
params = urllib.parse.quote_plus(
    f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SUNUCU_ADI};DATABASE=IETT_Analiz_Projesi;Trusted_Connection=yes;"
)
app.config['SQLALCHEMY_DATABASE_URI'] = "mssql+pyodbc:///?odbc_connect=%s" % params
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

from models import YolculukGecmisi
from services import *
from routes import register_routes
register_routes(app, db)

if __name__ == '__main__':
    start_background_threads()
    print("Baslatiliyor...")
    print("http://localhost:5000")
    app.run(port=5000, threaded=True, debug=False)