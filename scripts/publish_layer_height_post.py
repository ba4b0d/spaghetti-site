import urllib.request
import json
import http.cookiejar
import sqlite3
import os
import sys

zwnj = "\u200c"

# =========================================================================
# NEW ARTICLE: Layer Height & Print Quality Settings Guide
# =========================================================================
title = f"راهنمای ارتفاع لایه و تنظیمات کیفیت چاپ س{zwnj}بعدی؛ از FDM تا جزئیات میکرونی"
slug = "layer-height-and-print-quality-guide"
summary = f"ارتفاع لایه یکی از کلیدی{zwnj}ترین پارامترهای کیفیت چاپ س{zwnj}بعدی است. در این راهنما یاد می{zwnj}گیرید ارتفاع لایه چقدر روی دقت، سرعت، استحکام و سطح نهایی قطعه اثر می{zwnj}گذارد و بهترین تنظیمات برای هر کاربرد چیست."

content = f"""# راهنمای ارتفاع لایه و تنظیمات کیفیت چاپ س{zwnj}بعدی؛ از FDM تا جزئیات میکرونی

وقتی یک مدل سه بعدی را برای چاپ آماده می کنید، یکی از اولین سوال هایی که در نرم افزار اسلایسر (Slicer) با آن روبه رو می شوید، فیلد **ارتفاع لایه (Layer Height)** است. این عدد ظاهراً ساده، بیشترین تأثیر را روی **دقت سطح، سرعت چاپ و استحکام قطعه** دارد؛ اما بسیاری از افراد تازه‌کار آن را نادیده می‌گیرند و همان مقدار پیش‌فرض را نگه می‌دارند.

در این راهنمای جامع از **اسپاگتی پرینت**، به زبان ساده بررسی می‌کنیم که ارتفاع لایه چیست، چرا مهم است، چه تنظیماتی برای چاپ باکیفیت مناسب شماست و چطور می‌توانید تعادل درست میان سرعت و جزئیات را پیدا کنید.

---

## ۱. ارتفاع لایه دقیقاً چیست؟

در چاپ سه بعدی **FDM**، قطعه به شکل لایه‌های نازک و متوالی روی هم ساخته می‌شود. ارتفاع لایه، همان ضخامت هر یک از این نوارهای پلاستیکی است؛ یعنی فاصله عمودی میان هر دو پاس حرکت هد چاپگر.

به زبان ساده:

- **ارتفاع لایه کم = جزئیات بیشتر و سطح صاف‌تر** اما زمان چاپ طولانی‌تر
- **ارتفاع لایه زیاد = سرعت بالاتر و چاپ سریع‌تر** اما سطح زبرتر و جزئیات کمتر

ارتفاع لایه معمولاً با واحد **میکرون (µm)** یا **میلی‌متر (mm)** نمایش داده می‌شود. برای مثال ارتفاع `0.2 میلی‌متر` معادل `200 میکرون` است.

---

## ۲. تأثیر ارتفاع لایه روی کیفیت نهایی

### الف) دقت و صافی سطح
هرچه ارتفاع لایه کمتر باشد، پله‌های نامرئی سطح (پدیدهٔ **Layer Lines**) ریزتر و کمتر دیده می‌شوند. برای قطعات نمایشی، مجسمه‌ها و دکوری‌ها، ارتفاع پایین تفاوت بزرگی ایجاد می‌کند.

### ب) استحکام مکانیکی
برخلاف تصور رایج، ارتفاع لایه خیلی کم همیشه به معنای استحکام بیشتر نیست. بهترین چسبندگی بین لایه‌ها معمولاً در بازهٔ `0.15 تا 0.28mm` به دست می‌آید. ارتفاع خیلی ریز می‌تواند زمان ماندن پلاستیک مذاب را کاهش دهد و چسبندگی لایه‌ها را ضعیف کند.

### ج) سرعت چاپ
تعداد لایه‌های یک قطعه با کاهش ارتفاع، به‌صورت تصاعدی افزایش می‌یابد. برای نمونه چاپ یک قطعهٔ ۶۰ میلی‌متری با ارتفاع `0.2mm` حدوداً `300` لایه دارد، در حالی که با ارتفاع `0.1mm` به `600` لایه می‌رسد؛ یعنی زمان چاپ تقریباً دو برابر می‌شود.

### د) زمان تکمیل سفارش
اگر سفارش چاپ را به صورت حرفه‌ای ثبت می‌کنید، ارتفاع لایه مستقیماً روی **هزینه و زمان تحویل** اثر می‌گذارد، دقیقاً همان گونه که در [راهنمای محاسبه قیمت پرینت س بعدی](/blog/3d-printing-cost-guide-1405) توضیح داده‌ایم.

---

## ۳. تنظیمات استاندارد ارتفاع لایه برای نازل‌های رایج

نکتهٔ طلایی این است که ارتفاع لایهٔ مناسب، تابعی از **قطر نازل (Nozzle)** است. قانون عمومی: ارتفاع لایه معمولاً باید بین `۲۵٪ تا ۷۵٪` قطر نازل باشد.

| نوع چاپ | ارتفاع لایه پیشنهادی (نازل 0.4mm) | کاربرد |
| ---: | ---: | --- |
| **چاپ فانتزی و تبلیغاتی (دکوری)** | 0.12 – 0.16 mm (۱۲۰ تا ۱۶۰ میکرون) | فیگورها، مجسمه‌ها، تندیس‌ها |
| **چاپ استاندارد و متعادل** | 0.20 mm (۲۰۰ میکرون) | اکثر قطعات کاربردی و روزمره |
| **چاپ سریع و حجمی** | 0.28 – 0.32 mm (۲۸۰ تا ۳۲۰ میکرون) | نمونه‌های اولیه، ماکت‌ها، قطعات بزرگ |

---

## ۴. ارتفاع لایه مناسب هر نوع محصول چیست؟

در فروشگاه **اسپاگتی پرینت** هر کالکشن با هدف خاصی چاپ می‌شود و ارتفاع لایهٔ آن بر همین اساس انتخاب می‌شود:

- **[کالکشن فیگورهای نشسته](/collection/%DA%A9%D8%A7%D9%84%DA%A9%D8%B4%D9%86-%D9%81%DB%8C%DA%AF%D9%88%D8%B1%D9%87%D8%A7%DB%8C-%D9%86%D8%B4%D8%B3%D8%AA%D9%87)**: ارتفاع لایهٔ پایین (۱۵۰ میکرون) برای ثبت جزئیات چهره، سلاح و بافت لباس.
- **[کالکشن فلکسی](/collection/%DA%A9%D8%A7%D9%84%DA%A9%D8%B4%D9%86-%D9%81%D9%84%DA%A9%D8%B3%DB%8C)**: ارتفاع متوسط تا ریز برای حرکت روان مفاصل یکپارچه.
- **[کالکشن تابلوهای دکوراتیو](/collection/%DA%A9%D8%A7%D9%84%DA%A9%D8%B4%D9%86-%D8%AA%D8%A7%D8%A8%D9%84%D9%88-%D8%B3%D9%87-%D8%A8%D8%B9%D8%AF%DB%8C-%D8%A7%D8%A8%D8%B1%D9%82%D9%87%D8%B1%D9%85%D8%A7%D9%86%D8%A7%D9%86)**: لایه‌های بسیار ظریف (۱۲۰ میکرون) برای سطحی کاملاً صاف و براق.
- **[کالکشن حیوانات بافتنی](/collection/%DA%A9%D8%A7%D9%84%DA%A9%D8%B4%D9%86-%D8%AD%DB%8C%D9%88%D8%A7%D9%86%D8%A7%D8%AA-%D8%A8%D8%A7%D9%81%D8%AA%D9%86%DB%8C)**: ترکیبی از ارتفاع ریز برای بافت کاموایی و جزئیات دقیق.
- **اکسسوری‌ها و جاکلیدی‌ها**: ارتفاع استاندارد ۰.۲ برای تعادل میان استحکام و سرعت.

---

## ۵. سه پارامتر مکمل که نباید فراموش کنید

ارتفاع لایه به تنهایی کافی نیست؛ برای رسیدن به کیفیت واقعاً حرفه‌ای، این سه پارامتر را هم تنظیم کنید:

1. **عرض اکستروژن (Extrusion Width)**: معمولاً کمی بیشتر از قطر نازل تنظیم می‌شود تا پاس‌ها به هم بچسبند.
2. **دمای نازل و بستر**: هر متریال نقطهٔ ذوب و چسبندگی خاص خودش را دارد. اگر تازه آغاز به کار کرده‌اید، [راهنمای فیلامنت PLA](/blog/what-is-pla-filament-guide) را از دست ندهید تا اصول پایهٔ تنظیم دما را یاد بگیرید.
3. **پرینت خوب از یک مدل سالم شروع می‌شود**: پیش از چاپ، مطمئن شوید فایل سه بعدی شما بدون سوراخ یا خطا است.

---

## ۶. ارتفاع لایه؛ پرینتی درست، صرف نظر از متریال

مهم‌ترین نکته‌ای که باید به خاطر بسپارید:

> هیچ «بهترین ارتفاع لایه» واحدی برای همهٔ چاپ‌ها وجود ندارد. بهترین تنظیم، ارتفاعی است که با **کاربرد قطعه، قطر نازل و بودجهٔ زمانی شما** هم‌خوانی داشته باشد.

اگر قطعه برای دیده شدن است، برای آن هزینهٔ زمان چاپ بپردازید و ارتفاع را کم کنید. اگر قطعه در حال استفادهٔ روزانه است، ارتفاع استاندارد و استحکام را در اولویت بگذارید.

---

## پرسش‌های متداول (FAQ)

### آیا ارتفاع لایهٔ 0.1 همیشه بهتر از 0.2 است؟
خیر. ارتفاع ۰.۱ زمان چاپ را تقریباً دو برابر می‌کند و گاهی چسبندگی لایه‌ها را کاهش می‌دهد. فقط برای جزئیات ظریف و قطعات نمایشی ارزش این زمان اضافه را دارد.

### حداقل و حداکثر ارتفاع لایه با نازل 0.4 چقدر است؟
عملاً بین `0.08` تا `0.32mm`. خارج از این بازه، کیفیت اکستروژن افت می‌کند.

### برای چاپ سریع چه ارتفاعی انتخاب کنم؟
`0.28` تا `0.32mm` برای ماکت و نمونهٔ اولیه ایده‌آل است؛ سطح زبرتر اما سرعت حداکثری.

### آیا ارتفاع لایه روی قیمت سفارش من تأثیر می‌گذارد؟
بله، مستقیم. زمان چاپ بیشتر یعنی هزینهٔ بیشتر. اگر بودجهٔ مشخصی دارید، دربارهٔ ارتفاع لایهٔ مناسب قطعهٔ خود با تیم **اسپاگتی پرینت** مشورت کنید.

---

## سفارش چاپ باکیفیت در اسپاگتی پرینت

تیم **اسپاگتی پرینت** در تمام کالکشن‌های خود، ارتفاع لایه را متناسب با نوع محصول بهینه می‌کند تا هم جزئیات خیره‌کننده باشد و هم قیمت عادلانه. اگر طرح دلخواه خود را دارید، می‌توانید فایل خود را برای چاپ حرفه‌ای ارسال کنید.

👉 **[مشاهده کاتالوگ کامل محصولات](/)**  
👉 **[ثبت سفارش ساخت طرح دلخواه با فایل یا عکس اختصاصی](/custom-order)**
"""

