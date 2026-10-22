"""Oncelikli firmalarin olasi kariyer adreslerini yokla: durum kodu, son adres, baslik, kullanilan ATS parmak izi."""
import re, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36', 'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
      'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}
FP = {'successfactors': r'successfactors|sapsf\.com|jobs\.sap', 'workday': r'myworkdayjobs|workday\.com', 'oracle': r'oraclecloud\.com|taleo',
      'smartrecruiters': r'smartrecruiters', 'greenhouse': r'greenhouse\.io', 'lever': r'lever\.co', 'icims': r'icims\.com', 'kariyer.net': r'kariyer\.net',
      'teamtailor': r'teamtailor', 'personio': r'personio', 'workable': r'workable\.com', 'comeet': r'comeet', 'recruitee': r'recruitee', 'ashby': r'ashbyhq',
      'sharepoint': r'_layouts/15|sharepoint', 'next.js': r'_next/static', 'angular': r'ng-version|<app-root', 'react/spa': r'id="root"|id="__next"'}
C = {
    'Garanti BBVA': ['https://www.garantibbva.com.tr/kariyer', 'https://kariyer.garantibbva.com.tr', 'https://garantibbvateknoloji.com.tr/kariyer', 'https://www.garantibbvakariyer.com'],
    'Hepsiburada': ['https://kariyer.hepsiburada.com', 'https://careers.hepsiburada.com', 'https://www.hepsiburada.com/kariyer'],
    'Akbank': ['https://www.akbank.com/tr-tr/Sayfalar/kariyer.aspx', 'https://kariyer.akbank.com', 'https://www.akbank.com/kariyer'],
    'Is Bankasi': ['https://www.isbank.com.tr/kariyer', 'https://kariyer.isbank.com.tr', 'https://www.isbank.com.tr/is-ilanlari'],
    'Yapi Kredi': ['https://www.yapikredi.com.tr/kariyer', 'https://kariyer.yapikredi.com.tr', 'https://www.yapikredi.com.tr/insan-kaynaklari/kariyer'],
    'Vodafone TR': ['https://www.vodafone.com.tr/kariyer', 'https://kariyer.vodafone.com.tr', 'https://www.vodafone.com.tr/hakkimizda/kariyer'],
    'Turk Telekom': ['https://www.turktelekom.com.tr/kariyer', 'https://kariyer.turktelekom.com.tr', 'https://www.turktelekom.com.tr/kurumsal/insan-kaynaklari'],
    'Getir': ['https://getir.com/kariyer/', 'https://careers.getir.com', 'https://kariyer.getir.com'],
    'Insider': ['https://useinsider.com/careers/open-positions/', 'https://useinsider.com/careers/'],
    'HAVELSAN': ['https://www.havelsan.com.tr/kariyer', 'https://kariyer.havelsan.com.tr', 'https://www.havelsan.com.tr/tr/kariyer'],
    'Roketsan': ['https://www.roketsan.com.tr/tr/kariyer', 'https://kariyer.roketsan.com.tr', 'https://www.roketsan.com.tr/kariyer'],
    'TUSAS': ['https://www.tusas.com/kariyer', 'https://kariyer.tusas.com', 'https://www.tusas.com/tr/kariyer'],
    'Baykar': ['https://kariyer.baykartech.com', 'https://www.baykartech.com/tr/kariyer/', 'https://baykartech.com/tr/kariyer'],
    'STM': ['https://www.stm.com.tr/tr/kariyer', 'https://kariyer.stm.com.tr'],
    'Amazon': ['https://www.amazon.jobs/en/search.json?result_limit=3&country%5B%5D=TUR', 'https://www.amazon.jobs/en/locations/istanbul-turkey'],
    'Microsoft': ['https://gcsservices.careers.microsoft.com/search/api/v1/search?lc=Turkey&l=en_us&pg=1&pgSz=3&o=Relevance&flt=true', 'https://jobs.careers.microsoft.com/global/en/search?lc=Turkey'],
    'Ericsson': ['https://jobs.ericsson.com/careers?location=Turkey'],
    'Koc Digital': ['https://www.koc.com.tr/kariyer', 'https://kariyer.koc.com.tr'],
    'Arcelik': ['https://www.arcelikglobal.com/tr/kariyer/', 'https://kariyer.arcelik.com.tr'],
    'Ford Otosan': ['https://www.fordotosan.com.tr/tr/kariyer', 'https://kariyer.fordotosan.com.tr'],
    'Papara': ['https://www.papara.com/kariyer', 'https://careers.papara.com'],
    'Param': ['https://param.com.tr/kariyer', 'https://www.param.com.tr/kariyer'],
    'Sipay': ['https://sipay.com.tr/kariyer', 'https://www.sipay.com.tr/kariyer'],
    'Enpara/QNB': ['https://www.qnbfinansbank.com/kariyer', 'https://kariyer.qnbfinansbank.com'],
    'DenizBank': ['https://www.denizbank.com/kariyer', 'https://kariyer.denizbank.com'],
    'ING TR': ['https://www.ing.com.tr/tr/kariyer', 'https://kariyer.ing.com.tr'],
    'Logo Yazilim': ['https://www.logo.com.tr/kariyer', 'https://kariyer.logo.com.tr'],
    'OBSS': ['https://www.obss.com.tr/kariyer', 'https://obss.tech/kariyer', 'https://www.obss.com.tr/tr/kariyer'],
    'Netas': ['https://www.netas.com.tr/kariyer', 'https://kariyer.netas.com.tr'],
}
jobs = [(f, u) for f, us in C.items() for u in us]


def probe(args):
    f, u = args
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            b = r.read(600000).decode('utf-8', 'replace')
            t = re.search(r'<title[^>]*>(.*?)</title>', b, flags=re.S | re.I)
            fp = [k for k, rx in FP.items() if re.search(rx, b, re.I)]
            return f, u, r.status, r.geturl(), re.sub(r'\s+', ' ', t.group(1)).strip()[:60] if t else '', len(b), fp
    except Exception as e:  # noqa
        return f, u, getattr(e, 'code', type(e).__name__), '', '', 0, []


with ThreadPoolExecutor(12) as ex:
    res = list(ex.map(probe, jobs))
last = None
for f, u, st, final, title, n, fp in res:
    if f != last:
        print(f'\n## {f}'); last = f
    mark = 'OK ' if st == 200 else str(st)[:3].ljust(3)
    red = '' if final == u or not final else f'  -> {final[:70]}'
    print(f'  {mark} {u[:70]:70s}{red}\n      "{title}" {n}B {fp}')
