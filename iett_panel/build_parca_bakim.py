"""
build_parca_bakim.py
-------------------
Arıza + Sefer CSV'lerinden araç bazlı parça bakım takvimi üretir.

Çıktılar:
  panel_data/parca_bakim.json    — her araç için parça durumu
  panel_data/bakim_takvimi.json  — garaj kapasiteli yığılmaz bakım takvimi

Çalıştır: python build_parca_bakim.py
"""

import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from datetime import date, timedelta
from math import ceil
from collections import defaultdict
import pandas as pd

# ─── YOLLAR ──────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(sys.argv[0]))
PANEL_DIR = os.path.join(BASE_DIR, '..', 'Datathon', 'panel_data')
ARIZA_CSV = r'C:\Users\asus\Desktop\Datathon\ARIZA\DATA\ariza_temiz.csv'
SEFER_CSV = r'C:\Users\asus\Desktop\Datathon\SEFER\DATA\sefer_temiz.csv'

REF_DATE     = date(2025, 7, 1)   # Takvim başlangıcı (veri sonu + 1 gün)
WINDOW_DAYS  = 90                  # Kaç günlük takvim oluşturulsun

# ─── PARÇA TANIMLARI ─────────────────────────────────────────────────────────
# guven_sonuclar: hangi SONUCTIPI değerleri parça değişimini garantiler
GUVEN_YUKSEK = {'Çekilerek - Garaj', 'Yol Ustası - Garaj', 'Telefonla - Garaj', 'Kayıt Dışı - Garaj'}
GUVEN_ORTA   = {'Yol Ustası - Servis', 'Telefonla - Servis'}

