# İlan Radarı

Türkiye'deki ~2.000 yazılım/teknoloji/oyun firmasının kariyer sayfalarını tarayıp tüm ilanları tek ekranda gösteren, yalnızca bu bilgisayarda çalışan web uygulaması.

## Çalıştırma
`Baslat.bat` dosyasına çift tıkla. Tarayıcıda `http://127.0.0.1:8765` açılır. Kapatmak için siyah pencereyi kapat.
Kod güncellendiğinde açık pencereyi kapatıp `Baslat.bat` ile yeniden açman gerekir.
Uygulama açıkken kendiliğinden tarama yapar (aşağıda “Otomatik tarama”); istemezsen sağ üstteki “Son tarama” göstergesinden kapat.

- **Hızlı tara**: Bilinen ATS'ler, firmaya özel okuyucular, iş platformu araması ve kariyer sayfasından ilan veren firmalar. Birkaç dakika.
  - ATS'ler: Lever, Greenhouse, Ashby, Workable, SmartRecruiters, Recruitee, Personio, BambooHR, Breezy, Pinpoint, Teamtailor, Workday,
    SuccessFactors (RMK), Manatal, JazzHR, Rippling, Talentics / Kolay İK
  - Çok uluslu firmaların kariyer platformları (yalnızca Türkiye ilanları): Oracle Recruiting Cloud, Eightfold, Phenom,
    Radancy TalentBrew, Avature (Türkiye filtreli arama adresiyle). Okuyucusu olmayanlar (iCIMS, Taleo, Jobvite, Zoho Recruit,
    Peoplise, Peoplebox, HRPeak, JOIN, Homerun…) tespit edilip kaydedilir, ilanları genel ayrıştırıcıyla okunur.
  - Özel okuyucular: Turkcell, Garanti BBVA, Baykar, Roketsan, HAVELSAN, Türk Telekom, Amazon
    (Garanti BBVA'nın robots.txt'si arama motorları dışındaki botları engelliyor; izin verene kadar okunmaz, durumu `robots.txt engeli`)
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
- **Workday**: hesapta ülke filtresi (yoksa konum filtresi, ör. Mastercard) varsa yalnızca Türkiye ilanları alınır (çok uluslu
  hesaplarda binlerce yurt dışı ilanı gelmez); hesapta hiç Türkiye ilanı yoksa eski ilanlar kapanır.
- **Türkiye'de ilan veren çok uluslu firmalar** (`firmalar_global.json`): Mastercard, Visa, Citi, ING Hubs, J.P. Morgan, Microsoft,
  Ericsson, Nokia, Vodafone, Siemens, Bosch, Cisco, HPE, Analog Devices, Oracle, Uber, DHL, EY, PwC, ilaç ve tüketici firmaları…
  Uygulama her açılışta ve taramada bu listeyi veritabanına eşitler: listede olmayan firmayı ekler, olup da ATS'i bilinmeyen firmaya
  hesabı bağlar (genel ayrıştırıcının bulduğu bağlantılar kapanır). Bu firmalarda **yalnızca Türkiye'deki ilanlar** alınır
  (`tr_only`); listeye firma eklemek için dosyaya `{"firma", "ats", "slug", "extra"}` satırı ekle (`eslesme`: listedeki başka adı).
- **İş platformu araması**: Workable'ın genel aramasındaki tüm Türkiye ilanları her hızlı/tam taramada okunur (`workable-tr`
  kaynağı) ve firmalarına dağıtılır; SmartRecruiters'ın genel aramasında Türkiye'de ilanı görünen firmalar haftada bir (tam
  taramada her seferinde) SmartRecruiters hesaplarıyla eklenir. Listede olmayan firma yalnızca en az bir yazılım/teknik ilanı varsa
  “İş platformundan eklenen” kategorisiyle eklenir; kendi kaynağı olan firmanın ilanları buradan alınmaz (çift kayıt olmasın).
