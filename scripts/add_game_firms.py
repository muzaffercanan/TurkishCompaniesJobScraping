"""data/oyun_yeni.json'daki oyun firmalarini Turkiye_Yazilim_Firmalari_v2.xlsx 'Firmalar' sayfasina ekler.
Bicim, bağlantılar, açılır listeler, koşullu biçim, filtre ve Özet formül aralıkları yeni son satıra uzatılır.
Kullanim: python scripts/add_game_firms.py"""
import copy
import json
import re
from urllib.parse import quote

import openpyxl

XLSX = 'Turkiye_Yazilim_Firmalari_v2.xlsx'
SIZE = {'Tier 1': 'Büyük / kurumsal', 'Tier 2': 'Orta / scale-up', 'Tier 3': 'Küçük / startup'}
APPROACH = {'Büyük / kurumsal': 'Kariyer sayfası + yeni mezun/MT programı + içeriden çalışana referans isteği',
            'Orta / scale-up': "Engineering Manager / Tech Lead'e LinkedIn mesajı + kariyer sayfası",
            'Küçük / startup': "Kurucuya / CTO'ya doğrudan kısa mail veya LinkedIn mesajı",
            'Bilinmiyor (çoğunlukla küçük)': "Kurucuya / CTO'ya doğrudan kısa mail veya LinkedIn mesajı"}
SRC = {'ana': 'Oyun firmaları listesi (game-firmaları güncel.xlsx)', 'aday': 'Oyun firmaları derin araştırma (eksik adaylar)'}

new = json.load(open('data/oyun_yeni.json', encoding='utf-8'))
wb = openpyxl.load_workbook(XLSX)
ws = wb['Firmalar']
old_last = ws.max_row
hdr = [c.value for c in ws[1]]
col = {h: i + 1 for i, h in enumerate(hdr)}
# mevcut bir Oyun satirindan roller/hedef alan ve bicim
game_row = next(r for r in ws.iter_rows(min_row=2) if r[col['Kategori'] - 1].value == 'Oyun')
roles = game_row[col['Uygun roller'] - 1].value
target = game_row[col['Hedef alan eşleşmesi'] - 1].value
style_row = {c.column: c for c in ws[2]}
link_font = copy.copy(ws.cell(2, col['LinkedIn şirket']).font)

r = old_last
for g in new:
    r += 1
    size = SIZE.get((g.get('tier') or '').strip(), 'Bilinmiyor (çoğunlukla küçük)')
    city = (g.get('city') or 'Belirtilmemiş').strip()
    note = ' · '.join(x for x in (g.get('kat'), g.get('note')) if x)
    name = g['name']
    q = quote(name)
    web = g.get('url')
    vals = {'No': r - 1, 'Firma': name, 'Kategori': 'Oyun', 'Alt alan / Not': note[:400], 'Şehir': city, 'Büyüklük (tahmini)': size,
            'Yazılım odağı': 'Yazılım şirketi', 'Uygun roller': roles, 'Hedef alan eşleşmesi': target, 'Önerilen yaklaşım': APPROACH[size],
            'Web sitesi': re.sub(r'^https?://(www\.)?', '', web).rstrip('/') if web else None, 'LinkedIn şirket': 'Şirketi bul',
            'LinkedIn çalışanlar': 'Mühendisleri gör', 'LinkedIn İK / recruiter': "İK'yı gör", 'Google: kariyer sayfası': 'Kariyer ara',
            'Kaynak': SRC[g['src']], 'Durum': 'Araştırılacak', 'Takip tarihi (+7 gün)': f'=IF(U{r}="","",U{r}+7)'}
    links = {'Web sitesi': web, 'LinkedIn şirket': f'https://www.linkedin.com/search/results/companies/?keywords={q}',
             'LinkedIn çalışanlar': f'https://www.linkedin.com/search/results/people/?keywords={q}%20software%20engineer',
             'LinkedIn İK / recruiter': f'https://www.linkedin.com/search/results/people/?keywords={q}%20talent%20acquisition',
             'Google: kariyer sayfası': f'https://www.google.com/search?q={q}%20kariyer%20yaz%C4%B1l%C4%B1m'}
    for h, j in col.items():
        c = ws.cell(r, j, vals.get(h))
        src = style_row[j]
        c.font, c.fill, c.border = copy.copy(src.font), copy.copy(src.fill), copy.copy(src.border)
        c.alignment, c.number_format = copy.copy(src.alignment), src.number_format
        if links.get(h):
            c.hyperlink = links[h]
            c.font = copy.copy(link_font)
    ws.row_dimensions[r].height = ws.row_dimensions[2].height
new_last = r


def grow(ref):
    return re.sub(rf'(\$?[A-Z]+\$?){old_last}\b', lambda m: f'{m.group(1)}{new_last}', ref)


ws.auto_filter.ref = grow(ws.auto_filter.ref)
for dv in ws.data_validations.dataValidation:
    dv.sqref = openpyxl.worksheet.cell_range.MultiCellRange(grow(str(dv.sqref)))
cf_old = ws.conditional_formatting
cf_new = openpyxl.formatting.formatting.ConditionalFormattingList()
for rng in cf_old:
    for rule in rng.rules:
        cf_new.add(grow(str(rng.sqref)), rule)
ws.conditional_formatting = cf_new
oz = wb['Özet']
for row in oz.iter_rows():
    for c in row:
        if isinstance(c.value, str) and c.value.startswith('='):
            c.value = grow(c.value)
wb.save(XLSX)
print(f'{len(new)} oyun firmasi eklendi: satir {old_last + 1}-{new_last}; filtre {ws.auto_filter.ref}')