PARCA_TANIM = {
    'AKÜ': {
        'label': 'Akü',
        'kodlar': {'AKÜ ARIZASI', 'ALTERNATİF AKÜ\'YÜ ŞARJ ETMİYOR',
                   'ALTERNATÖR AKÜ\'YÜ ŞARJ ETMİYOR'},
        'ust_katlar': {'ELEKTRİK SİSTEMİ ARIZALARI'},
        'km_omur': 60000, 'ay_omur': 24,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'elektrik', 'ikon': '🔋',
    },
    'MARŞ': {
        'label': 'Marş Motoru',
        'kodlar': {'MARŞ MOTORU ÇALIŞMIYOR'},
        'ust_katlar': {'ELEKTRİK SİSTEMİ ARIZALARI'},
        'km_omur': 80000, 'ay_omur': 36,
        'min_guven': GUVEN_YUKSEK,
        'kategori': 'elektrik', 'ikon': '⚡',
    },
    'SİGORTA': {
        'label': 'Sigorta/Röle',
        'kodlar': {'SİGORTA DEĞİŞİMİ'},
        'ust_katlar': {'ELEKTRİK SİSTEMİ ARIZALARI'},
        'km_omur': None, 'ay_omur': 12,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'elektrik', 'ikon': '💡',
    },
    'KAYIŞ': {
        'label': 'Kayış/Kasnak',
        'kodlar': {'KAYIŞ ARIZASI'},
        'ust_katlar': {'KAYIŞ KASNAK ARIZALARI'},
        'km_omur': 40000, 'ay_omur': 18,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'motor', 'ikon': '⚙️',
    },
    'ŞANZIMAN': {
        'label': 'Şanziman',
        'kodlar': {'ŞANZIMAN ARIZASI', 'VİTESLERE GEÇİŞTE VURUNTU YAPIYOR'},
        'ust_katlar': {'OTOMATİK ŞANZIMAN ARIZALARI'},
        'km_omur': 100000, 'ay_omur': 48,
        'min_guven': GUVEN_YUKSEK,
        'kategori': 'aktarma', 'ikon': '🔧',
    },
    'FREN': {
        'label': 'Fren/Balata',
        'kodlar': {'FRENLER SIKIYOR', 'RETARDER FRENLEMESİ ZAYIF-ÇALIŞMIYOR',
                   'ABS - ASR ARIZASI'},
        'ust_katlar': {'FREN ŞİKAYETLERİ'},
        'km_omur': 30000, 'ay_omur': 12,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'fren', 'ikon': '🛑',
    },
    'SOĞUTMA': {
        'label': 'Soğutma Sistemi',
        'kodlar': {'HARARET YÜKSELİYOR', 'SU HORTUMU PATLAK',
                   'SU BORUSU VE HORTUMLARI', 'HARARET VE SU EKSİK',
                   'SU EKSİK'},
        'ust_katlar': {'SOĞUTMA SİSTEMİ ARIZASI'},
        'km_omur': 50000, 'ay_omur': 24,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'motor', 'ikon': '🌡️',
    },
    'KLİMA': {
        'label': 'Klima',
        'kodlar': {'KLİMA SOĞUTMUYOR', 'KLİMA ÇALIŞMIYOR'},
        'ust_katlar': {'KLİMA SİSTEMİ ARIZALARI'},
        'km_omur': 20000, 'ay_omur': 12,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'iklimlendirme', 'ikon': '❄️',
    },
    'KALORİFER': {
        'label': 'Kalorifer',
        'kodlar': {'KALORİFER ÇALIŞMIYOR', 'KALORİFER ISITMIYOR'},
        'ust_katlar': {'ISITMA SİSTEMİ'},
        'km_omur': None, 'ay_omur': 18,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'iklimlendirme', 'ikon': '🔥',
    },
    'KAPI': {
        'label': 'Kapı Sistemi',
        'kodlar': {'KAPI DONANIM HATASI', 'KAPI BEYNİ ARIZALI',
                   'KAPI HAVA KAÇAĞI ARIZASI'},
        'ust_katlar': {'KAPI ARIZALARI'},
        'km_omur': None, 'ay_omur': 18,
        'min_guven': GUVEN_YUKSEK,
        'kategori': 'karoser', 'ikon': '🚪',
    },
    'KÖRÜK': {
        'label': 'Körük/Süspansiyon',
        'kodlar': {'KÜRÜKLER AYARSIZ', 'SÜVİYE DÜZENLEME YAPMIYOR'},
        'ust_katlar': {'SÜSPANSİYON SİSTEMİ ARIZALARI'},
        'km_omur': 60000, 'ay_omur': 30,
        'min_guven': GUVEN_YUKSEK,
        'kategori': 'süspansiyon', 'ikon': '🔩',
    },
    'AKBİL': {
        'label': 'AKBİL/Validatör',
        'kodlar': set(),
        'ust_katlar': {'AKBİL ARIZALARI'},
        'km_omur': None, 'ay_omur': 24,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'elektronik', 'ikon': '💳',
    },
    'TABELA': {
        'label': 'Dijital Tabela',
        'kodlar': {'DİGİTAL TABELA ARIZALARI'},
        'ust_katlar': set(),
        'km_omur': None, 'ay_omur': 24,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'elektronik', 'ikon': '📺',
    },
    'HİDROLİK': {
        'label': 'Yağ/Hidrolik Sistemi',
        'kodlar': {'YAĞ KAÇAĞI'},
        'ust_katlar': {'BASINÇLI MOTOR YAĞI SİSTEMİ'},
        'km_omur': 30000, 'ay_omur': 12,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'motor', 'ikon': '🛢️',
    },
    'MOTOR': {
        'label': 'Motor',
        'kodlar': {'GAZ YEMİYOR', 'MOTOR AYARLAMA DEVRE DIŞI ARIZASI',
                   'OTO ÇEKMIYOR'},
        'ust_katlar': {'MOTOR ARIZALARI'},
        'km_omur': None, 'ay_omur': 36,
        'min_guven': GUVEN_YUKSEK,
        'kategori': 'motor', 'ikon': '🔩',
    },
    'PNÖMATİK': {
        'label': 'Pnömatik/Hava Sistemi',
        'kodlar': {'HAVA KAÇAĞI-BORU PATLAK', 'HAVALAR DÜŞÜYOR'},
        'ust_katlar': {'BASINÇLI HAVA DONANIMI ARIZALARI'},
        'km_omur': 40000, 'ay_omur': 24,
        'min_guven': GUVEN_YUKSEK | GUVEN_ORTA,
        'kategori': 'pnömatik', 'ikon': '💨',
    },
}

