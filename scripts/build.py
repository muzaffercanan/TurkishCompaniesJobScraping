"""orig.xlsx + ankara_raw.json + ht_details.json -> Turkiye_Yazilim_Firmalari_v2.xlsx
Kullanim: python scripts/build.py [--dry]"""
import collections, copy, json, re, sys
from urllib.parse import quote

import openpyxl
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.datavalidation import DataValidation

DRY = '--dry' in sys.argv

# ---------------------------------------------------------------- yardimcilar
TR = str.maketrans({'İ': 'i', 'I': 'i', 'ı': 'i', 'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u',
                    'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c'})


def norm(s):
    return (s or '').translate(TR).lower()


def tokens(s):
    return [t for t in re.split(r'[^a-z0-9]+', norm(s)) if t]


LEGAL = {'limited', 'ltd', 'sti', 'sirketi', 'sirket', 'anonim', 'as', 'a', 's', 'san', 'sanayi', 've', 'tic', 'ticaret',
         'inc', 'co', 'llc', 'gmbh', 'bv', 'ltd.', 'tld', 'sti.'}


def tr_lower(w):
    return w.replace('İ', 'i').replace('I', 'ı').lower()


def tr_title(w):
    lw = tr_lower(w)
    if not lw or any(ch.isdigit() for ch in lw) or len(lw) <= 2:
        return w
    return {'i': 'İ', 'ı': 'I'}.get(lw[0], lw[0].upper()) + lw[1:]


def _strip_legal(s):
    s = re.sub(r'(?i)\s+(ltd\.?\s*ş?ti\.?|a\.\s?ş\.?|a\.s\.)\s*$', '', s)  # "Ltd.şti", "A.Ş." gibi bitisik/noktali ekler
    parts = s.split(' ')
    while len(parts) > 1 and norm(re.sub(r'[^\w]', '', parts[-1])) in LEGAL:
        parts.pop()
    return ' '.join(parts).strip(' ,.-')


def short_name(raw):
    s = _strip_legal(re.sub(r'\s+', ' ', raw).strip())
    letters = re.sub(r'[^A-Za-zÇĞİÖŞÜçğıöşü]', '', s)
    if letters and letters == letters.upper():
        s = ' '.join('-'.join(tr_title(p) for p in w.split('-')) for w in s.split(' '))
    s = re.sub(r'\bV[Ee]\b', 've', s)
    if len(s) > 52:
        cut = s[:52].rsplit(' ', 1)[0]
        s = cut if len(cut) > 15 else s[:52]
        s = _strip_legal(s)
        s = re.sub(r'\s+(ve|ile|&)$', '', s)
    return s


def clean_text(t):
    """Siteden gelen metindeki bozuk HTML artiklarini ve kontrol karakterlerini temizle."""
    t = re.sub(r'/?(?:div|span|strong|p|br|b|i|em|ul|li|a|h\d)gt;?', ' ', t or '')
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'[\x00-\x1f]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip(' ·|-')


def cap_tr(s):
    s = tr_lower(s)
    return {'i': 'İ', 'ı': 'I'}.get(s[:1], s[:1].upper()) + s[1:] if s else s


GEN = {'yazilim', 'bilisim', 'teknoloji', 'teknolojileri', 'teknolojisi', 'bilgi', 'sistemleri', 'sistem', 'danismanlik', 'hizmetleri',
       'muhendislik', 'elektronik', 'savunma', 'sanayi', 'ticaret', 've', 'tic', 'san', 'ltd', 'sti', 'as', 'anonim', 'sirketi',
       'limited', 'grup', 'group', 'holding', 'turkiye', 'turkey', 'tr', 'software', 'technology', 'technologies', 'tech', 'bilgisayar',
       'otomasyon', 'dijital', 'digital', 'arge', 'ar', 'ge', 'gelistirme', 'uretim', 'pazarlama', 'egitim', 'a', 's', 'inc', 'co',
       'com', 'net', 'org', 'cozumleri', 'cozum', 'solutions', 'systems', 've', 'iletisim', 'haberlesme', 'merkezi', 'laboratuvari'}


def key(name):
    t = [x for x in tokens(name) if x not in GEN]
    return '_'.join(t[:3]) if t else '_'.join(tokens(name)[:3])


BAD_HOST = ('wixsite', 'blogspot', 'wordpress', 'facebook', 'linkedin', 'instagram', 'google', 'github', 'weebly')


def host(w):
    w = norm(w).strip()
    w = re.sub(r'^https?://', '', w)
    w = re.sub(r'^www\.', '', w)
    w = w.split('/')[0].strip()
    return '' if (not w or any(b in w for b in BAD_HOST) or '.' not in w) else w


