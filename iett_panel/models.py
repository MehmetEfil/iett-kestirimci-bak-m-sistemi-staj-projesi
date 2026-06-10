from extensions import db

# --- DOKÜMANA BİREBİR UYGUN TABLO TANIMLAMASI ---
class YolculukGecmisi(db.Model):
    __tablename__ = 'Ham_Yolculuk_Otoyol'
    
    # SQLAlchemy'nin okuma yapabilmesi için benzersiz kombinasyon (Composite PK)
    transition_date = db.Column(db.Date, primary_key=True)      # YYYY-MM-DD
    transition_hour = db.Column(db.Integer, primary_key=True)       # HH
    line_name = db.Column(db.String(50), primary_key=True)            # Hat Kodu (Örn: 500T)
    transfer_type = db.Column(db.String(50), primary_key=True)        # Normal / Aktarma
    product_kind = db.Column(db.String(50), primary_key=True)         # Tam, İndirimli vb.
    town = db.Column(db.String(100), primary_key=True)                # İlçe
    
    # Diğer Veri Kolonları
    transport_type_id = db.Column(db.Integer)                         # 1:Otoyol, 2:Raylı
    road_type = db.Column(db.String(100))                             # Ulaşım türü açık.
    line = db.Column(db.String(150))                                  # Güzergah/Hat açık.
    number_of_passage = db.Column(db.Integer)                         # TOPLAM GEÇİŞ SAYISI
    number_of_passenger = db.Column(db.Integer)                       # TEKİL YOLCU SAYISI
    transaction_type_desc = db.Column(db.String(150))                 # İşlem tipi (Kontur vb.)
    station_poi_desc_cd = db.Column(db.String(150))                   # İstasyon/Durak kodu
from dataclasses import dataclass

from dataclasses import dataclass

@dataclass
class TrafficIndexHistoryItem:
    traffic_index: int
    traffic_index_date: str
    period: str = ""
    source: str = "ibb_traffic"

    def to_dict(self):
        return {
            "traffic_index": self.traffic_index,
            "traffic_index_date": self.traffic_index_date,
            "period": self.period,
            "source": self.source
        }