# Periyodik bakımlar — arıza kaydından bağımsız, sadece km bazlı
PERIYODIK = [
    {'parca': 'MOTOR YAĞI',     'label': 'Motor Yağı Değişimi', 'km_aralik': 15000, 'ikon': '🛢️'},
    {'parca': 'YAKIT FİLTRESİ','label': 'Yakıt Filtresi',       'km_aralik': 20000, 'ikon': '⛽'},
    {'parca': 'HAVA FİLTRESİ', 'label': 'Hava Filtresi',        'km_aralik': 20000, 'ikon': '🌬️'},
]

# Mevsimsel bakımlar — takvim bazlı tetikleyici (hangi ay yapılmalı)
MEVSIM = [
    {'parca': 'KIŞ LASTİK',      'label': 'Kışlık Lastik',      'ay': 10, 'ikon': '❄️'},
    {'parca': 'YAZ LASTİK',      'label': 'Yazlık Lastik',       'ay': 4,  'ikon': '☀️'},
    {'parca': 'KLİMA BAKIMI',    'label': 'Klima Yıllık Bakımı', 'ay': 4,  'ikon': '❄️'},
    {'parca': 'KALORİFER BAKIM','label': 'Kalorifer Bakımı',     'ay': 9,  'ikon': '🔥'},
    {'parca': 'ANTİFRİZ KIŞ',   'label': 'Antifriz (Kış)',      'ay': 10, 'ikon': '🧊'},
    {'parca': 'ANTİFRİZ YAZ',   'label': 'Antifriz (Yaz)',      'ay': 3,  'ikon': '💧'},
]


# ─── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────────
def hesapla_durum(birikim_km, omur_km, gecen_gun, omur_gun):
    """Kullanım yüzdesine göre durum döndürür."""
    pcts = []
    if omur_km and birikim_km is not None:
        pcts.append(birikim_km / omur_km)
    if omur_gun and gecen_gun is not None:
        pcts.append(gecen_gun / omur_gun)
    if not pcts:
        return 'BELİRSİZ', None
    pct = max(pcts)
    if pct >= 1.0:   return 'ACİL',       round(pct * 100)
    if pct >= 0.75:  return 'YAKLAŞIYOR', round(pct * 100)
    if pct >= 0.40:  return 'NORMAL',     round(pct * 100)
    return 'YENİ', round(pct * 100)


def mevsim_durumu(ay_hedef, ref):
    """Mevsimsel bakımın ne zaman yapılması gerektiğini hesaplar."""
    hedef = date(ref.year, ay_hedef, 1)
    if hedef < ref:
        hedef = date(ref.year + 1, ay_hedef, 1)
    fark_gun = (hedef - ref).days
    if fark_gun <= 14:   return 'ACİL',       fark_gun
    if fark_gun <= 45:   return 'YAKLAŞIYOR', fark_gun
    return 'NORMAL', fark_gun


# ─── VERİ OKUMA ──────────────────────────────────────────────────────────────
print("📂 Arıza verisi okunuyor...")
ariza_cols = ['KAPINO', 'OLAYTARIHI', 'ARIZAKODU', 'ARIZAUSTKODTANIM',
              'SONUCTIPI', 'GARAJADI']
ariza = pd.read_csv(ARIZA_CSV, encoding='utf-8-sig', usecols=ariza_cols,
                    low_memory=False)
ariza['OLAYTARIHI'] = pd.to_datetime(ariza['OLAYTARIHI'], errors='coerce').dt.date
ariza = ariza.dropna(subset=['KAPINO', 'OLAYTARIHI'])
ariza['KAPINO']          = ariza['KAPINO'].astype(str).str.strip()
ariza['ARIZAKODU']       = ariza['ARIZAKODU'].fillna('').str.strip()
ariza['ARIZAUSTKODTANIM']= ariza['ARIZAUSTKODTANIM'].fillna('').str.strip()
ariza['SONUCTIPI']       = ariza['SONUCTIPI'].fillna('').str.strip()
ariza['GARAJADI']        = ariza['GARAJADI'].fillna('').str.strip()
print(f"   ✅ {len(ariza):,} arıza kaydı, {ariza['KAPINO'].nunique():,} araç")