# =========================================================================
# 1. Update local database (backend/data/3djat.db)
# =========================================================================
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "3djat.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
local_cover = "/uploads/blog/layer-height-quality-guide.webp"

cur.execute("SELECT id FROM blog_posts WHERE slug = ?", (slug,))
row = cur.fetchone()
if row:
    cur.execute(
        "UPDATE blog_posts SET title=?, summary=?, content=?, cover_image=?, is_published=1 WHERE slug=?",
        (title, summary, content, local_cover, slug),
    )
    print(f"Updated local post ID {row[0]}")
else:
    cur.execute(
        "INSERT INTO blog_posts (title, slug, summary, content, cover_image, is_published, views) VALUES (?, ?, ?, ?, ?, 1, 0)",
        (title, slug, summary, content, local_cover),
    )
    print("Inserted local post")

conn.commit()
conn.close()
print("Local DB updated:", db_path)


# =========================================================================
# 2. Publish to Live Site (spaghettiprints.ir) via admin API
# =========================================================================
def publish_live(post_title, post_slug, post_summary, post_content, local_cover_path):
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    login_url = "https://spaghettiprints.ir/api/v1/auth/login"
    login_data = json.dumps({"username": "admin", "password": "Adadep@1625"}).encode("utf-8")
    req_login = urllib.request.Request(
        login_url,
        data=login_data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with opener.open(req_login) as resp:
        print("Logged in to live API.")

    # Upload cover image
    upload_url = "https://spaghettiprints.ir/api/v1/admin/posts/upload-cover"
    boundary = "----SpaghettiBoundary7MA4YWxkTrZu0gW"
    with open(local_cover_path, "rb") as f:
        img_bytes = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(local_cover_path)}"\r\n'
        f"Content-Type: image/webp\r\n\r\n"
    ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req_upload = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "Mozilla/5.0"},
    )
    with opener.open(req_upload) as r:
        upload_data = json.loads(r.read().decode("utf-8"))
    cover_url = upload_data.get("url")
    print("Cover uploaded:", cover_url)

    # Create the post
    post_url = "https://spaghettiprints.ir/api/v1/admin/posts"
    payload = {
        "title": post_title,
        "slug": post_slug,
        "summary": post_summary,
        "content": post_content,
        "cover_image": cover_url,
        "is_published": True,
    }
    req_post = urllib.request.Request(
        post_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with opener.open(req_post) as r:
        res = json.loads(r.read().decode("utf-8"))
    print(f"Published live: \"{res.get('title')}\" (ID {res.get('id')}, slug {res.get('slug')})")


if __name__ == "__main__":
    cover_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "uploads", "blog", "layer-height-quality-guide.webp")
    local_cover_path = os.path.abspath(cover_file)
    if not os.path.exists(local_cover_path):
        print(f"ERROR: cover file not found: {local_cover_path}", file=sys.stderr)
        sys.exit(1)
    publish_live(title, slug, summary, content, local_cover_path)