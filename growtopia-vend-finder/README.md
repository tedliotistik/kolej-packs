# Growtopia Vend Finder

Discord'a girmeden eşya fiyatı aramak için iki seçenek var:

| | **A) Overlay penceresi** (önerilen) | **B) Proxy + oyun içi `/vend`** |
|---|---|---|
| Ban riski | **Yok**: oyuna, oyun dosyalarına ve ağ trafiğine dokunmaz | Var: proxy Growtopia kurallarına aykırı |
| Nasıl açılır | Oyun açıkken **F8** → üstte pencere açılır | Sohbete `/vend <eşya>` yazılır |
| Veri | Kendin eklersin (`+ Ekle`), veya B'nin topladığı dosyayı okur | Girdiğin dünyalardaki vend'leri otomatik kaydeder |

İkisi aynı veri dosyasını (`data/vend_finder.tsv`) kullanır; aynı klasöre koyarsan proxy'nin
topladığı fiyatlar overlay'de de görünür.

---

# A) Overlay penceresi (ban riski yok)

`overlay/vend_overlay.py` (derlenmiş hali `VendOverlay.exe`): her zaman üstte duran küçük
bir arama penceresi.

- **F8** (ayarlanabilir) ile açılır/kapanır. **Esc** gizler, **Ctrl+Q** kapatır.
- En üstteki kutuya **eşya adını yaz**; sonuçlar yazdıkça güncellenir. Tam isim eşleşmesi
  varsa sadece o eşya, yoksa adında aradığın kelime geçen tüm eşyalar listelenir.
- Sonuç tablosu: **Fiyat · Eşya · Dünya · Konum · Güncellenme tarihi** ("09.11.2026 00:57 (2 sa once)").
  7 günden eski kayıtlar gri görünür.
- **Filtreler:**
  - Sıralama: *Ucuzdan pahalıya* (varsayılan), *Pahalıdan ucuza*, *En yeni önce*, *En eski önce*
    (Fiyat / Güncellenme başlığına tıklayınca da değişir)
  - Güncellenme: *Tüm zamanlar, Son 1 saat, Son 24 saat, Son 3 gün, Son 7 gün, Son 30 gün*
  - Dünya adı ve *Max WL/adet* fiyat sınırı
- **+ Ekle** (Ctrl+N): eşya, dünya, fiyat (WL / DL / BGL adet başı veya "X adet / WL") ve
  istersen koordinat girersin. Aynı dünyadaki aynı eşya (veya aynı koordinat) güncellenir.
- Satıra **çift tık**: dünya adını panoya kopyalar (oyunda dünya adını yapıştırırsın).
  **Sağ tık**: düzenle, "fiyat hâlâ aynı" (tarihi yeniler), sil, dünyanın tüm ilanlarını sil.
- Veri dosyası değişirse (ör. proxy yeni dünya kaydettiğinde) pencere kendini yeniler.

**Kurulum:** GitHub Actions'taki **Vend Finder** iş akışından `VendOverlay-windows`
dosyasını indir, `VendOverlay.exe`'yi bir klasöre koyup çalıştır. Python yüklüyse
`python overlay/vend_overlay.py` de olur (ek paket gerekmez).

İlk açılışta yanında `config.json` oluşur:

```json
{
  "hotkey": "F8",
  "data_file": "data/vend_finder.tsv",
  "opacity": 0.95,
  "always_on_top": true,
  "start_hidden": false
}
```

`hotkey` için `F1`–`F12`, `CTRL+SHIFT+V` gibi kombinasyonlar olur. Kısayol Windows'un
`RegisterHotKey` özelliğiyle alınır (klavye dinleme / hook yok). Growtopia tam ekran
modundaysa pencere arkada kalabilir; oyunu **pencereli** veya **kenarlıksız** modda oynaman
önerilir.

> Not: Ban riski olmadan **otomatik** veri toplamak mümkün değil. Otomatik toplama ya
> proxy (B seçeneği) ya da oyun belleğini okumayı gerektirir, ikisi de kurallara aykırı.
> Overlay tek başına kullanıldığında fiyatları sen eklersin.

## Overlay + Discord Vend Finder botu (selfbot — Discord ban riski var)

Overlay, aramayı Discord'daki **Vend Finder** botuna da sorabilir. Arama kutusuna eşya adını
yazıp **Enter**'a (veya "Discord'da ara" düğmesine) basınca program **senin Discord
hesabınla** botun arama komutunu bir kez gönderir, cevabındaki ilanları (fiyat, dünya, konum,
tarih) okur ve listeye ekler. Bot birden fazla sayfa gönderirse en fazla `max_pages` sayfa
okunur.

- Her arama tek bir komut demek (elle yazmakla aynı). 6 sn bekleme süresi ve 2 dk önbellek
  var; botun veritabanının tamamını indirmez.
- **Uyarı:** Kullanıcı hesabını otomatikleştirmek (selfbot) Discord kurallarına aykırıdır;
  hesabın banlanabilir. Mümkünse yan hesap kullan. Program kendini resmi Discord uygulaması
  gibi göstermez; Discord bunu reddederse hata mesajı gösterir.
