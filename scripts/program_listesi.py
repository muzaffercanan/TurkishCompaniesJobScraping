"""Bulunan genc yetenek / staj / yeni mezun program sayfalarini kontrol icin listeler.
Calistir: python -m scripts.program_listesi   ->  Program_Sayfalari.csv (Excel ile acilir)"""
import csv
import os

from app import db

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Program_Sayfalari.csv')


def main():
    con = db.connect()
    rows = con.execute(
        "SELECT c.name, j.title, j.team, j.level, j.url, j.first_seen, j.active FROM jobs j JOIN companies c ON c.id=j.company_id "
        "WHERE j.source='program' ORDER BY j.active DESC, c.name, j.title").fetchall()
    with open(OUT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Firma', 'Program', 'Tur', 'Durum', 'Son basvuru', 'Adres', 'Ilk gorulme', 'Sayfa hala var'])
        for r in rows:
            parts = (r['team'] or '').split(' · ')
            status = parts[1] if len(parts) > 1 else ''
            deadline = parts[2].replace('son başvuru ', '') if len(parts) > 2 else ''
            w.writerow([r['name'], r['title'], r['level'], status, deadline, r['url'], r['first_seen'], 'evet' if r['active'] else 'hayir'])
    print(f'{len(rows)} program sayfasi -> {OUT}')


if __name__ == '__main__':
    main()
