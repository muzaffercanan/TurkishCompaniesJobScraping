# İlan Radarı

Türkiye'deki ~2.000 yazılım/teknoloji/oyun firmasının kariyer sayfalarını tarayıp tüm ilanları tek ekranda gösteren, yalnızca bu bilgisayarda çalışan web uygulaması.

## Çalıştırma
`Baslat.bat` dosyasına çift tıkla. Tarayıcıda `http://127.0.0.1:8765` açılır. Kapatmak için siyah pencereyi kapat.
Kod güncellendiğinde açık pencereyi kapatıp `Baslat.bat` ile yeniden açman gerekir.

- **Hızlı tara**: Bilinen ATS'ler, firmaya özel okuyucular ve kariyer sayfasından ilan veren firmalar. Birkaç dakika.
  - ATS'ler: Lever, Greenhouse, Ashby, Workable, SmartRecruiters, Recruitee, Personio, BambooHR, Breezy, Pinpoint, Teamtailor, Workday, SuccessFactors (RMK), Manatal, JazzHR
  - Özel okuyucular: Turkcell, Garanti BBVA, Baykar, Roketsan, HAVELSAN, Türk Telekom, Amazon
- **Yeni eklenenleri tara**: Excel'e sonradan eklenen ya da adresi düzeltilen, henüz hiç taranmamış firmalar.
- **Tam tara**: Tüm firmaların kariyer sayfalarını bulur (gerekirse gerçek tarayıcıyla açar) ve ilanları çıkarır. ~50 dk.
  Kariyer sayfası bulunamayan firmalar 14 günde bir yeniden denenir.
- **Genç yetenek / staj programlarını bul** (tarama menüsü): firmaların kendi sitelerinde genç yetenek, staj, yeni mezun,
  kampüs programı sayfalarını arar (ör. `kariyerim.turkcell.com.tr/genc-yetenek` ve oradan bağlanan `/gncytnkstaj`). 20–40 dk;
  son 30 günde bakılan firmalar atlanır. Bulunan sayfalar `program` kaynağıyla listelenir; seviye Staj ya da Junior / Yeni mezun,
  "Program · Başvuru açık / kapalı / Durum belirsiz · son başvuru …" bilgisi ekip alanında görünür. Hızlı tarama bilinen program
  sayfalarını her seferinde yeniden okur (başvurular açılınca durum değişir).
  Doğruluk kuralları: sayfa firmanın kendi alan adında olmalı; başlığı ya da adresi program anlatmalı; 404, haber/blog/basın,
  KVKK, PDF ve ürün/kampanya sayfaları (öğrenci kartı, öğrenci tarifesi…) elenir. Kontrol listesi: `python -m scripts.program_listesi`
  → `Program_Sayfalari.csv`. Yanlış bir sayfayı "Gizle" ile kaldırabilirsin.
- **Firmalar** sekmesi: her firmanın durumu; site / kariyer adresi düzeltme ve **Yeniden keşfet**; her satırda tek tıkla
  **Kariyer.net** ve **LinkedIn** araması (bu siteler taranmaz, arama senin tarayıcında açılır).
  Üstteki **Web sitesi bulma** bölümünden bir Brave Search API anahtarı girersen, sitesi bilinmeyen firmaların sitesi aranır.
- **Kaynak sağlığı**: her kaynağın son iki taraması; ilan sayısı birden düşen, ilanları bir anda değişen (okuyucu bozulmuş
  olabilir) ve hata veren kaynaklar en üstte.
- **Arama kısayolları**: LinkedIn, Kariyer.net, Indeed, Glassdoor, Google İş İlanları, Youthall, Coderspace, Techcareer, Secretcv.