# ------------------------------------------------------------ siniflandirma
CAT_BANK = 'Banka & Banka Teknolojisi'
CAT_FIN = 'Fintech & Ödeme'
CAT_INS = 'Sigorta & Emeklilik'
CAT_CRY = 'Kripto & Blockchain'
CAT_ECOM = 'E-ticaret & Tüketici İnternet'
CAT_GAME = 'Oyun'
CAT_MOB = 'Mobilite, Lojistik & Seyahat'
CAT_AUTO = 'Otomotiv & Elektrikli Araç'
CAT_TEL = 'Telekom & Ağ'
CAT_DEF = 'Savunma, Havacılık & Uzay'
CAT_PUB = 'Kamu & Kamu Ar-Ge'
CAT_EMB = 'Gömülü Sistemler & Elektronik'
CAT_IND = 'Endüstriyel Otomasyon & Mühendislik'
CAT_ENE = 'Enerji & Akıllı Şebeke'
CAT_GIS = 'Harita, GIS & Konum'
CAT_AI = 'Yapay Zeka & Veri'
CAT_SEC = 'Siber Güvenlik'
CAT_HLT = 'Sağlık Teknolojileri'
CAT_EDU = 'Eğitim Teknolojileri'
CAT_MED = 'Medya, Reklam & MarTech'
CAT_ERP = 'Kurumsal Yazılım, ERP & SaaS'
CAT_CON = 'Yazılım Danışmanlığı & Proje Evleri'
CAT_APP = 'Mobil Uygulama & Web Ajansları'
CAT_HOL = 'Holding & Kurumsal Dijital Ekipler'
CAT_GLB = 'Global Şirket Türkiye Ofisi / Ar-Ge'
CAT_GEN = 'Genel Yazılım & BT (sektör belirsiz)'
CAT_OTH = 'Diğer / Yazılım Dışı Olabilir'

RENAME = {'Banka & Banka Teknoloji Şirketleri': CAT_BANK, 'Telekom & Altyapı': CAT_TEL,
          'Yazılım Danışmanlığı & Proje Firmaları': CAT_CON, 'Mobil Uygulama Stüdyoları & Ajanslar': CAT_APP}
RECLASS_OLD = {'Yazılım & Teknoloji (Teknopark / Startup)', 'Gömülü Sistemler, Elektronik & Mühendislik', 'Savunma, Havacılık & Kamu Ar-Ge'}

RULES = [  # (kategori, regex ASCII-normalize isim uzerinde) - ilk eslesen kazanir
    (CAT_GAME, r'game|oyun|gaming|esport'),
    (CAT_BANK, r'\bbank|banka'),
    (CAT_INS, r'sigorta|insur|emeklilik'),
    (CAT_CRY, r'kripto|crypto|blockchain|\bcoin|token'),
    (CAT_FIN, r'finans|fintech|odeme|payment|\bpay\b|\bpos\b|tahsilat|faktoring|leasing|kredi|e-?para|elektronik para|yatirim|borsa|trading'),
    (CAT_DEF, r'savunma|defen[cs]e|havacilik|aviation|aero|ucak|fuze|radar|uzay|space|uydu|satellite|\biha\b|roket|harp|silah'),
    (CAT_SEC, r'siber|cyber|guvenlik|security|sifre|kriptoloji|biyometri|biometr'),
    (CAT_AI, r'yapay zeka|artificial|\bai\b|\bml\b|machine learning|makine ogren|\bdata\b|\bveri\b|analitik|analytics|big data|goruntu isleme|vision|robot|derin ogren|deep learn'),
    (CAT_HLT, r'saglik|health|medikal|medical|\btip\b|hastane|ilac|pharma|\bbio|klinik|diyet|eczane|teshis|hasta'),
    (CAT_EDU, r'education|edtech|akademi|okul|ogren|learning|kurs\b|ogretim'),
    (CAT_TEL, r'telekom|telecom|haberlesme|network|\b5g\b|\brf\b|fiber|\bgsm\b|operator|kablosuz|wireless|antenna|anten'),
    (CAT_GIS, r'harita|\bgis\b|\bcbs\b|cografi|\bgeo|konum|location|navigasyon'),
    (CAT_AUTO, r'otomotiv|automotive|\barac\b|vehicle|\bev\b|sarj|charging|elektrikli ara|motor'),
    (CAT_MOB, r'lojistik|logistic|tasima|kargo|nakliye|\bfilo\b|fleet|ulasim|seyahat|travel|turizm|\botel\b|hotel|mobilite|mobility'),
    (CAT_ENE, r'enerji|energy|solar|gunes|ruzgar|elektrik|\bpower\b|sebeke|\bgrid\b|batarya|battery|hidrojen|sayac|smart meter'),
    (CAT_ECOM, r'e-?ticaret|ecommerce|e-commerce|pazaryeri|marketplace|perakende|retail|alisveris|shop|sepet|siparis|yemek'),
    (CAT_MED, r'medya|media|reklam|\bads?\b|advert|pazarlama|marketing|ajans|agency|produksiyon|animasyon|sosyal medya|icerik|content|yayin'),
    (CAT_APP, r'mobil uygulama|mobile app|\bapp\b|\bapps\b|web tasarim|web design|\bweb\b|mobil'),
    (CAT_ERP, r'\berp\b|\bcrm\b|saas|muhasebe|accounting|e-?fatura|e-?defter|insan kaynak|\bhr\b|bordro|is zekasi|\bbi\b|kurumsal|yonetim sistem|otomasyon yazilim|yazilim cozum'),
    (CAT_CON, r'consult|outsourc|bilisim hizmet|it services|yazilim hizmet|yazilim evi|software house'),
    (CAT_EMB, r'gomulu|embedded|elektronik|electronic|devre|\bpcb\b|sensor|\biot\b|nesnelerin|mikro|cihaz|donanim|hardware|firmware|fpga|lazer|laser|optik|optic|kamera'),
    (CAT_IND, r'otomasyon|automation|endustri|industrial|makine|mekatronik|mechatron|proses|\bplc\b|scada|uretim|imalat|tasarim|muhendislik|engineering|\bcnc\b|kalip|insaat|yapi'),
    (CAT_GEN, r'yazilim|software|\bsoft|bilisim|bilgi sistem|bilgi teknoloji|dijital|digital|\btech|teknoloji|technolog|sistem|system|\blab|arge|ar-ge|bilgisayar|computer|\bit\b|internet|platform|cozum|solution|\.com|\.io|\.ai'),
    (CAT_EDU, r'egitim'),  # "Yazilim Egitim Danismanlik" gibi unvan listelerinde yaniltici; yalnizca baska ipucu yoksa
]
RULES = [(c, re.compile(r)) for c, r in RULES]
# Turk unvanlari "Yazilim Danismanlik Egitim Ticaret" gibi sektor listeleri icerir; bu yuzden sira degil, ismin
# basindaki anahtar kelime belirleyici olsun. Cok belirgin sektorler (STRONG) her zaman kazanir, ortadakiler
# isimde ilk gecene gore secilir, zayif olanlar (muhendislik/tasarim/genel) yalnizca baska bir sey yoksa kullanilir.
STRONG = {CAT_GAME, CAT_BANK, CAT_INS, CAT_CRY, CAT_FIN, CAT_DEF, CAT_SEC, CAT_HLT}
WEAK = {CAT_IND, CAT_GEN, CAT_CON}
SOFT_RX = re.compile(r'yazilim|software|\bsoft\b|bilisim|bilgi sistem|bilgi teknoloji|dijital|digital')

