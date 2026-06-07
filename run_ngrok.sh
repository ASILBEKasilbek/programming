#!/bin/bash
# HotelOS — Ngrok bilan ishga tushirish (Dashboard port 8080 da)
# Ishlatish: ./run_ngrok.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Avval oddiy run.sh bilan ishga tushiramiz, keyin ngrok qo'shamiz
echo "🏨 HotelOS + Ngrok ishga tushmoqda..."
echo ""

# Servislarni ishga tushirish
./run.sh --ngrok
