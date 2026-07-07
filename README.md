# Pelasko SmartFind AI

دستیار فروش هوشمند فارسی با FAISS، GapGPT و WebSocket.

پروژه **فقط با Docker** اجرا می‌شود — API و کلاینت React هر دو داخل container بالا می‌آیند.

## ساختار پروژه

```
pelasko-smartfind-ai/
├── backend/                 # FastAPI + FAISS + GapGPT
│   ├── app/
│   └── scripts/
├── client/                  # React chat UI (nginx)
│   ├── Dockerfile
│   └── nginx.conf
├── docker/
│   └── entrypoint.sh
├── data/                    # index.faiss + products.pkl
├── .env.example
├── Dockerfile               # API image
├── docker-compose.yml
└── Makefile
```

## پیش‌نیاز

- Docker
- Docker Compose

## راه‌اندازی

```bash
make setup
```

فایل `.env` ساخته می‌شود. حداقل این مقادیر را تنظیم کنید:

```env
GAPGPT_API_KEY=your_key_here
PUBLIC_HOST=localhost
PORT=8000
CLIENT_PORT=5173
```

سپس:

```bash
make up
```

یا در background:

```bash
make up-d
```

## آدرس سرویس‌ها

بعد از `make setup` یا `make urls`:

| سرویس | متغیر env | پیش‌فرض |
|---|---|---|
| API | `API_URL` | `http://localhost:8000` |
| Client | `CLIENT_URL` | `http://localhost:5173` |
| WebSocket | — | `ws://localhost:5173/ws/chat` |

کلاینت از طریق nginx به API وصل می‌شود — نیازی به اجرای جداگانه React نیست.

## متغیرهای محیطی

| Variable | توضیح |
|---|---|
| `PUBLIC_HOST` | hostname عمومی |
| `PORT` | پورت API |
| `CLIENT_PORT` | پورت کلاینت |
| `API_URL` | آدرس کامل API (اختیاری) |
| `CLIENT_URL` | آدرس کامل کلاینت (اختیاری) |
| `CORS_ORIGINS` | originهای مجاز (اختیاری) |
| `GAPGPT_API_KEY` | کلید GapGPT |
| `EMBEDDING_MODEL` | مدل embedding (پیش‌فرض: multilingual برای فارسی) |
| `SEARCH_TOP_K` | تعداد کاندیداهای جستجو (پیش‌فرض: 10) |
| `SEARCH_MIN_SCORE` | حداقل شباهت برای قبول نتیجه (پیش‌فرض: 0.40) |
| `PRODUCTS_API_URL` | API محصولات |
| `INDEX_REBUILD_INTERVAL_HOURS` | بازسازی خودکار index (پیش‌فرض: 24) |

### مثال production

```env
PUBLIC_HOST=smartfind.example.com
API_URL=https://api.example.com
CLIENT_URL=https://chat.example.com
CORS_ORIGINS=https://chat.example.com
```

## دستورات Makefile

```bash
make help          # لیست دستورات
make setup         # ساخت .env
make urls          # نمایش URLها
make up            # اجرای API + Client
make up-d          # اجرا در background
make down          # توقف
make ps            # وضعیت containerها
make logs          # لاگ API
make logs-client   # لاگ کلاینت
make health        # تست /health
make rebuild       # rebuild index از API
make build-index   # rebuild index داخل Docker
make shell         # shell داخل container API
make restart       # restart همه سرویس‌ها
make clean-all     # حذف volumeها
```

## API

```bash
make health
make rebuild        # ساخت index داخل Docker + restart API (پیشنهادی)
make rebuild-api    # فقط وقتی API از قبل بالا است
```

### به‌روزرسانی روی سرور

```bash
git pull
make deploy         # pull + build image + rebuild index
```

یا مرحله‌به‌مرحله:

```bash
git pull
make up-d           # build مجدد image و اعمال env جدید
make rebuild        # ساخت index با مدل جدید
```

> `make restart` فقط container را restart می‌کند و کد/env جدید را اعمال نمی‌کند.
> بعد از تغییر `EMBEDDING_MODEL` حتماً `make rebuild` بزنید.
> اگر metadata index با مدل فعلی نخواند، API در startup خودکار rebuild می‌کند.

## WebSocket Chat

اتصال از مرورگر:

```
ws://{PUBLIC_HOST}:{CLIENT_PORT}/ws/chat
```

پیام:

```json
{"message":"یه ظرف برای مدرسه میخوام که درب داشته باشه"}
```

پاسخ stream:

```json
{"type":"status","content":"دارم محصولات مناسب را بررسی می‌کنم..."}
{"type":"product","data":{"name":"...","price":170000,"colors":[],"specs":[],"link":"","image":"","score":0.45}}
{"type":"message","content":"برای شما محصول زیر مناسب است..."}
{"type":"done"}
```

## بازسازی خودکار Index

هر **24 ساعت** index به‌صورت خودکار از API محصولات rebuild می‌شود.

```env
INDEX_REBUILD_ENABLED=true
INDEX_REBUILD_INTERVAL_HOURS=24
```

## معماری

```
Browser
   |
   |  CLIENT_URL (nginx)
   v
smartfind-client ──proxy /ws──> smartfind-api
                                      |
                                 FAISS + GapGPT
                                      |
                                 Products API
```