SW_VERY = re.compile(r'yazilim|software|\bsoft|bilisim|bilgi sistem|bilgi teknoloji|dijital|digital|\bai\b|yapay zeka|siber|cyber|oyun|game|\bdata\b|\bveri\b|bulut|cloud|mobil|internet|platform|saas|fintech|\bweb\b|\bapp\b')
SW_BROAD = re.compile(SW_VERY.pattern + r'|robot|simulasyon|simulation|bilgisayar|computer|network|telekom|haberlesme|iletisim|elektronik|electronic|embedded|gomulu|otomasyon|automation|savunma|defen|havacilik|uzay|space|\btech|teknoloji|technolog|sistem|system|\blab|arge|ar-ge|\biot\b|sensor|muhendislik|engineering|arastirma gelistirme|bilgi islem|\bgis\b|harita')
BIG_RX = re.compile(r'aselsan|havelsan|roketsan|tusas|baykar|turkcell|vodafone|ericsson|huawei|siemens|bosch|samsung|nokia|oracle|microsoft|\bibm\b|\bsap\b|\bintel\b|cisco|schneider|honeywell|arcelik|vestel|netas|turk telekom|turksat|tubitak|\bstm\b|mkek|otokar|tofas|ford otosan|hyundai|toyota|continental|\bnxp\b|qualcomm')
NEG = re.compile(r'gida|tarim|hayvan|insaat|ilac\b|kimya|tekstil|boya|madencilik|maden\b|gayrimenkul|nakliyat|hafriyat|ambalaj|plastik|mobilya|kozmetik|temizlik|restoran|catering|ormancilik|deri|kagit|cam\b|seramik|metal(?!urji arastirma)|celik|dokum|boru|vana|makina imalat|gubre|tohum|su aritma|atik')

CORP = {CAT_BANK, CAT_INS, CAT_HOL, CAT_GLB, CAT_PUB}
SWNATIVE = {CAT_GAME, CAT_FIN, CAT_CRY, CAT_ECOM, CAT_AI, CAT_SEC, CAT_EDU, CAT_MED, CAT_ERP, CAT_CON, CAT_APP, CAT_GEN, CAT_HLT, CAT_MOB}

ODAK_SW = 'Yazılım şirketi'
ODAK_MIX = 'Teknoloji + Ar-Ge (karma)'
ODAK_CORP = 'Kurumsal iç yazılım ekibi'
ODAK_UNK = 'Belirsiz / yazılım dışı olabilir'

PUB_RE = re.compile(r'tubitak|turksat|\bptt\b|dijital donusum|belediye|kamu|bakanlik|ulakbim|\btse\b|btk|\bmke\b|tcdd|gov')


