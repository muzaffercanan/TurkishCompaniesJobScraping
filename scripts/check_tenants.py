"""ilanlar.db: her ATS eslesmesinin dogru firmaya ait olup olmadigini konum dagilimindan kontrol et."""
import sqlite3

db = sqlite3.connect('ilanlar.db')
print(f"{'firma':30s} {'kaynak':10s} {'ilan':>4s} {'TR':>4s} {'uzak':>4s} {'yurtdisi':>8s} {'tech':>4s}")
for r in db.execute("""SELECT firm,ats,COUNT(*),SUM(region='Türkiye'),SUM(region='Uzaktan'),SUM(region='Yurt dışı'),SUM(tech=1)
                       FROM jobs WHERE active=1 GROUP BY firm,ats ORDER BY 4 DESC,3 DESC"""):
    print(f'{r[0][:30]:30s} {r[1]:10s} {r[2]:4d} {r[3]:4d} {r[4]:4d} {r[5]:8d} {r[6]:4d}')
print()
for f in ['Adjust (İstanbul)', 'Gain', 'Arena', 'ATP (Ata Technology Platforms)', 'Link Bilgisayar', 'Ace Games', 'Mikro Yazılım',
          'Udemy (Ankara)', 'Sedna Otel Yazılımı', 'OKX TR', 'Binance TR']:
    rows = db.execute('SELECT title,location FROM jobs WHERE firm=? AND active=1 LIMIT 3', (f,)).fetchall()
    print(f, '->', [(t[:34], l[:22]) for t, l in rows])