# Araç → garaj eşlemesi (en sık görülen garaj)
arac_garaj = (ariza[ariza['GARAJADI'] != '']
              .groupby('KAPINO')['GARAJADI']
              .agg(lambda x: x.value_counts().index[0])
              .to_dict())

print("🚌 Sefer/km verisi okunuyor (büyük dosya)...")
sefer_chunks = []
for chunk in pd.read_csv(SEFER_CSV, encoding='utf-8-sig', low_memory=False,
                          chunksize=100000,
                          usecols=['KAPINO', 'TARIH', 'GERCEKLESENGUZERGAHUZUNLUK']):
    chunk['KAPINO'] = chunk['KAPINO'].astype(str).str.strip()
    sefer_chunks.append(chunk)
sefer = pd.concat(sefer_chunks)
sefer['TARIH'] = pd.to_datetime(sefer['TARIH'], errors='coerce').dt.date
sefer = sefer.dropna(subset=['KAPINO', 'TARIH'])
sefer['km'] = sefer['GERCEKLESENGUZERGAHUZUNLUK'].fillna(0) / 1000  # metre → km

# Araç + tarih bazlı günlük km
print("   Günlük km hesaplanıyor...")
gunluk = (sefer.groupby(['KAPINO', 'TARIH'])['km']
               .sum()
               .reset_index())
gunluk.columns = ['kapino', 'tarih', 'km']

# Son mevcut tarih
SON_TARIH = gunluk['tarih'].max()
print(f"   ✅ {len(sefer):,} sefer kaydı | Son tarih: {SON_TARIH}")

# Araç başına günlük km lookup: {kapino: {tarih: km}}
print("   Araç km lookup oluşturuluyor...")
arac_km_lookup = defaultdict(dict)
for row in gunluk.itertuples(index=False):
    arac_km_lookup[row.kapino][row.tarih] = row.km

# Araç başına ortalama günlük km (sefer olmayan günler için fallback)
arac_km_ort = gunluk.groupby('kapino')['km'].mean().to_dict()

print("   ✅ KM lookup hazır")


def km_birikim(kapino, baslangic_tarih):
    """Başlangıç tarihinden SON_TARIH'e kadar gerçek kümülatif km."""
    lookup = arac_km_lookup.get(kapino, {})
    toplam = 0.0
    t = baslangic_tarih
    while t <= SON_TARIH:
        toplam += lookup.get(t, 0.0)
        t += timedelta(days=1)
    return round(toplam, 1)


# ─── PARÇA DURUMU HESAPLAMA ──────────────────────────────────────────────────
print("\n🔧 Parça bakım durumları hesaplanıyor...")

tum_kapinolar = ariza['KAPINO'].unique()
parca_bakim   = {}