def _pick(n):
    ms = []  # (grup, konum, sira, kategori)
    for i, (cat, rx) in enumerate(RULES):
        m = rx.search(n)
        if m:
            grp = 0 if cat in STRONG else 2 if (cat in WEAK or i == len(RULES) - 1) else 1
            ms.append((grp, m.start(), i, cat))
    sm = SOFT_RX.search(n)
    if sm:  # "yazilim/bilisim" orta grupta genel yazilim sinyali
        ms.append((1, sm.start(), 99, CAT_GEN))
    if not ms:
        return None
    strong = [m for m in ms if m[0] == 0]
    if strong:
        return min(strong, key=lambda m: (m[1], m[2]))[3]
    mid = [m for m in ms if m[0] == 1]
    if mid:
        return min(mid, key=lambda m: (m[1], m[2]))[3]
    return min(ms, key=lambda m: m[2])[3]


def classify(name, note='', old=None, desc=''):
    n = norm(name)
    if old == 'Savunma, Havacılık & Kamu Ar-Ge':
        return CAT_PUB if PUB_RE.search(n) else CAT_DEF
    hit = _pick(n)
    if hit and hit not in WEAK:
        return hit
    if desc:
        h2 = _pick(norm(desc))
        if h2 and h2 not in WEAK:
            return h2
    if hit:
        return hit
    # isimden bir sey cikmadiysa eski/kaynak ipucuna dus
    if old == 'Gömülü Sistemler, Elektronik & Mühendislik':
        return CAT_EMB
    if 'Endüstriyel Tasarım' in (note or ''):
        return CAT_IND
    if 'Rehber sektörü: Yazılım' in (note or '') or old == 'Yazılım & Teknoloji (Teknopark / Startup)':
        return CAT_GEN
    return CAT_OTH


def odak(cat, name):
    n = norm(name)
    if cat in CORP:
        return ODAK_CORP
    if SW_VERY.search(n):
        return ODAK_SW
    if cat == CAT_OTH:
        return ODAK_UNK
    if cat == CAT_IND:
        return ODAK_UNK
    if cat in SWNATIVE:
        return ODAK_SW
    return ODAK_MIX


# --------------------------------------------------------------- girdiler
wb = openpyxl.load_workbook('orig.xlsx')
ws = wb['Firmalar']
rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
# hyperlink hedefleri (web) korunur
web_target = {}
for i, r in enumerate(ws.iter_rows(min_row=2), start=0):
    c = r[9]
    web_target[i] = c.hyperlink.target if c.hyperlink else None

SIZE_BIG, SIZE_MID, SIZE_SMALL, SIZE_UNK = 'Büyük / kurumsal', 'Orta / scale-up', 'Küçük / startup', 'Bilinmiyor (çoğunlukla küçük)'
APPROACH = {SIZE_BIG: 'Kariyer sayfası + yeni mezun/MT programı + içeriden çalışana referans isteği',
            SIZE_MID: "Engineering Manager / Tech Lead'e LinkedIn mesajı + kariyer sayfası",
            SIZE_SMALL: "Kurucuya / CTO'ya doğrudan kısa mail veya LinkedIn mesajı",
            SIZE_UNK: "Kurucuya / CTO'ya doğrudan kısa mail veya LinkedIn mesajı"}

# kategori -> (roller, hedef alan) : mevcut verideki en yaygin deger + yeni kategoriler icin elle
role_by_cat = collections.defaultdict(collections.Counter)
for r in rows:
    role_by_cat[RENAME.get(r[2], r[2])][(r[6], r[7])] += 1
ROLE = {c: cnt.most_common(1)[0][0] for c, cnt in role_by_cat.items()}
ROLE.update({
    CAT_PUB: ('Yazılım (Java/C#/C++), Gömülü, Veri', 'Backend (Java/C#)'),
    CAT_DEF: ('Yazılım (Java/C#/C++), Gömülü, Simülasyon', 'Backend (Java/C#)'),
    CAT_IND: ('Gömülü (C/C++), PLC/SCADA yazılımı, Test', 'Gömülü / Backend'),
    CAT_ENE: ('Backend, Veri, IoT, Gömülü', 'Backend · Full Stack · Data'),
    CAT_AUTO: ('Gömülü (C/C++), Backend, Mobil', 'Gömülü / Backend'),
    CAT_GIS: ('Backend, Full Stack, Veri (GIS)', 'Backend · Full Stack · Data'),
    CAT_GEN: ('Full Stack, Backend', 'Backend · Full Stack · Data'),
    CAT_OTH: ('Yazılım rolü varsa (Test, Destek, Backend)', 'Belirsiz'),
    CAT_EMB: ('Gömülü (C/C++), Yazılım, Test', 'Gömülü / Backend'),
    CAT_TEL: ROLE.get(CAT_TEL, ('Backend, Cloud/DevOps, Data', 'Backend · Full Stack · Data')),
})

