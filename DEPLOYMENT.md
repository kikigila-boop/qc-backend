# Deployment Guide — OTT QC Management System Backend

## Option A: Local Development (Docker Compose)

```bash
# 1. Clone / copy project
cd qc-backend

# 2. Create .env from example
cp .env.example .env
# Edit .env — set SECRET_KEY (min 32 chars random string)

# 3. Start everything
docker compose up --build

# API will be live at: http://localhost:8000
# Docs (Swagger UI):   http://localhost:8000/docs
```

---

## Option B: Free Cloud Deploy (Railway + Supabase)

### Step 1 — Database: Supabase (free PostgreSQL)
1. Go to https://supabase.com → New Project
2. Copy the **Connection String** (URI format)  
   Example: `postgresql://postgres:[PASSWORD]@db.xxxx.supabase.co:5432/postgres`
3. Save it — you'll need it for DATABASE_URL

### Step 2 — Backend: Railway (free tier)
1. Go to https://railway.app → New Project → Deploy from GitHub
2. Connect your GitHub repo (upload `qc-backend` folder first)
3. In Railway: **Variables** tab, add all values from `.env.example`:
   ```
   DATABASE_URL=postgresql://...   (from Supabase)
   SECRET_KEY=your-32-char-secret
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=480
   ```
4. Railway auto-detects Dockerfile and builds it
5. Your API URL will be: `https://your-app.up.railway.app`

### Step 3 — Test the API
- Swagger UI: `https://your-app.up.railway.app/docs`
- Health check: `GET https://your-app.up.railway.app/`

---

## API Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/auth/register | Register new editor |
| POST | /api/v1/auth/login | Login, get JWT token |
| GET | /api/v1/users/ | List all active users |
| GET | /api/v1/users/me | Get current user |
| POST | /api/v1/qc/ | Create new QC entry |
| GET | /api/v1/qc/ | List QC with search & filter |
| GET | /api/v1/qc/{id} | Get detail + history |
| PUT | /api/v1/qc/{id} | Update QC fields |
| PATCH | /api/v1/qc/{id}/status | Advance workflow status |
| GET | /api/v1/qc/{id}/history | Get activity log |
| GET | /api/v1/dashboard/stats | Dashboard statistics |

---

## Google Sheets Sync (Optional)

1. Go to Google Cloud Console → Create Service Account
2. Give it "Editor" access to the target spreadsheet
3. Download JSON credentials
4. Set in `.env`:
   ```
   GOOGLE_SHEETS_CREDENTIALS_JSON={"type":"service_account",...}
   GOOGLE_SPREADSHEET_ID=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
   ```
5. Create a sheet tab named `QC_Data` with headers in row 1:
   `QCID | Title | Season | Episode | Duration | Cast | Storage | QC Result | Status | Editor | QC Date | Created | Updated | Notes`

The API will sync automatically in the background after every create/update.

---

## Security Notes for Production

- Change `allow_origins=["*"]` in `main.py` to your frontend domain
- Use a strong random SECRET_KEY (generate with `openssl rand -hex 32`)
- Enable Supabase Row Level Security (RLS) if using direct DB access
