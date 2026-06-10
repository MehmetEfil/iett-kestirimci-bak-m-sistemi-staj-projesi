import math

def temiz_sayi(v, d=0.0):
    if v is None:
        return d
    try:
        return float(str(v).replace(",", ".").strip())
    except (ValueError, TypeError):
        return d

def temiz_str(v, d=''):
    if v is None:
        return d
    s = str(v).strip()
    return d if s.lower() in ('none', 'null', '') else s

def yon_cozucu(y):
    y = str(y or '').strip().upper()
    if y in ('G','1','-1','A','GIDIS','GIDIŞ'):
        return 'G'
    if y in ('D','2','0','B','DONUS','DÖNÜŞ'):
        return 'D'
    return None

def hav(la1,lo1,la2,lo2):
    R=6371
    dl=(la2-la1)*math.pi/180
    dn=(lo2-lo1)*math.pi/180
    a=math.sin(dl/2)**2+math.cos(la1*math.pi/180)*math.cos(la2*math.pi/180)*math.sin(dn/2)**2
    return R*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

def alan_oku(d, *anahtarlar, varsayilan=''):
    for k in anahtarlar:
        adaylar = [k, str(k).upper(), str(k).lower(), str(k).capitalize()]
        for deneme in adaylar:
            if deneme in d and d[deneme] is not None:
                return d[deneme]
    return varsayilan

import xml.etree.ElementTree as ET

def safe_int(v, d=0):
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except (ValueError, TypeError):
        return d

def safe_bool(v, d=False):
    if v is None:
        return d
    s = str(v).strip().lower()
    if s in ("1", "true", "evet", "yes"):
        return True
    if s in ("0", "false", "hayir", "hayır", "no"):
        return False
    return d

def strip_ns(tag):
    return tag.split('}', 1)[-1] if '}' in tag else tag

def parse_xml_root(xml_text):
    try:
        return ET.fromstring(xml_text)
    except Exception:
        return None

def xml_child_text(elem, name, default=""):
    if elem is None:
        return default
    for child in elem:
        if strip_ns(child.tag) == name:
            return temiz_str(child.text, default)
    return default

def xml_findall_local(root, local_name):
    sonuc = []
    if root is None:
        return sonuc
    for elem in root.iter():
        if strip_ns(elem.tag) == local_name:
            sonuc.append(elem)
    return sonuc