for i, kapino in enumerate(tum_kapinolar):
    if i % 500 == 0:
        print(f"   {i}/{len(tum_kapinolar)} araç işlendi...")

    arac_ariza = ariza[ariza['KAPINO'] == kapino]
    garaj      = arac_garaj.get(kapino, 'BELİRSİZ')
    km_ort     = round(arac_km_ort.get(kapino, 150.0), 1)  # 150 km/gün default

    kayit = {
        '_garaj':      garaj,
        '_km_ort':     km_ort,
        '_parcalar':   [],   # Bakım gereken parça adları (takvim için)
        '_mevsim':     [],
        '_periyodik':  [],
    }

    # ── Parça bazlı hesaplama ─────────────────────────────────────────────
    # Araç toplam km tahmini (başlangıçtan SON_TARIH'e kadar)
    arac_toplam_km = sum(arac_km_lookup.get(kapino, {}).values())

    for parca_adi, tanim in PARCA_TANIM.items():
        # Bu parçayla ilgili yüksek güvenli arızaları filtrele
        eslesme = (
            arac_ariza['ARIZAKODU'].isin(tanim['kodlar']) |
            arac_ariza['ARIZAUSTKODTANIM'].isin(tanim.get('ust_katlar', set()))
        ) & arac_ariza['SONUCTIPI'].isin(tanim['min_guven'])

        gecmis = arac_ariza[eslesme].sort_values('OLAYTARIHI', ascending=False)

        if gecmis.empty:
            continue  # Bu parça için kayıt yok, gösterme

        son_tarih = gecmis.iloc[0]['OLAYTARIHI']
        gecen_gun = (SON_TARIH - son_tarih).days

        # Gerçek kümülatif km (son servis tarihinden itibaren)
        birikim   = km_birikim(kapino, son_tarih)

        omur_km  = tanim['km_omur']
        omur_gun = tanim['ay_omur'] * 30 if tanim['ay_omur'] else None

        kalan_km  = (omur_km - birikim)  if omur_km  else None
        kalan_gun = (omur_gun - gecen_gun) if omur_gun else None

        durum, pct = hesapla_durum(birikim, omur_km, gecen_gun, omur_gun)

        kayit[parca_adi] = {
            'label':      tanim['label'],
            'ikon':       tanim['ikon'],
            'kategori':   tanim['kategori'],
            'son_tarih':  str(son_tarih),
            'gecen_gun':  gecen_gun,
            'birikim_km': birikim,
            'omur_km':    omur_km,
            'kalan_km':   round(kalan_km, 1) if kalan_km is not None else None,
            'omur_gun':   omur_gun,
            'kalan_gun':  kalan_gun,
            'kullanim_pct': pct,
            'durum':      durum,
            'kayit_sayisi': int(len(gecmis)),
        }

        if durum in ('ACİL', 'YAKLAŞIYOR'):
            kayit['_parcalar'].append(parca_adi)

    # ── Periyodik bakım ───────────────────────────────────────────────────
    for p in PERIYODIK:
        # Toplam km'ye göre kaçıncı bakım dönemi?
        if arac_toplam_km <= 0:
            continue
        gecmis_bakim = int(arac_toplam_km // p['km_aralik'])
        sonraki_km   = (gecmis_bakim + 1) * p['km_aralik']
        kalan_km     = round(sonraki_km - arac_toplam_km, 1)
        pct          = round((arac_toplam_km % p['km_aralik']) / p['km_aralik'] * 100)

        if pct >= 75:    durum = 'ACİL'
        elif pct >= 50:  durum = 'YAKLAŞIYOR'
        else:            durum = 'NORMAL'

        kayit['_periyodik'].append({
            'parca':      p['parca'],
            'label':      p['label'],
            'ikon':       p['ikon'],
            'kalan_km':   kalan_km,
            'sonraki_km': sonraki_km,
            'kullanim_pct': pct,
            'durum':      durum,
        })
        if durum in ('ACİL', 'YAKLAŞIYOR'):
            kayit['_parcalar'].append(p['parca'])

    # ── Mevsimsel bakım ───────────────────────────────────────────────────
    for m in MEVSIM:
        durum, kalan_gun = mevsim_durumu(m['ay'], REF_DATE)
        kayit['_mevsim'].append({
            'parca':     m['parca'],
            'label':     m['label'],
            'ikon':      m['ikon'],
            'ay':        m['ay'],
            'kalan_gun': kalan_gun,
            'durum':     durum,
        })
        if durum in ('ACİL', 'YAKLAŞIYOR'):
            kayit['_parcalar'].append(m['parca'])

    parca_bakim[kapino] = kayit

print(f"   ✅ {len(parca_bakim):,} araç işlendi")


# ─── BAKIM TAKVİMİ (YIĞILMAZ) ────────────────────────────────────────────────
print("\n📅 Bakım takvimi oluşturuluyor (yığılma önleme)...")

# Garaj kapasitesi: günde max araç sayısı
garaj_arac_sayisi = defaultdict(int)
for _, v in parca_bakim.items():
    g = v.get('_garaj', '')
    if g and 'BELİRSİZ' not in g:
        garaj_arac_sayisi[g] += 1

# Formül: küçük garaj min 3, büyük garaj filonun %5'i (max 15)
garaj_kapasite = {
    g: min(15, max(3, ceil(n * 0.05)))
    for g, n in garaj_arac_sayisi.items()
}

# Bakım listesi: sadece parçası olan araçlar, öncelik sırasıyla
gorevler = []
for kapino, v in parca_bakim.items():
    if not v['_parcalar']:
        continue
    garaj  = v.get('_garaj', '')

    # Acil seviye belirleme: en kötü parça durumuna göre
    durumlar = []
    for p in PARCA_TANIM:
        if p in v:
            durumlar.append(v[p]['durum'])
    for pp in v['_periyodik']:
        durumlar.append(pp['durum'])
    for mm in v['_mevsim']:
        durumlar.append(mm['durum'])

    oncelik = 0 if 'ACİL' in durumlar else (1 if 'YAKLAŞIYOR' in durumlar else 2)
    gorevler.append({
        'kapino':   kapino,
        'garaj':    garaj,
        'oncelik':  oncelik,
        'parcalar': list(set(v['_parcalar'])),
        'durum':    'ACİL' if oncelik == 0 else ('YAKLAŞIYOR' if oncelik == 1 else 'NORMAL'),
    })

gorevler.sort(key=lambda x: x['oncelik'])

# Takvim: {tarih: {garaj: [araç listesi]}}
takvim      = defaultdict(lambda: defaultdict(list))
arac_tarih  = {}  # kapino → atanan tarih

for g in gorevler:
    kapino = g['kapino']
    garaj  = g['garaj']
    if not garaj or 'BELİRSİZ' in garaj:
        continue

    kapasite = garaj_kapasite.get(garaj, 3)

    # Hafta içi tercihli slot bul (Pazartesi-Cuma)
    for day_off in range(WINDOW_DAYS):
        gun = REF_DATE + timedelta(days=day_off)
        if gun.weekday() >= 5:   # Cumartesi/Pazar atla (tercihe göre)
            continue
        tarih_str = str(gun)
        mevcut    = len(takvim[tarih_str][garaj])
        if mevcut < kapasite:
            takvim[tarih_str][garaj].append({
                'kapino':   kapino,
                'parcalar': g['parcalar'],
                'durum':    g['durum'],
            })
            arac_tarih[kapino] = tarih_str
            # Atanan tarihi parca_bakim'a ekle
            parca_bakim[kapino]['_planlanan_tarih'] = tarih_str
            break

# Dict'e çevir (JSON serileştirme için)
takvim_dict = {
    tarih: {garaj: araçlar for garaj, araçlar in garajlar.items()}
    for tarih, garajlar in takvim.items()
}

# Özet istatistikler
acil_say   = sum(1 for g in gorevler if g['durum'] == 'ACİL')
yaklasan   = sum(1 for g in gorevler if g['durum'] == 'YAKLAŞIYOR')
zamanli    = len(arac_tarih)
print(f"   🔴 ACİL: {acil_say} | 🟡 YAKLAŞIYOR: {yaklasan} | 📅 Zamanlandı: {zamanli}")


# ─── JSON KAYDET ─────────────────────────────────────────────────────────────
print("\n💾 JSON dosyaları kaydediliyor...")
os.makedirs(PANEL_DIR, exist_ok=True)

with open(os.path.join(PANEL_DIR, 'parca_bakim.json'), 'w', encoding='utf-8') as f:
    json.dump(parca_bakim, f, ensure_ascii=False, indent=None)
print("   ✅ parca_bakim.json")

with open(os.path.join(PANEL_DIR, 'bakim_takvimi.json'), 'w', encoding='utf-8') as f:
    json.dump(takvim_dict, f, ensure_ascii=False, indent=None)
print("   ✅ bakim_takvimi.json")

# Özet JSON (dashboard KPI için)
ozet = {
    'acil':      acil_say,
    'yaklasan':  yaklasan,
    'zamanli':   zamanli,
    'toplam_arac': len(parca_bakim),
    'ref_tarih': str(REF_DATE),
    'son_veri':  str(SON_TARIH),
    'garaj_kapasite': garaj_kapasite,
}
with open(os.path.join(PANEL_DIR, 'parca_bakim_ozet.json'), 'w', encoding='utf-8') as f:
    json.dump(ozet, f, ensure_ascii=False, indent=2)
print("   ✅ parca_bakim_ozet.json")

print(f"\n✅ Tamamlandı! {len(parca_bakim):,} araç, {len(takvim_dict)} günlük takvim hazır.")
