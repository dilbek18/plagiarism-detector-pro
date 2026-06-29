ACADEMIC INTEGRITY SEARCH SERVER — Render free uchun yengil variant
Muallif: Dilshod Xo'jayev loyihasi uchun moslashtirilgan.

NIMA QILADI:
- API kalitlar frontendda ko'rinmaydi.
- Google Programmable Search, Brave Search, Serper va DuckDuckGo/SearchAPI ni server orqali ulaydi.
- API kalit bo'lmasa ham DuckDuckGo Lite fallback orqali oddiy qidiruv qiladi.
- PDF, DOCX, TXT, HTML, PPTX fayldan matn ajratib, internetdan o'xshash manbalarni topadi.
- 512 MB free Render uchun og'ir AI modellar, torch, transformers, OCR olib tashlangan.

FAYLLARNI QO'YISH:
1) GitHub repongizga quyidagi fayllarni yuklang:
   - main.py
   - requirements.txt
   - render.yaml
   - Procfile
   - static/index.html
2) Render dashboard > Settings:
   Build Command:
   pip install --no-cache-dir -r requirements.txt

   Start Command:
   uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1

3) Render > Environment:
   PYTHON_VERSION=3.11.9
   WEB_CONCURRENCY=1
   PYTHONUNBUFFERED=1
   PIP_NO_CACHE_DIR=1

4) Google ulash uchun Environmentga qo'shing:
   GOOGLE_API_KEY=...
   GOOGLE_CSE_ID=...

5) Qo'shimcha qidiruv tizimlari:
   BRAVE_API_KEY=...
   SERPER_API_KEY=...
   SEARCHAPI_API_KEY=...

6) Render > Manual Deploy > Clear build cache & deploy.

TEKSHIRISH:
Brauzerda oching:
https://SIZNING-SERVER.onrender.com/health

Agar google true bo'lsa, Google ulangan:
"google": true

API ENDPOINTLAR:
POST /api/search
Body:
{"q":"artificial intelligence in education", "limit":8, "academic":true}

POST /api/check
Body:
{"text":"Matn...", "max_fragments":8, "limit_per_fragment":5, "academic":true}

POST /api/check-file
Form-data:
file: PDF/DOCX/TXT/HTML/PPTX
max_fragments: 8
limit_per_fragment: 5
academic: true

MUHIM:
- Google Custom Search JSON API uchun Google Programmable Search Engine yaratish va API key olish kerak.
- GOOGLE_CSE_ID bu Google'dagi Search engine ID / cx qiymati.
- Google qidiruvi butun internetdan ishlashi uchun Programmable Search Engine sozlamasida “Search the entire web” yoqiladi.
- API kalitlarni index.html yoki GitHub kod ichiga yozmang. Faqat Render Environmentga yozing.
