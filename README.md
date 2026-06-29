# Internet Detector Pro — Render Internet Search Fix

Bu paket Render uchun tuzatilgan versiya. Interfeysda API kalit yozuvlari ko‘rinmaydi.
Server `/api/search-sources` orqali avtomatik internet qidiruvi qiladi.

## Render start command
uvicorn main:app --host 0.0.0.0 --port $PORT

## Muhim
GitHub repository bosh papkasiga quyidagi fayllarni yuklang:
- main.py
- index.html
- requirements.txt
- render.yaml
- Procfile
- runtime.txt
- README.md

Keyin Render: Manual Deploy → Clear build cache & deploy.