# ---------------------------------------------------- mevcut satirlari donustur
recs = []  # sozluk listesi
changed_cat = collections.Counter()
for i, r in enumerate(rows):
    (no, name, cat, note, city, size, roles, target, approach, web, li_c, li_p, li_h, g, src, status, prio, who, whol, d1, d2, notes) = r
    old = cat
    cat = RENAME.get(cat, cat)
    if old in RECLASS_OLD:
        cat = classify(name, note, old)
    if cat != old:
        changed_cat[(old, cat)] += 1
    if cat != RENAME.get(old, old) or old in RECLASS_OLD:
        roles, target = ROLE[cat]
    size = SIZE_UNK if size.startswith('Küçük / bilinmiyor') else size
    if web in ('—', '-', ''):
        web = None
    if city == '—':
        city = 'Belirtilmemiş'
    recs.append(dict(name=name, cat=cat, note=note, city=city, size=size, roles=roles, target=target, approach=approach,
                     web=web, web_link=web_target.get(i), src=src, status=status, prio=prio, who=who, whol=whol, d1=d1, notes=notes, old=True))

# --------------------------------------------------------- Ankara'yi ekle
raw = json.load(open('ankara_raw.json', encoding='utf-8'))
det = {d['ht_page']: d for d in json.load(open('ht_details.json', encoding='utf-8'))}
SRC_NAME = {'ODTÜ Teknokent': 'ODTÜ Teknokent firma rehberi', 'Bilkent Cyberpark': 'Bilkent Cyberpark firma rehberi',
            'Hacettepe Teknokent': 'Hacettepe Teknokent firma rehberi'}
HT_OK = {'YAZILIM', 'BİLGİSAYAR VE İLETİŞİM TEKNOLOJİLERİ', 'ELEKTRONİK', 'SAVUNMA SANAYİ VE HAVACILIK', 'TELEKOMÜNİKASYON',
         'MEDYA VE İLETİŞİM', 'DANIŞMANLIK'}

existing_keys = collections.defaultdict(list)
existing_hosts = {}
for k, rc in enumerate(recs):
    existing_keys[key(rc['name'])].append(k)
    h = host(rc['web'] or '')
    if h:
        existing_hosts[h] = k
first_tok = collections.defaultdict(list)
for k, rc in enumerate(recs):
    t = tokens(rc['name'])
    if t and len(t[0]) >= 6:
        first_tok[t[0]].append(k)

KEEP_DISTINCT = ('karaca grup', 'optima soft', 'aselsan bilkent')
new = {}  # key -> dict (Ankara ici birlestirme)
excluded, dup_exist, dup_review = [], [], []
for x in raw:
    name_raw = x['name']
    n = norm(name_raw)
    hint = x.get('hint', '')
    web = x.get('web', '')
    d = det.get(x.get('ht_page'))
    desc = ''
    if d:
        web = web or d['web']
        desc = d['desc']
    # ilgi filtresi
    strong = bool(SW_VERY.search(n))
    if x['source'] == 'Hacettepe Teknokent':
        ok = (hint in HT_OK and (strong or SW_BROAD.search(n) or hint in {'YAZILIM', 'BİLGİSAYAR VE İLETİŞİM TEKNOLOJİLERİ'})) or strong
        if hint in {'SAVUNMA SANAYİ VE HAVACILIK'} and NEG.search(n) and not strong:
            ok = False
    else:
        ok = bool(SW_BROAD.search(n)) and (not NEG.search(n) or strong)
    if not ok:
        excluded.append((x['source'], name_raw))
        continue
    sname = short_name(name_raw)
    k = key(sname)
    h = host(web)
    # mevcut listede var mi?
    hit = existing_keys.get(k) or ([existing_hosts[h]] if h and h in existing_hosts else None)
    if hit:
        dup_exist.append((sname, recs[hit[0]]['name']))
        continue
    t = tokens(sname)
    if t and len(t[0]) >= 6 and t[0] in first_tok and len(tokens(recs[first_tok[t[0]][0]]['name'])) <= 2:
        other = recs[first_tok[t[0]][0]]['name']
        if not sname.lower().startswith(KEEP_DISTINCT):  # farkli firma oldugu bilinenler
            dup_review.append((sname, other))
            continue
    if k in new:
        e = new[k]
        if SRC_NAME[x['source']] not in e['src']:
            e['src'] += ' + ' + SRC_NAME[x['source']]
        e['web'] = e['web'] or web
        e['desc'] = e['desc'] or desc
        e['hint'] = e['hint'] or hint
        continue
    new[k] = dict(sname=sname, legal=name_raw, web=web, src=SRC_NAME[x['source']], desc=desc, hint=hint)

