"""ilanlar.db'den ozet: firma bazinda sayilar + yeni mezun/junior ilanlari + seviyesi yazmayan teknik TR ilanlari."""
import datetime as dt, sqlite3, sys

db = sqlite3.connect('ilanlar.db')
today = dt.date.today()
LIM = int(sys.argv[1]) if len(sys.argv) > 1 else 45

print(f"{'firma':18s} {'kaynak':10s} {'aktif':>5s} {'teknik':>6s} {'TR-teknik':>9s} {'junior':>6s} {'staj':>5s}")
for r in db.execute("""SELECT firm, ats, COUNT(*), SUM(tech=1), SUM(tech=1 AND region IN ('Türkiye','Belirsiz')),
        SUM(tech=1 AND level='Junior / Yeni mezun' AND region IN ('Türkiye','Uzaktan','Belirsiz')), SUM(tech=1 AND level='Staj' AND region IN ('Türkiye','Uzaktan','Belirsiz'))
        FROM jobs WHERE active=1 GROUP BY firm, ats ORDER BY 5 DESC, 3 DESC"""):
    print(f'{r[0][:18]:18s} {r[1]:10s} {r[2]:5d} {r[3]:6d} {r[4]:9d} {r[5]:6d} {r[6]:5d}')


def show(title, where):
    rows = db.execute(f"SELECT firm,title,location,posted,first_seen,url FROM jobs WHERE active=1 AND tech=1 AND {where} ORDER BY firm,title").fetchall()
    print(f'\n### {title}: {len(rows)}')
    for firm, t, loc, posted, fs, url in rows[:LIM]:
        age = (today - dt.date.fromisoformat(posted or fs)).days
        print(f'  {firm[:14]:14s} | {t[:56]:56s} | {loc[:18]:18s} | {age:5d}g | {url}')
    if len(rows) > LIM:
        print(f'  ... +{len(rows) - LIM} ilan daha (ilan_raporu.xlsx)')


show('JUNIOR / YENI MEZUN (TR + uzaktan)', "level='Junior / Yeni mezun' AND region IN ('Türkiye','Uzaktan','Belirsiz')")
show('SEVIYE YAZMAYAN teknik ilanlar (TR)', "level='Seviye yazmıyor' AND region IN ('Türkiye','Belirsiz')")
