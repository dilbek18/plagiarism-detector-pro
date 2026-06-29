# Plagiarism Detector Pro — Public Internet Server Ready

Muallif: Dilshod Xo'jayev

Bu paket ochiq serverga joylash uchun tayyorlangan.

## Ishga tushirish buyrug'i

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## Render start command

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables

```text
SEARCH_PROVIDER=internet_server_all
ALLOW_ORIGINS=*
```

## Eslatma

Dastur interfeysida API kalit yoki backend URL ko'rinmaydi. Internet manbalar backend orqali avtomatik qidiriladi.