- **Gizli firmalar**: Baykar, TUSAŞ (TEI dahil), Roketsan, ASELSAN ve TÜBİTAK birimlerinin ilanları varsayılan olarak
  **Gizlenenler**'de durur (yenileri de gizli eklenir, “Bana uygun” bildirimi gitmez). Firmalar sekmesindeki **İlanları gizle /
  İlanları göster** düğmesiyle herhangi bir firma için açıp kapatabilirsin.
- **Program konumu**: sayfadan çıkarılır; çok uluslu firmaların Türkiye'den söz etmeyen genel sayfaları "Yurt dışı" sayılır.
- **Kaynak sağlığı**: her kaynağın son iki taraması; ilan sayısı birden düşen, ilanları bir anda değişen (okuyucu bozulmuş
  olabilir) ve hata veren kaynaklar en üstte. Genel ayrıştırıcı kaynakları 5, diğerleri 10 ilandan itibaren denetlenir.
  İlanları bir anda değişen kaynakta (kimlik kayması: adresler değişiyor ya da sayfa her seferinde başka ilanlar gösteriyor)
  o taramada gelen ilanlar "yeni" sayılmaz ve bildirim gönderilmez. turbin.ai bir ilan sitesi olduğu için taranmaz.
- **Arama kısayolları**: LinkedIn, Kariyer.net, Indeed, Glassdoor, Google İş İlanları, Youthall, Coderspace, Techcareer, Secretcv.

## Tarama kuralları (nezaket ve güvenlik)
- **robots.txt**: firma sitelerinde (kariyer, program ve ilan sayfaları, özel okuyucuların uç noktaları, gerçek tarayıcıyla açılan
  sayfalar) robots.txt'ye uyulur; site başına bir kez okunur, yoksa ya da okunamazsa kısıtlama yok sayılır. İzin vermeyen kaynağın
  açık ilanları kapanır ve firma `robots.txt engeli` durumuna geçer; site izin verirse okuma kendiliğinden başlar.
  ATS'lerin belgelenmiş herkese açık API'leri (Lever, Greenhouse, Workday, SmartRecruiters…) bu kuraldan muaftır; firmanın kendi
  alan adındaki arama uçları (Eightfold, Phenom, Avature, TalentBrew, Talentics) ile iş platformu aramaları uyar.
  Kurallar RFC 9309'a göre uygulanır: adrese uyan en uzun kural kazanır (`Disallow: /` + `Allow: /api/pcsx` → `/api/pcsx` serbest).
