"""Hizli fizibilite: halka acik ATS (Greenhouse/Lever/Workable/SmartRecruiters/Teamtailor...) uzerinden ilan cekilebiliyor mu?"""
import json, re, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15, context=ctx) as r:
            return r.status, r.read(400000).decode('utf-8', 'replace')
    except Exception as e:  # noqa
        return getattr(e, 'code', type(e).__name__), ''


# (etiket, url, ilan sayisini cikaran fonksiyon)
tests = [
    ('Greenhouse insider', 'https://boards-api.greenhouse.io/v1/boards/insider/jobs', lambda t: len(json.loads(t)['jobs'])),
    ('Greenhouse getir', 'https://boards-api.greenhouse.io/v1/boards/getir/jobs', lambda t: len(json.loads(t)['jobs'])),
    ('Greenhouse monzo (kontrol)', 'https://boards-api.greenhouse.io/v1/boards/monzo/jobs', lambda t: len(json.loads(t)['jobs'])),
    ('Lever dreamgames', 'https://api.lever.co/v0/postings/dreamgames?mode=json', lambda t: len(json.loads(t))),
    ('Lever spotify (kontrol)', 'https://api.lever.co/v0/postings/spotify?mode=json', lambda t: len(json.loads(t))),
    ('SmartRecruiters trendyol', 'https://api.smartrecruiters.com/v1/companies/trendyol/postings', lambda t: json.loads(t)['totalFound']),
    ('SmartRecruiters Visa (kontrol)', 'https://api.smartrecruiters.com/v1/companies/Visa/postings?limit=1', lambda t: json.loads(t)['totalFound']),
    ('Workable getir', 'https://apply.workable.com/api/v1/widget/accounts/getir', lambda t: len(json.loads(t)['jobs'])),
]
# Kariyer sayfalarinin hangi sistemi kullandigini anlamak: ana sayfa HTML'inde parmak izi
pages = ['https://careers.trendyol.com', 'https://www.hepsiburada.com/kariyer', 'https://www.dreamgames.com/careers',
         'https://jobs.garantibbvatechnology.com', 'https://kariyer.turkcell.com.tr', 'https://careers.getir.com',
         'https://useinsider.com/careers/open-positions/', 'https://www.papara.com/kariyer', 'https://www.iyzico.com/kariyer',
         'https://www.aselsan.com/tr/kariyer', 'https://www.baykartech.com/tr/kariyer/', 'https://www.n11.com/kariyer']
FP = {'greenhouse': r'greenhouse\.io', 'lever': r'lever\.co', 'workable': r'workable\.com', 'smartrecruiters': r'smartrecruiters\.com',
      'teamtailor': r'teamtailor', 'recruitee': r'recruitee\.com', 'comeet': r'comeet\.(co|com)', 'personio': r'personio\.', 'workday': r'myworkdayjobs',
      'ashby': r'ashbyhq', 'kariyer.net': r'kariyer\.net', 'jobvite': r'jobvite', 'oracle': r'oraclecloud\.com', 'sap-successfactors': r'successfactors'}


def run_test(t):
    lab, u, f = t
    code, body = get(u)
    try:
        return lab, code, f(body) if body else None
    except Exception as e:  # noqa
        return lab, code, 'parse:' + type(e).__name__


def run_page(u):
    code, body = get(u)
    found = [k for k, rx in FP.items() if re.search(rx, body, re.I)]
    return u, code, len(body), found


with ThreadPoolExecutor(8) as ex:
    print('--- Halka acik ATS API testleri')
    for r in ex.map(run_test, tests):
        print(' ', r)
    print('--- Kariyer sayfasi parmak izi')
    for r in ex.map(run_page, pages):
        print(' ', r)
