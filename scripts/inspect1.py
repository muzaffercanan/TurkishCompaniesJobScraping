import re, sys
sp = sys.argv[1]
t = open(sp + '/odtu_f.html', encoding='utf-8').read()
print('ODTU tables', len(re.findall('<table', t)), 'tr', len(re.findall('<tr', t)), 'li', len(re.findall('<li', t)))
j = t.find('<tbody')
print(t[j:j + 1800] if j > 0 else 'no tbody')
print('=== CP')
c = open(sp + '/cp.html', encoding='utf-8').read()
print('cp imgs', len(re.findall(r'class="img-responsive" />', c)))
print(re.findall(r'href="([^"]*(?:page|sayfa|p=)[^"]*)"', c)[:20])
print(re.findall(r'<ul class="pagination.*?</ul>', c, flags=re.S)[:1])
print('=== HT cats')
h = open(sp + '/ht_f.html', encoding='utf-8').read()
print(re.findall(r'href="(/tr/firma_rehberi/[^"]+)"\s*>([^<]+)</a></div>', h))