- **Kimlik**: tüm istekler tek HTTP katmanından (`app/util.py: fetch`) ve aynı kimlikle gider: tarayıcı uyumlu UA + `IlanRadari/1.0`
  (robots.txt'de `User-agent: IlanRadari` ile eşleşir).
- **Sertifika**: HTTPS sertifikası her zaman doğrulanır. Doğrulanamayan sitede (çoğu zaman ara sertifikasını göndermeyen sunucu)
  yalnızca o site için doğrulamasız bağlanılır ve günlüğe yazılır.
- **Yük**: aynı sunucuya aynı anda en fazla 2 istek (`HOST_LIMIT`); 429/503'te `Retry-After` beklenir; detay sayfaları firma başına
  taramada en fazla 40 ve aralarında 0,5 sn.
- **Yapılandırılmış veri**: sayfada schema.org `JobPosting` (application/ld+json) varsa ilan başlık, konum, yayın tarihi ve açıklamayla
  oradan alınır (liste sayfasında ilan, detay sayfasında açıklama + konum). Örneklemde kariyer sayfalarının ~%6'sında, ilan detay
  sayfalarının ~%15'inde bulundu.
- **HTML**: özel okuyucular (Garanti, Roketsan) ve JazzHR / SuccessFactors sayfaları regex yerine HTML ağacıyla okunur
  (`app/dom.py`, yalnızca standart kütüphane). XML/RSS beslemeleri (Personio, Teamtailor, Türk Telekom) sabit etiketli olduğu için düz okunur.
- **Günlük dosyası**: `data/logs/tarama.log` (1 MB × 5 dosya, eskiler silinir): tarama satırları, hataların tam izi, sertifika geri düşüşleri.
  Uygulamadaki **Günlük** sekmesi yalnızca son taramanın son 500 satırını gösterir.

## Arayüz
- **Hızlı filtreler**: “Bana uygun” (junior + staj, yazılım/teknik, Türkiye/uzaktan), seviye etiketleri, eklenme zamanı (bugün / 3 / 7 / 30 gün). Diğer filtreler **Filtreler** düğmesinde; seçili olanlar etiket olarak görünür ve tek tıkla kaldırılır. Filtreler bir sonraki açılışta hatırlanır.
- **Yeni ilan** (`YENİ` etiketi, “Yeni ilan” kutusu ve “Eklenme” seçenekleri aynı kuralı kullanır): yayın tarihi son 3 gün içindeyse, ya da yayın tarihi yoksa firmanın **ilk taramasından sonra** bulunduysa. Bir firma (ya da kaynak) ilk kez tarandığında bulunan ilanlar siteye o gün eklenmiş olmadığı için “yeni” sayılmaz; tarama bittiğinde şeritte “N yeni ilan (+M ilan ilk kez taranan kaynaklardan)” yazar. Bir kaynak daha önce kısmen okunmuşsa (hata, sayfalama) ilk tam okuma yüzlerce sahte “yeni” üretmesin diye tek taramada 50'den ve önceki aktif sayısının 2 katından fazla ilan gelirse o da ilk tarama sayılır (Günlük'te bir satırla belirtilir).
- **Görüldü işareti**: açtığın, favorilediğin, başvurduğun ya da gizlediğin ilan görülmüş sayılır; görülmeyenler kalın yazılır ve solunda nokta taşır. **Görülmemiş** düğmesi yalnız onları gösterir, “tümünü görüldü say” listedekilerin hepsini işaretler (geri alınabilir), `u` tek ilanı çevirir.
- **Otomatik tarama**: uygulama (siyah pencere) açıkken, son tam taramadan bu yana seçilen süre (6 / 12 saat, günde bir, 2 günde bir; varsayılan 12 saat) geçmişse kendiliğinden **hızlı tarama** başlar; ilk kontrol açılıştan ~90 sn sonra, sonra dakikada bir. Son tarama hiçbir kaynağı okuyamadıysa (ör. internet yok) 1 saat sonra tekrar dener. Ayarlar sağ üstteki “Son tarama” göstergesine tıklayınca açılır (açma/kapama, sıklık, bildirim, **Şimdi tara**); `data/config.json` içindeki `auto` anahtarında saklanır. Hiç tarama yapılmamışsa ilk taramayı elle yaparsın. Test sunucusu için `python -m app.server --no-auto`.
- **Sana uygun yeni ilan**: “Bana uygun” kuralına (junior ya da staj, yazılım/teknik, Türkiye / uzaktan / konumu belirtilmemiş) uyan, son 3 günde eklenmiş ve henüz açmadığın ilanlar. Sayfanın üstünde şerit olarak (“11 yeni ilan sana uygun · Göster”) ve sekme başlığında `(11)` olarak görünür; ilanları açtıkça azalır. **Otomatik tarama** yeni bir uygun ilan bulursa ayrıca **Windows masaüstü bildirimi** gönderir (tıklayınca uygulama bu ilanlar açık olarak açılır: `/#fit`). Bildirim PowerShell'in kendi kimliğiyle gelir, ek kurulum gerekmez; Odak/Rahatsız Etme açıksa yalnızca Eylem Merkezi'ne düşer. Elle başlattığın taramalar bildirim göndermez (sonucu zaten ekranda görürsün). Ayar panelindeki **Bildirimi dene** düğmesiyle denenir.
- **Arama**: büyük/küçük harf ve Türkçe harf farkı yok sayılır (`izmir` = İzmir, `yazilim` = yazılım); birden çok kelime yazarsan hepsi (başlık, firma, konum ya da takımda) geçmeli: `backend istanbul`. Sonuçlarda eşleşen kısım vurgulanır.
- **Görünümler**: Tümü · Favoriler · Başvurduklarım · Gizlenenler. Favori ve başvuru listelerinde kapanmış ilanlar da kalır.
- **İlan detayı**: satıra tıklayınca sağdan açılır. Açıklama, “en az N yıl / yeni mezun / intern” gibi deneyim ifadelerinin öne çıkarılmış özeti, kişisel not (otomatik kaydolur), ok düğmeleriyle önceki/sonraki ilan. Ctrl+tık ilanı doğrudan yeni sekmede açar.
- **Sıralama**: hem Liste hem Firmaya göre görünümde aynı firmanın ilanları hep alt alta gelir; firmalar büyükten küçüğe
  sıralanır (Büyük / kurumsal → Orta / scale-up → Küçük / startup → Bilinmiyor; aynı büyüklükte aktif ilanı çok olan önce).
  "Firma içinde" seçimi (en yeni / yayın tarihi / başlık) yalnızca firmanın kendi ilanlarının sırasını belirler.