web_meta = json.load(open('web_meta.json', encoding='utf-8'))
for k, e in new.items():
    meta = web_meta.get(host(e['web']), {}) if e['web'] else {}
    mtxt = ' '.join(x for x in (meta.get('title'), meta.get('desc')) if x)
    if not e['desc'] and meta.get('desc'):
        e['desc'] = meta['desc']
    elif not e['desc'] and meta.get('title'):
        e['desc'] = meta['title']
    cat = classify(e['sname'] + ' ' + e['legal'], desc=(e['desc'] + ' ' + mtxt))
    if cat == CAT_OTH and e['hint'] in {'YAZILIM', 'BİLGİSAYAR VE İLETİŞİM TEKNOLOJİLERİ'}:
        cat = CAT_GEN
    if cat == CAT_OTH and e['hint'] == 'ELEKTRONİK':
        cat = CAT_EMB
    if cat == CAT_OTH and e['hint'] == 'SAVUNMA SANAYİ VE HAVACILIK':
        cat = CAT_DEF
    if cat == CAT_OTH and e['hint'] == 'TELEKOMÜNİKASYON':
        cat = CAT_TEL
    if cat == CAT_OTH and e['hint'] == 'MEDYA VE İLETİŞİM':
        cat = CAT_MED
    parts = []
    if e['hint']:
        parts.append(f"Rehber sektörü: {cap_tr(e['hint'])}")
    dtxt = clean_text(e['desc'])[:160]
    if dtxt:
        parts.append(dtxt)
    if e['legal'] != e['sname']:
        parts.append('Ticari unvan: ' + re.sub(r'\s+', ' ', e['legal']))
    note = ' · '.join(parts) if parts else 'Ankara teknokent firması'
    w = (e['web'] or '').strip()
    if '.' not in w or ' ' in w:  # "-", "yok" gibi bos degerler
        w = ''
    wl = None
    wt = ''
    if w:
        wl = w if re.match(r'https?://', w, re.I) else 'https://' + w
        wt = re.sub(r'^https?://(www\.)?', '', w, flags=re.I).rstrip('/')
    roles, target = ROLE[cat]
    size = SIZE_BIG if BIG_RX.search(norm(e['sname'])) else SIZE_UNK
    recs.append(dict(name=e['sname'], cat=cat, note=note, city='Ankara', size=size, roles=roles, target=target,
                     approach=APPROACH[size], web=wt, web_link=wl, src=e['src'], status='Araştırılacak', prio=None, who=None,
                     whol=None, d1=None, notes=None, old=False))

# ------------------------------------------------------------ yazilim odagi
for rc in recs:
    rc['odak'] = odak(rc['cat'], rc['name'] + ' ' + (rc['note'] or '')) if rc['cat'] != CAT_OTH else ODAK_UNK
    # eski, elle derlenmis satirlar icin not metni isim filtresini bozmasin
    if rc['old']:
        rc['odak'] = odak(rc['cat'], rc['name'])

# ---------------------------------------------------------------- istatistik
print('Toplam', len(recs), '| eski', sum(r['old'] for r in recs), '| yeni Ankara', sum(not r['old'] for r in recs))
print('Ankara ham', len(raw), 'dislanan', len(excluded), 'mevcutla cakisan', len(dup_exist), 'birlesen(park arasi)', len(raw) - len(excluded) - len(dup_exist) - len(new))
print('\nKategori:'); [print(f'  {v:4d}  {k}') for k, v in collections.Counter(r['cat'] for r in recs).most_common()]
print('\nOdak:', collections.Counter(r['odak'] for r in recs))
print('Sehir:', collections.Counter(r['city'] for r in recs).most_common(8))
print('Boyut:', collections.Counter(r['size'] for r in recs))
print('\nYeniden siniflanan (eski->yeni) ilk 25:'); [print('  ', v, a, '->', b) for (a, b), v in changed_cat.most_common(25)]
print('\nCakisma ornekleri:', dup_exist[:12])
print('\nInceleme (ilk token ayni):', dup_review[:25])
print('\nDislanan ornek:', [e[1][:40] for e in excluded[:25]])
if DRY:
    sys.exit()

# --------------------------------------------------------------------- yaz
NAVY, ACCENT, YEL_H, YEL = '1F3A5F', '0F766E', '7A5C00', 'FFF7D6'
HEAD = ['No', 'Firma', 'Kategori', 'Alt alan / Not', 'Şehir', 'Büyüklük (tahmini)', 'Yazılım odağı', 'Uygun roller', 'Hedef alan eşleşmesi',
        'Önerilen yaklaşım', 'Web sitesi', 'LinkedIn şirket', 'LinkedIn çalışanlar', 'LinkedIn İK / recruiter', 'Google: kariyer sayfası',
        'Kaynak', 'Durum', 'Önceliğim (A/B/C)', 'İletişim kişisi', 'Kişi LinkedIn / e-posta', 'İlk temas tarihi', 'Takip tarihi (+7 gün)',
        'Notlarım']
FILTER_COLS = {3, 5, 6, 7}  # C E F G
TRACK_FIRST = 17  # Q
WIDTH = {1: 6, 2: 34, 3: 34, 4: 46, 5: 14, 6: 26, 7: 26, 8: 32, 9: 26, 10: 40, 11: 22, 12: 13, 13: 17, 14: 13, 15: 13, 16: 34, 17: 22,
         18: 11, 19: 20, 20: 26, 21: 13, 22: 13, 23: 30}

