import openpyxl, collections
wb = openpyxl.load_workbook('orig.xlsx')
ws = wb['Firmalar']
hdr = [c.value for c in ws[1]]
for c in ws[2]:
    print(c.column_letter, hdr[c.column - 1], '|', repr(c.value)[:80], '| link=', c.hyperlink.target if c.hyperlink else None,
          '| fill=', c.fill.fgColor.rgb if c.fill and c.fill.fill_type else None, '| font=', c.font.color.rgb if c.font.color else None, c.font.u)
print('row height', ws.row_dimensions[2].height, ws.row_dimensions[1].height)
print('widths', {k: v.width for k, v in ws.column_dimensions.items()})
# link formulas of other rows
r = list(ws.iter_rows(min_row=5, max_row=5))[0]
for c in r[9:14]:
    print(c.coordinate, c.value, c.hyperlink.target if c.hyperlink else None)
# role / approach / target by category
m = collections.defaultdict(collections.Counter)
for row in ws.iter_rows(min_row=2, values_only=True):
    m[row[2]][(row[6], row[7], row[8])] += 1
for k, v in m.items():
    print('##', k)
    for kk, n in v.most_common(3):
        print('   ', n, kk)
print('--- city "—" rows')
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[4] == '—':
        print(row[1], '|', row[2], '|', row[3][:60])
print('--- sample Ankara')
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[4] == 'Ankara':
        print(row[1], '|', row[2])