- **Token = hesabının şifresi gibidir.** Sadece kendi bilgisayarındaki `config.json`'a yaz,
  kimseyle (bana da) paylaşma, ekran görüntüsüne girmesin.

Ayar (`config.json`, VendOverlay.exe'nin yanında):

```json
"discord": {
  "enabled": true,
  "token": "BURAYA_TOKEN",
  "channel_link": "https://discord.com/channels/SUNUCU_ID/KANAL_ID",
  "bot_name": "Vend Finder",
  "command": "",
  "query_option": "",
  "max_pages": 3
}
```

- `channel_link`: botu kullandığın kanala sağ tık → **Linki Kopyala**.
- `command` / `query_option` boş kalırsa program botun komutlarından arama komutunu kendisi
  seçer. Yanlış komutu seçerse `data/discord_commands.json` dosyasındaki komut listesine
  bakıp doğru adı yaz.
- Her aramadan sonra botun ham cevabı `data/discord_last_reply.json` dosyasına yazılır.
  Fiyatlar yanlış okunursa bu dosya parser'ı düzeltmek için gerekir (içinde token yoktur).

---

# B) Proxy + oyun içi /vend (ban riski var)

Proxy açıkken **girdiğin her dünyadaki** vending machine / DigiVend'leri okuyup bilgisayarına
kaydeder. Sonra oyunda `/vend <eşya>` yazdığında sadece senin gezdiğin dünyalardaki fiyatları
en ucuzdan pahalıya gösterir.

```
[Vend Finder] magplant icin 3 ilan (en ucuz once):
1. 2 DL 50 WL Magplant 5000 - MAGSHOP (10, 20) - 2 sa once
2. 2 DL 70 WL Magplant 5000 - BUYMAG (4, 51) - 1 gun once
...
Dunyaya gitmek icin: /vgo <numara>
```

## Nasıl çalışır (proxy)

[GTProxy](https://github.com/ZTzTopia/GTProxy) (açık kaynak Growtopia proxy'si) oyun ile
Growtopia sunucusu arasına girer. Bu klasördeki yama GTProxy'nin Lua script motoruna
vending machine verisini ve dünya adını açar; `scripts/vend_finder.lua` da:

1. Bir dünyaya girdiğinde (sunucu dünya haritasını gönderdiğinde) içindeki tüm vend'leri okur:
   eşya, fiyat, koordinat.
2. `data/vend_finder.tsv` dosyasına kaydeder (o dünyanın eski kaydının yerine yazar; vend'ler
   kaldırılmışsa dünyayı siler).
3. Sohbete yazdığın `/vend`, `/find` vb. komutları yakalar (sunucuya gitmez) ve cevabı oyun
   konsoluna yazar.

Fiyat notu: Growtopia vend fiyatı ya "her biri X WL" ya da "1 WL'ye X tane" şeklindedir.
Sıralama tek eşya başına WL fiyatına göredir. 100 WL = 1 DL, 100 DL = 1 BGL.
Stok miktarı dünya verisinde gelmediği için gösterilmez.

## Komutlar

| Komut | Açıklama |
|---|---|
| `/vend <eşya>` | Girdiğin dünyalardaki en ucuz 10 ilan. Tam isim eşleşmesi varsa sadece onu, yoksa ismin içinde geçenleri gösterir. |
| `/find <eşya>` | `/vend` ile aynı. |
| `/vgo <numara>` | Son aramadaki ilanın dünyasına ışınlanır (GTProxy'nin `/warp` komutunu kullanır). |
| `/vendworlds` | Kayıtlı dünyalar, vend sayısı ve ne zaman tarandığı. |
| `/venddel <dünya>` | Bir dünyayı kayıttan siler. |
| `/vendhelp` | Komut listesi. |

## Kurulum (proxy, Windows)

1. Bu repodaki GitHub Actions'ta **Vend Finder** iş akışının son başarılı çalışmasından
   `VendFinder-windows` dosyasını indirip bir klasöre çıkar.
   (Elle derlemek istersen aşağıdaki "Kendin derle" kısmına bak.)
2. `hosts-ekle.bat` dosyasına sağ tıkla → **Yönetici olarak çalıştır**. Bu, Growtopia'nın
   `www.growtopia1.com` / `www.growtopia2.com` adreslerini bilgisayarındaki proxy'ye yönlendirir.
3. `Proxy.exe`'yi çalıştır (ilk açılışta `config.json` oluşturur). Pencere açık kalsın.
4. Growtopia'yı aç ve normal giriş yap. Konsolda `[Vend Finder]` mesajları görmelisin.
5. Satış dünyalarını gez; her dünya otomatik kaydedilir. Sonra `/vend <eşya>` yaz.

Proxy olmadan normal oynamak için `hosts-kaldir.bat`'ı yönetici olarak çalıştır.

Veriler `Proxy.exe`'nin yanındaki `data/vend_finder.tsv` dosyasında durur (Excel ile de
açılabilir). Bulutta tutmak istersen bu klasörü OneDrive/Google Drive klasörüne koyman yeterli.

## Uyarılar

- **Ban riski:** Proxy kullanmak Growtopia kullanım şartlarına aykırıdır ve hesabın
  banlanabilir. Bu eklenti sadece gelen dünya verisini okur ve sunucuya hiçbir paket eklemez
  (sadece `/vgo` normal bir dünya giriş isteği gönderir), ama proxy'nin kendisi tespit
  edilebilir. Riski bilerek kullan; mümkünse önce yan hesapla dene.
- Veriler sadece **senin girdiğin** dünyalardan gelir ve girdiğin andaki fiyatları gösterir.
  Eski fiyatlar için yaş bilgisine bak ("2 sa once", "3 gun once").
- Oyun güncellemesiyle dünya veri formatı değişirse GTProxy'nin de güncellenmesi gerekebilir.
  O durumda `.github/workflows/vend-finder.yml` içindeki `GTPROXY_COMMIT` değerini yeni bir
  GTProxy sürümüne çekip yamanın hâlâ uygulandığını kontrol et.

## Ek script: Auto Tile (`/ac`) — ban riski YÜKSEK

`scripts/auto_tile.lua`: kendi yaptığın vurma / blok koyma tıklamalarını kaydedip
tekrar eder. GTProxy fareyi göremez; onun yerine oyunun tıklayınca sunucuya gönderdiği
paketi **bayt bayt aynen** kaydeder ve zamanlayıcıyla tekrar yollar. Bu yüzden oyun
alt-tab'dayken de çalışır.

| Komut | Açıklama |
|---|---|
| `/ac kaydet` | Kaydı başlatır. Sonra istediğin karelere vur / blok koy (en fazla 20). |
| `/ac bitti` | Kaydı bitirir. |
| `/ac basla [ms] [tur]` | Kayıtlı tıklamaları sırayla `ms` arayla tekrar eder (varsayılan 250, en az 100). `tur` verilirse o kadar tur sonra durur. |
| `/ac dur` | Durdurur. |
| `/ac liste` / `/ac temizle` | Kayıtları gösterir / siler. |

- Paketin içinde kayıt anındaki karakter konumun var: **çalışırken yürüme**.
- Dünya değiştirince kayıtlar silinir ve tekrar durur; bağlantı koparsa da durur.
- Blok koyma tekrarı, envanterde blok bittiğinde sunucu tarafından reddedilir.
- **Uyarı:** Bu otomasyon (bot) sayılır. Growtopia bunu proxy kullanmaktan daha sert
  cezalandırır; sabit aralıklı, insansız tıklamalar tespit edilmesi kolay bir davranıştır.
  Ana hesabında kullanma. Gerçek oyunda hiç test edilmedi.
- İstemiyorsan `scripts/auto_tile.lua` dosyasını silmen yeterli.

## Kendin derle

```bash
git clone https://github.com/ZTzTopia/GTProxy.git
cd GTProxy
git checkout 0105cd5e7f9312cf9289faf18596d357068da088
git submodule update --init --recursive
git apply ../growtopia-vend-finder/patches/0001-vend-finder-lua-bindings.patch
git apply ../growtopia-vend-finder/patches/0002-dns-over-https-ca-bundle.patch
pip install "conan>2.0"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

Sonra `build/src/Release/Proxy.exe`, `build/conan/build/*.dll`, GTProxy'nin `resources/`
klasörü ve bu repodaki `scripts/vend_finder.lua` (GTProxy'nin `scripts/` klasörüne, örnek
test scriptlerini koymadan) aynı klasörde olmalı.

## Yamanın içeriği (`patches/`)

GTProxy'ye eklenenler:

- `world:get_name()` – şu anki dünyanın adı.
- `world:get_vendings()` – dünyadaki tüm vend'ler: `{ x, y, item_id, price, tile_id }`.
- `TileExtra:get_as_vending()` ve tile-extra Lua tiplerinin kaydı (önceden hiç çağrılmıyordu).
- `storage.read/write/now/path` – scriptlerin sadece `data/` klasörüne dosya yazabildiği
  küçük bir kayıt API'si (GTProxy Lua'da `io`/`os` kütüphanelerini açmıyor).
- `/warp` komutundaki bir hata düzeltmesi (dünya adı gecikmeli görevde referansla
  tutuluyordu, ışınlanma bozuk isimle gidebiliyordu).
- `0002-dns-over-https-ca-bundle.patch`: GTProxy gerçek Growtopia sunucusunun adresini
  DNS-over-HTTPS ile bulur; bu istek bazı Windows bilgisayarlarda sertifika doğrulamasında
  hata veriyordu ("DNS request failed: SSLServerVerification"). Artık pakete eklenen
  `resources/cacert.pem` (Mozilla CA listesi) ile doğrulanıyor ve Cloudflare çalışmazsa
  Google DNS deneniyor.

## Testler

```bash
pip install lupa pytest
pytest growtopia-vend-finder/tests          # Linux'ta GUI testi için: xvfb-run -a pytest ...
```

Testler overlay'in veri/arama/filtre mantığını ve penceresini, proxy scriptinin de tarama,
kaydetme/yükleme, arama, sıralama ve komutlarını (GTProxy API'si taklit edilerek) doğrular.
