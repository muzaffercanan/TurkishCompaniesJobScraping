import collections, random, re
import openpyxl

wb = openpyxl.load_workbook('Turkiye_Yazilim_Firmalari_v2.xlsx')
print(wb.sheetnames)
ws = wb['Firmalar']
print('dims', ws.dimensions, 'filter', ws.auto_filter.ref, 'freeze', ws.freeze_panes)
hdr = [c.value for c in ws[1]]
print(hdr)
rows = list(ws.iter_rows(min_row=2))
print('rows', len(rows))
# bos zorunlu alanlar
for name, idx in [('Firma', 1), ('Kategori', 2), ('Sehir', 4), ('Buyukluk', 5), ('Odak', 6), ('Roller', 7), ('Yaklasim', 9), ('Kaynak', 15), ('Durum', 16)]:
    miss = sum(1 for r in rows if not r[idx].value)
    print(f'  bos {name}: {miss}')
# yinelenen isim
cnt = collections.Counter(r[1].value.lower() for r in rows)
print('ayni adli firma:', [k for k, v in cnt.items() if v > 1][:15])
# formul ve linkler
bad = [r[0].row for r in rows if r[21].value != f'=IF(U{r[0].row}="","",U{r[0].row}+7)']
print('formul hatali satir:', bad[:5])
nolink = [r[1].value for r in rows if not (r[11].hyperlink and r[12].hyperlink and r[13].hyperlink and r[14].hyperlink)]
print('linki eksik:', nolink[:5], len(nolink))
print('web linkli', sum(1 for r in rows if r[10].hyperlink), 'webli metin', sum(1 for r in rows if r[10].value))
print('web metin var ama link yok', sum(1 for r in rows if r[10].value and not r[10].hyperlink))
# eski satirlarin takip alanlari bos mu
print('DV', [(str(d.sqref), d.formula1[:30]) for d in ws.data_validations.dataValidation])
print('CF', [(str(k.sqref), [r.type for r in k.rules]) for k in ws.conditional_formatting])
# Ankara ornekleri
random.seed(7)
ank = [r for r in rows if r[4].value == 'Ankara' and r[15].value and ('ODTÜ' in r[15].value or 'Cyberpark' in r[15].value or 'Hacettepe' in r[15].value)]
print('yeni Ankara', len(ank), collections.Counter(r[15].value for r in ank))
for r in random.sample(ank, 14):
    print(' ', r[1].value, '|', r[2].value, '|', r[5].value, '|', r[6].value, '|', (r[3].value or '')[:70], '|', r[10].value)
# Ozet
oz = wb['Özet']
fs = [(c.coordinate, c.value) for row in oz.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith('=')]
print('Ozet formul sayisi', len(fs)); print(fs[:3], fs[-2:])
# Ozet toplamlari python ile
cats = collections.Counter(r[2].value for r in rows)
print('kategori sayisi', len(cats), 'toplam', sum(cats.values()))