old_ws = ws
hdr_src = old_ws['A1']
body_src = {c.column: c for c in old_ws[2]}
new_ws = wb.create_sheet('Firmalar_yeni', 0)
OLD2NEW = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 8, 8: 9, 9: 10, 10: 11, 11: 12, 12: 13, 13: 14, 14: 15, 15: 16, 16: 17, 17: 18, 18: 19, 19: 20,
           20: 21, 21: 22, 22: 23}


def style_from(dst, src):
    dst.font = copy.copy(src.font)
    dst.fill = copy.copy(src.fill)
    dst.border = copy.copy(src.border)
    dst.alignment = copy.copy(src.alignment)
    dst.number_format = src.number_format
    dst.protection = copy.copy(src.protection)


for j, h in enumerate(HEAD, 1):
    c = new_ws.cell(1, j, h)
    style_from(c, old_ws.cell(1, 1))
    c.fill = PatternFill('solid', fgColor=(YEL_H if j >= TRACK_FIRST else ACCENT if j in FILTER_COLS else NAVY))
new_ws.row_dimensions[1].height = old_ws.row_dimensions[1].height or 36

blue = copy.copy(old_ws['J2'].font)
for i, rc in enumerate(recs):
    r = i + 2
    q = quote(rc['name'])
    vals = {
        1: i + 1, 2: rc['name'], 3: rc['cat'], 4: rc['note'], 5: rc['city'], 6: rc['size'], 7: rc['odak'], 8: rc['roles'], 9: rc['target'],
        10: rc['approach'], 11: rc['web'] or None, 12: 'Şirketi bul', 13: 'Mühendisleri gör', 14: "İK'yı gör", 15: 'Kariyer ara',
        16: rc['src'], 17: rc['status'], 18: rc['prio'], 19: rc['who'], 20: rc['whol'], 21: rc['d1'], 22: f'=IF(U{r}="","",U{r}+7)', 23: rc['notes']}
    links = {11: rc['web_link'] if rc['web'] else None,
             12: f'https://www.linkedin.com/search/results/companies/?keywords={q}',
             13: f'https://www.linkedin.com/search/results/people/?keywords={q}%20software%20engineer',
             14: f'https://www.linkedin.com/search/results/people/?keywords={q}%20talent%20acquisition',
             15: f'https://www.google.com/search?q={q}%20kariyer%20yaz%C4%B1l%C4%B1m'}
    for j in range(1, 24):
        c = new_ws.cell(r, j, vals[j])
        sj = {7: 6}.get(j) or next((o for o, n_ in OLD2NEW.items() if n_ == j), 1)
        style_from(c, body_src[sj])
        if j in links and links[j]:
            c.hyperlink = links[j]
            c.font = copy.copy(blue)
    new_ws.row_dimensions[r].height = old_ws.row_dimensions[2].height

last = len(recs) + 1
for j, w in WIDTH.items():
    new_ws.column_dimensions[L(j)].width = w
new_ws.freeze_panes = 'C2'
new_ws.auto_filter.ref = f'A1:{L(23)}{last}'
new_ws.sheet_view.zoomScale = old_ws.sheet_view.zoomScale

STATUS = '"Araştırılacak,Bağlantı isteği gönderildi,Mail gönderildi,Referans istendi,Yanıt geldi,İK görüşmesi,Teknik mülakat,Teklif,Red,Şimdilik pas"'
dv1 = DataValidation(type='list', formula1=STATUS, allow_blank=True)
dv2 = DataValidation(type='list', formula1='"A,B,C"', allow_blank=True)
new_ws.add_data_validation(dv1); new_ws.add_data_validation(dv2)
dv1.add(f'Q2:Q{last}'); dv2.add(f'R2:R{last}')
new_ws.conditional_formatting.add(f'Q2:Q{last}', CellIsRule(operator='equal', formula=['"Teklif"'], fill=PatternFill('solid', bgColor='C6EFCE', fgColor='C6EFCE')))
new_ws.conditional_formatting.add(f'Q2:Q{last}', CellIsRule(operator='equal', formula=['"Red"'], fill=PatternFill('solid', bgColor='F8CBAD', fgColor='F8CBAD')))
new_ws.conditional_formatting.add(f'V2:V{last}', FormulaRule(
    formula=['AND(V2<>"",V2<=TODAY(),OR(Q2="Mail gönderildi",Q2="Bağlantı isteği gönderildi",Q2="Referans istendi"))'],
    fill=PatternFill('solid', bgColor='FFC7CE', fgColor='FFC7CE')))

wb.remove(old_ws)
new_ws.title = 'Firmalar'

# ------------------------------------------------------------------- Özet
del wb['Özet']
oz = wb.create_sheet('Özet', 1)
hfont = Font(name='Arial', bold=True, color='FFFFFF', size=10)
hfill = PatternFill('solid', fgColor=NAVY)
bfont = Font(name='Arial', size=10)
bold = Font(name='Arial', size=10, bold=True)
thin = Border(bottom=Side(style='thin', color='D9D9D9'))
R = f'$2:${last}'


def rng(col):
    return f'Firmalar!${col}$2:${col}${last}'


