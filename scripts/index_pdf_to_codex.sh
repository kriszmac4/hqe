#!/usr/bin/env bash
# ============================================================================
# index_pdf_to_codex.sh — PDF letöltés → szöveg kinyerés → Codex indexelés
# ============================================================================
# Használat:
#   ./index_pdf_to_codex.sh <gdrive_url_or_id> [<category>]
#
# Példa:
#   ./index_pdf_to_codex.sh "1OUvx7uKH817Md6PvitBcLN_VuCkpTNpi" "trading-bot"
#   ./index_pdf_to_codex.sh "https://drive.google.com/uc?id=1OUvx7uKH817Md6PvitBcLN_VuCkpTNpi"
#
# A script:
#   1. Letölti a PDF-et gdown-nal egy temp mappába
#   2. Kinyeri a szöveget fitz (pymupdf) segítségével
#   3. Betáplálja a Codex DB-be (hqe_codex.db)
#   4. Törli a temp PDF-et
# ============================================================================

set -euo pipefail

# ─── Konfiguráció ────────────────────────────────────────────────────────────
CODEX_DB="${HOME}/.hermes/profiles/dev/data/hqe_codex.db"
TEMP_DIR="/tmp/pdf-to-codex"
CATEGORY="${2:-books}"  # default category: books

# ─── Argumentum ellenőrzés ──────────────────────────────────────────────────
if [ $# -lt 1 ]; then
    echo "❌ Használat: $0 <gdrive_url_or_id> [<category>]"
    echo "Példa: $0 1OUvx7uKH817Md6PvitBcLN_VuCkpTNpi trading-bot"
    exit 1
fi

GDRIVE_ID="$1"

# URL-ből kinyerjük az ID-t ha teljes URL-t kaptunk
if echo "$GDRIVE_ID" | grep -q "drive.google.com"; then
    GDRIVE_ID=$(echo "$GDRIVE_ID" | grep -oP '(?<=id=|/d/)[a-zA-Z0-9_-]+' | head -1)
fi

echo "🔍 Google Drive ID: $GDRIVE_ID"

# ─── Letöltés ────────────────────────────────────────────────────────────────
mkdir -p "$TEMP_DIR"
echo "⬇️  Letöltés folyamatban..."

# Letöltjük és elkapjuk a fájlnevet
OUTPUT=$(gdown "https://drive.google.com/uc?id=${GDRIVE_ID}" -O "$TEMP_DIR" 2>&1)
echo "$OUTPUT"

# Kitaláljuk a fájlnevet
PDF_FILE=$(ls "$TEMP_DIR"/*.pdf 2>/dev/null | head -1)
if [ -z "$PDF_FILE" ]; then
    # Ha nem .pdf kiterjesztéssel jött, próbáljuk bármit
    PDF_FILE=$(ls -t "$TEMP_DIR" | head -1)
    PDF_FILE="$TEMP_DIR/$PDF_FILE"
fi

if [ ! -f "$PDF_FILE" ]; then
    echo "❌ Nem sikerült letölteni a PDF-et!"
    exit 1
fi

PDF_SIZE=$(stat -c%s "$PDF_FILE" 2>/dev/null || stat -f%z "$PDF_FILE" 2>/dev/null)
PDF_NAME=$(basename "$PDF_FILE")
echo "✅ Letöltve: $PDF_NAME ($(( PDF_SIZE / 1024 )) KB)"

# ─── Szöveg kinyerés ────────────────────────────────────────────────────────
echo "📄 Szöveg kinyerés fitz (pymupdf) segítségével..."

python3 -c "
import fitz
import sys
import os

pdf_path = '$PDF_FILE'
doc = fitz.open(pdf_path)
pages = doc.page_count
print(f'  Oldalszám: {pages}')
text_parts = []
for i, page in enumerate(doc):
    text = page.get_text()
    if text.strip():
        text_parts.append(f'--- Page {i+1} ---\n{text}')
    if (i+1) % 50 == 0:
        print(f'  Feldolgozva: {i+1}/{pages} oldal')

full_text = '\n\n'.join(text_parts)
doc.close()

# Mentjük a kinyert szöveget egy temp fájlba
text_file = '$TEMP_DIR/' + os.path.basename(pdf_path) + '.txt'
with open(text_file, 'w', encoding='utf-8') as f:
    f.write(full_text)

print(f'  Kinyert szöveg: {len(full_text)} karakter')
print(f'  Mentve: {text_file}')
" 2>&1

# ─── Codex indexelés ─────────────────────────────────────────────────────────
echo "📚 Codex indexelés..."

python3 -c "
import hashlib
import os
import sqlite3
import time

# Olvassuk a kinyert szöveget
text_file = '$TEMP_DIR/${PDF_NAME}.txt'
with open(text_file, 'r', encoding='utf-8') as f:
    full_text = f.read()

file_name = '$PDF_NAME'
category = '$CATEGORY'

# Virtual path a Codex-ben
file_path = f'gdrive:${GDRIVE_ID}'
file_hash = hashlib.sha256(full_text.encode()).hexdigest()
file_size = len(full_text.encode('utf-8'))

# Codex DB
db_path = '$CODEX_DB'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if already indexed
cursor.execute('SELECT 1 FROM file_registry WHERE file_path = ?', (file_path,))
if cursor.fetchone():
    print(f'  ⚠️  Már indexelve: {file_name}')
    conn.close()
    exit(0)

# Insert into FTS5
cursor.execute(
    'INSERT INTO codex_fts (file_path, file_name, content, category) VALUES (?, ?, ?, ?)',
    (file_path, file_name, full_text, category)
)

# Insert into registry
cursor.execute(
    'INSERT INTO file_registry (file_path, file_hash, last_indexed, file_size) VALUES (?, ?, ?, ?)',
    (file_path, file_hash, time.time(), file_size)
)

conn.commit()
conn.close()

print(f'  ✅ Sikeresen indexelve: {file_name}')
print(f'  📂 Kategória: {category}')
print(f'  🔗 Path: {file_path}')
print(f'  📏 Karakter: {len(full_text)}')
" 2>&1

# ─── Cleanup ─────────────────────────────────────────────────────────────────
echo "🧹 Takarítás..."
rm -f "$PDF_FILE" "$TEMP_DIR/${PDF_NAME}.txt"
echo "✅ PDF törölve"
echo ""
echo "🎉 Kész! A '$PDF_NAME' bekerült a Codex-be ($CATEGORY kategóriával)."
