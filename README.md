# CertiKeep MVP

AI-powered personal document vault with:
- Account registration/login
- Backend file storage
- PDF/DOCX/TXT/MD/JPG/PNG/WEBP upload
- Text extraction and embedding-based AI search
- "Ask CertiKeep" Q&A over uploaded documents
- Source references in answers
- Conflict/uncertainty instructions for the assistant
- Preview, download, and delete

## 1. Open in VS Code
Open the `certikeep` folder.

## 2. Backend setup (Windows PowerShell)
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```
Edit `backend/.env` and add your Gemini API key and a random JWT secret.

Run:
```powershell
uvicorn app.main:app --reload --port 8000
```
API docs: http://127.0.0.1:8000/docs

## 3. Frontend setup (second terminal)
```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```
Open http://localhost:5173

## 4. Test commands
Backend health:
```powershell
curl http://127.0.0.1:8000/health
```
Backend automated smoke test:
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q
```
Frontend production build check:
```powershell
cd frontend
npm run build
```

## Notes
- Local development storage is `backend/uploads/<user-id>/...`.
- SQLite database is `backend/certikeep.db`.
- Search embeddings are stored as JSON in SQLite for simplicity. For a larger deployment, replace this with Postgres + pgvector.
- Digital PDFs, DOCX, TXT and MD are extracted locally. Images use the configured Gemini model for text extraction.
- Scanned PDFs are intentionally rejected in this MVP; convert them to images or add OCR later.


## AI quota-safe uploads
Uploads are persisted even when Gemini indexing is unavailable (for example, API credits are exhausted). Such files show **Stored safely • AI indexing pending** in the dashboard. Once API access is available, click **Retry AI** on the document card to index it without uploading the file again.


## Gemini + safeguard behavior

CertiKeep stores the uploaded file before attempting Gemini indexing. If Gemini is unavailable or the free-tier quota is exhausted, the upload still succeeds and the UI shows AI indexing as pending. The user can retry indexing later. Search also falls back to a local keyword search when Gemini embeddings are unavailable.

For free-tier testing, use demo/non-sensitive documents. Do not upload real Aadhaar, passport, financial, or other sensitive identity documents to a free AI tier unless its data-use terms are acceptable for your use case.