oz['A1'] = 'Özet — formüller Firmalar sayfasından otomatik hesaplanır'
oz['A1'].font = Font(name='Arial', bold=True, size=13)
oz['A3'] = 'Toplam firma'; oz['B3'] = f'=COUNTA({rng("B")})'
oz['A3'].font = bold; oz['B3'].font = bold
row = 5


def table(title, col, items):
    global row
    oz.cell(row, 1, title).font = hfont; oz.cell(row, 1).fill = hfill
    oz.cell(row, 2, 'Firma sayısı').font = hfont; oz.cell(row, 2).fill = hfill
    start = row + 1
    for it in items:
        row += 1
        oz.cell(row, 1, it).font = bfont
        oz.cell(row, 2, f'=COUNTIF({rng(col)},A{row})').font = bfont
        oz.cell(row, 1).border = thin; oz.cell(row, 2).border = thin
    row += 1
    oz.cell(row, 1, 'Toplam').font = bold
    oz.cell(row, 2, f'=SUM(B{start}:B{row - 1})').font = bold
    row += 2


def order(field):
    return [k for k, _ in collections.Counter(r[field] for r in recs).most_common()]


table('Kategori', 'C', order('cat'))
table('Şehir', 'E', order('city'))
table('Büyüklük (tahmini)', 'F', [SIZE_BIG, SIZE_MID, SIZE_SMALL, SIZE_UNK])
table('Yazılım odağı', 'G', [ODAK_SW, ODAK_CORP, ODAK_MIX, ODAK_UNK])
table('Başvuru durumu', 'Q', ['Araştırılacak', 'Bağlantı isteği gönderildi', 'Mail gönderildi', 'Referans istendi', 'Yanıt geldi', 'İK görüşmesi',
                              'Teknik mülakat', 'Teklif', 'Red', 'Şimdilik pas'])

# Kategori x Sehir capraz tablo (en cok 6 sehir)
top_cities = [c for c, _ in collections.Counter(r['city'] for r in recs).most_common(6)]
oz.cell(row, 1, 'Kategori × Şehir').font = hfont; oz.cell(row, 1).fill = hfill
for j, cty in enumerate(top_cities, 2):
    oz.cell(row, j, cty).font = hfont; oz.cell(row, j).fill = hfill
hdr_row = row
for cat in order('cat'):
    row += 1
    oz.cell(row, 1, cat).font = bfont
    for j in range(2, 2 + len(top_cities)):
        cl = L(j)
        oz.cell(row, j, f'=COUNTIFS({rng("C")},$A{row},{rng("E")},{cl}${hdr_row})').font = bfont
oz.column_dimensions['A'].width = 42
for j in range(2, 9):
    oz.column_dimensions[L(j)].width = 16

# --------------------------------------------------------- Strateji / Kaynaklar
st = wb['Strateji & Şablonlar']
st['A2'] = ("1) Firmalar sayfasında filtreler: Kategori (sektör), Şehir, Büyüklük ve Yazılım odağı kolonları (turkuaz başlıklar). "
            "Başlıktaki ok ile liste seçip birden fazla filtreyi birlikte kullanabilirsin. Sarı kolonlar (Q–W) senin dolduracağın takip alanları.")
st['A6'] = ("4) Web sitesi yalnızca bilinen firmalarda dolu (ODTÜ ve Hacettepe rehberleri site adresi veriyor, Cyberpark vermiyor). "
            "Boş olanlarda 'Kariyer ara' linkini kullan. Teknopark/girişim/teknokent listeleri 2026 rehberlerinden alındı; bazı firmalar kapanmış veya taşınmış olabilir.")
st['A7'] = ("5) Büyüklük sütunu tahminidir; teknokent rehberleri çalışan sayısı vermediği için o firmalar 'Bilinmiyor (çoğunlukla küçük)' diye etiketli. "
            "'Yazılım odağı' ise firmanın adına ve kategorisine göre bir tahmindir: 'Belirsiz / yazılım dışı olabilir' olanları önceliklendirme.")
ka = wb['Kaynaklar']
fix = {'ODTÜ Teknokent (Ankara)': ('https://www.odtuteknokent.com.tr/tr/firmalar/tum-firmalar.php', 'Eklendi (420 kayıt tarandı; yazılım/teknoloji ilgisi olanlar listede)'),
       'Bilkent Cyberpark (Ankara)': ('https://www.cyberpark.com.tr/firma-arsiv', 'Eklendi (368 kayıt tarandı; site adresi vermiyor)'),
       'Hacettepe Teknokent (Ankara)': ('https://hacettepeteknokent.com.tr/tr/firma_rehberi', 'Eklendi (334 kayıt tarandı; site ve tanıtım metni çekildi)')}
for rr in ka.iter_rows(min_row=2):
    if rr[0].value in fix:
        rr[1].value, rr[2].value = fix[rr[0].value]
        rr[1].hyperlink = fix[rr[0].value][0]

out = 'Turkiye_Yazilim_Firmalari_v2.xlsx'
wb.save(out)
print('kaydedildi', out, 'satir', len(recs))
