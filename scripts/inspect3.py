import openpyxl
wb = openpyxl.load_workbook('orig.xlsx')
ws = wb['Firmalar']
for rng in ws.conditional_formatting:
    for r in rng.rules:
        print('CF', rng.sqref, r.type, r.operator, r.formula, r.dxf.fill.bgColor.rgb if r.dxf and r.dxf.fill else None,
              r.dxf.font.color.rgb if r.dxf and r.dxf.font and r.dxf.font.color else None)
h = ws['A1']
print('hdr', h.font.b, h.font.color.rgb if h.font.color else None, h.fill.fgColor.rgb, h.alignment.wrap_text, h.alignment.horizontal, h.border.bottom.style)
b = ws['B2']
print('body', b.font.name, b.font.sz, b.alignment.wrap_text, b.alignment.vertical, b.border.bottom.style, b.border.bottom.color.rgb if b.border.bottom.color else None)
print('row banding', ws['B3'].fill.fgColor.rgb if ws['B3'].fill.fill_type else None, ws['B2'].fill.fill_type)
print('hdr colors by col', [(c.column_letter, c.fill.fgColor.rgb) for c in ws[1]])
print('ws props', ws.sheet_properties.tabColor, ws.sheet_view.zoomScale, ws.sheet_view.showGridLines)
print('=== STRATEJI')
for i, r in enumerate(wb['Strateji & Şablonlar'].iter_rows(values_only=True), 1):
    print(i, r[0])
print('=== KAYNAKLAR')
for r in wb['Kaynaklar'].iter_rows(values_only=True):
    print(r)
print('sheet order', wb.sheetnames)
print('Ozet styles', [(c.coordinate, c.font.b, c.fill.fgColor.rgb) for c in wb['Özet']['A'][:6]])
