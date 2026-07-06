#!/bin/bash
# ============================================================
# Migration script: Railway → Fly.io
# Jalankan dari folder qc-backend3/
# ============================================================
set -e

APP_NAME="qc-backend"
REGION="sin"

echo "▶ Step 1: Create Fly app"
fly apps create $APP_NAME --org personal 2>/dev/null || echo "App sudah ada, lanjut..."

echo "▶ Step 2: Create Fly Postgres"
fly postgres create \
  --name qc-backend-db \
  --org personal \
  --region $REGION \
  --vm-size shared-cpu-1x \
  --volume-size 1 \
  --initial-cluster-size 1

echo "▶ Step 3: Attach Postgres ke app (set DATABASE_URL otomatis)"
fly postgres attach qc-backend-db --app $APP_NAME

echo ""
echo "✅ Postgres selesai. Sekarang set env vars lainnya:"
echo "   Jalankan: bash fly-set-secrets.sh"