## Arayüz
- **Hızlı filtreler**: “Bana uygun” (junior + staj, yazılım/teknik, Türkiye/uzaktan), seviye etiketleri, eklenme zamanı (bugün / 3 / 7 / 30 gün). Diğer filtreler **Filtreler** düğmesinde; seçili olanlar etiket olarak görünür ve tek tıkla kaldırılır. Filtreler bir sonraki açılışta hatırlanır.
- **Görünümler**: Tümü · Favoriler · Başvurduklarım · Gizlenenler. Favori ve başvuru listelerinde kapanmış ilanlar da kalır.
- **İlan detayı**: satıra tıklayınca sağdan açılır. Açıklama, “en az N yıl / yeni mezun / intern” gibi deneyim ifadelerinin öne çıkarılmış özeti, kişisel not (otomatik kaydolur), ok düğmeleriyle önceki/sonraki ilan. Ctrl+tık ilanı doğrudan yeni sekmede açar.
- **Firmaya göre grupla**, **sıkı görünüm**, **CSV dışa aktarma**, açık/koyu/sistem **tema**, sonsuz kaydırma.
- **Geri al**: gizle / başvurdum işaretleri toast ile geri alınabilir. Tarama bitince “yeni ilanları göster” kısayolu çıkar; üstte son taramanın ne kadar eski olduğu görünür.
- **Klavye**: `/` ara · `j`/`k` gezin · `Enter` detay · `o` ilana git · `s` favori · `a` başvurdum · `h` gizle · `f` filtreler · `g` grupla · `t` tema · `1`–`5` sekmeler · `?` yardım.

## Seviye etiketleri
Hiçbir ilan elenmez; seviye yalnızca filtre/sıralama için bir etikettir.
1. Başlıkta "junior / new grad / intern / senior / lead…" varsa o kullanılır.
2. Yoksa ilan açıklamasındaki deneyim ifadelerine bakılır ("en az 3 yıl", "2-4 years", "yeni mezun", "tecrübe şartı aranmamaktadır"):
   0–1 yıl → Junior / Yeni mezun · 2–4 yıl → Orta (2-4 yıl) · 5+ yıl → Kıdemli+. Bulunan en düşük yıl "en az N yıl" olarak gösterilir.
3. Açıklamayı liste ucu vermeyen kaynaklarda (Workday, SmartRecruiters, Garanti, Baykar, genel sayfalar) detay sayfası
   yalnızca Türkiye/uzaktan/belirtilmemiş konumlu ilanlar için, her taramada firma başına en fazla 40 ilan çekilir (siteleri yormamak için);
   kalanlar sonraki taramalarda tamamlanır.

## Kaynak etiketleri
| Etiket | Anlamı |
|---|---|
| `lever`, `greenhouse`, … | ATS'in herkese açık arayüzü, güvenilir |
| `ozel` | Firmaya özel yazılmış okuyucu |
| `genel` | Kariyer sayfasından kural tabanlı çıkarım (ilan adresi + unvan, ya da aynı listede yan yana duran unvanlar); arada ilan olmayan bağlantılar olabilir, "Gizle" ile temizle |

## Testler
- Çevrimdışı test (kaydedilmiş gerçek yanıtlarla, internet gerekmez): `python -m unittest discover -s tests -t .`
- Bir site yapısını değiştirdiyse yanıtları yeniden kaydet: `python -m tests.record` (ya da tek kaynak: `python -m tests.record custom_baykar`)
  ve testleri tekrar çalıştır. Kayıttakinden farklı sayıda ilan çıkması okuyucunun bozulduğunu gösterir.

## Klasörler
- `app/` uygulama kodu: `server.py` web sunucusu, `scanner.py` tarama, `careers.py` kariyer sayfası keşfi, `ats.py` ATS okuyucuları,
  `custom.py` firmaya özel okuyucular, `generic.py` genel ayrıştırıcı, `programs.py` genç yetenek / staj program sayfaları, `seniority.py` açıklamadan seviye, `enrich.py` ilan detayı,
  `sites.py` web sitesi keşfi, `search.py` arama API'si
- `tests/` testler ve `tests/fixtures/` kaydedilmiş yanıtlar
- `app/static/` arayüz: `index.html` iskelet, `app.css` tasarım sistemi, `app.js` mantık (derleme gerektirmez)
- `data/app.db` tüm firmalar, ilanlar ve işaretlerin (başvurdum/gizle/favori/not). `data/config.json` arama API anahtarı (yalnızca bu bilgisayarda).
- `Turkiye_Yazilim_Firmalari_v2.xlsx` firma listesi. Uygulama her açılışta Excel'e yeni eklenen firmaları alır.

## Gereksinimler
Python 3.12, `pip install flask playwright openpyxl`, `python -m playwright install chromium`.