- **Firmaya göre grupla**, **sıkı görünüm**, **CSV dışa aktarma**, açık/koyu/sistem **tema**, sonsuz kaydırma.
- **Geri al**: gizle / başvurdum işaretleri toast ile geri alınabilir. Tarama bitince “yeni ilanları göster” kısayolu çıkar; üstte son taramanın ne kadar eski olduğu görünür.
- **Klavye**: `/` ara · `j`/`k` gezin · `Enter` detay · `o` ilana git · `s` favori · `a` başvurdum · `h` gizle · `u` görüldü/görülmedi · `f` filtreler · `g` grupla · `t` tema · `1`–`5` sekmeler · `?` yardım.

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
| `workable-tr` | Workable'ın genel aramasındaki Türkiye ilanı (firmanın kendi kaynağı yok) |
| `ozel` | Firmaya özel yazılmış okuyucu |
| `genel` | Kariyer sayfasından kural tabanlı çıkarım (ilan adresi + unvan, ya da aynı listede yan yana duran unvanlar); arada ilan olmayan bağlantılar olabilir, "Gizle" ile temizle |

## Testler
- Çevrimdışı test (kaydedilmiş gerçek yanıtlarla, internet gerekmez): `python -m unittest discover -s tests -t .`
- Bir site yapısını değiştirdiyse yanıtları yeniden kaydet: `python -m tests.record` (ya da tek kaynak: `python -m tests.record custom_baykar`)
  ve testleri tekrar çalıştır. Kayıttakinden farklı sayıda ilan çıkması okuyucunun bozulduğunu gösterir.
- Özel okuyucuları canlı denemek (kayıt yapmaz): `python -m app.custom` (ya da `python -m app.custom roketsan`).

## Klasörler
- `app/` uygulama kodu: `server.py` web sunucusu, `scanner.py` tarama, `careers.py` kariyer sayfası keşfi, `ats.py` ATS okuyucuları,
  `custom.py` firmaya özel okuyucular, `generic.py` genel ayrıştırıcı, `programs.py` genç yetenek / staj program sayfaları, `seniority.py` açıklamadan seviye, `enrich.py` ilan detayı,
  `sites.py` web sitesi keşfi, `search.py` arama API'si, `util.py` ortak HTTP katmanı, `dom.py` küçük HTML ağacı
- `tests/` testler ve `tests/fixtures/` kaydedilmiş yanıtlar
- `app/static/` arayüz: `index.html` iskelet, `app.css` tasarım sistemi, `app.js` mantık (derleme gerektirmez)
- `data/app.db` tüm firmalar, ilanlar ve işaretlerin (başvurdum/gizle/favori/not). `data/config.json` arama API anahtarı (yalnızca bu bilgisayarda).
  `data/logs/` tarama günlükleri.
- `Turkiye_Yazilim_Firmalari_v2.xlsx` firma listesi. Uygulama her açılışta Excel'e yeni eklenen firmaları alır.
- `firmalar_global.json` Türkiye'de ilan veren çok uluslu firmalar ve ATS hesapları (her açılışta eşitlenir).

## Gereksinimler
Python 3.12, `pip install flask playwright openpyxl`, `python -m playwright install chromium`.
