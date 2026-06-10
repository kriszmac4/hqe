#!/usr/bin/env python3
"""
PDF → Codex indexelő pipeline

Használat:
    python3 index_pdf_to_codex.py <gdrive_file_id> [<category>]

Példa:
    python3 index_pdf_to_codex.py 1OUvx7uKH817Md6PvitBcLN_VuCkpTNpi books

Folyamat:
    1. Letölti a PDF-et gdown segítségével (stream, nem menti)
    2. Kinyeri a szöveget fitz (pymupdf) segítségével
    3. Betáplálja a Codex DB-be (hqe_codex.db)
    4. Törli a temp PDF-et
"""

import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

CODEX_DB = "/home/artofphotogrphyy/.hermes/profiles/dev/data/hqe_codex.db"
TEMP_DIR = tempfile.mkdtemp(prefix="pdf2codex-")


def download_pdf(gdrive_id: str) -> tuple[str, str]:
    """Download PDF using gdown, return (file_path, file_name)."""
    result = subprocess.run(
        ["gdown", f"https://drive.google.com/uc?id={gdrive_id}", "-O", TEMP_DIR + "/"],
        capture_output=True, text=True, timeout=120
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"❌ gdown error: {result.stderr}")
        sys.exit(1)

    # Find the downloaded file
    files = [f for f in os.listdir(TEMP_DIR) if os.path.isfile(os.path.join(TEMP_DIR, f))]
    if not files:
        print("❌ No file downloaded!")
        sys.exit(1)

    # Most recent file (in case multiple)
    files.sort(key=lambda f: os.path.getmtime(os.path.join(TEMP_DIR, f)), reverse=True)
    file_name = files[0]
    file_path = os.path.join(TEMP_DIR, file_name)
    size_kb = os.path.getsize(file_path) // 1024
    print(f"✅ Letöltve: {file_name} ({size_kb} KB)")
    return file_path, file_name


def extract_text(pdf_path: str) -> tuple[str, int]:
    """Extract text from PDF using fitz (pymupdf)."""
    import fitz
    doc = fitz.open(pdf_path)
    pages = doc.page_count
    print(f"📄 Oldalszám: {pages}")

    text_parts = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            text_parts.append(f"--- Page {i + 1} ---\n{text}")
        if (i + 1) % 50 == 0:
            print(f"  Feldolgozva: {i + 1}/{pages} oldal")

    doc.close()
    full_text = "\n\n".join(text_parts)
    print(f"  Kinyert szöveg: {len(full_text)} karakter")
    return full_text, pages


def index_to_codex(
    gdrive_id: str,
    file_name: str,
    full_text: str,
    category: str = "books",
):
    """Index extracted text into HQE Codex DB."""
    file_path = f"gdrive:{gdrive_id}"
    file_hash = hashlib.sha256(full_text.encode()).hexdigest()
    file_size = len(full_text.encode("utf-8"))

    conn = sqlite3.connect(CODEX_DB)
    cursor = conn.cursor()

    # Check if already indexed
    cursor.execute("SELECT 1 FROM file_registry WHERE file_path = ?", (file_path,))
    if cursor.fetchone():
        print(f"  ⚠️  Már indexelve: {file_name}")
        conn.close()
        return False

    # Insert into FTS5
    cursor.execute(
        "INSERT INTO codex_fts (file_path, file_name, content, category) VALUES (?, ?, ?, ?)",
        (file_path, file_name, full_text, category),
    )

    # Insert into registry
    cursor.execute(
        "INSERT INTO file_registry (file_path, file_hash, last_indexed, file_size) VALUES (?, ?, ?, ?)",
        (file_path, file_hash, time.time(), file_size),
    )

    conn.commit()
    conn.close()

    print(f"  ✅ Sikeresen indexelve: {file_name}")
    print(f"  📂 Kategória: {category}")
    print(f"  🔗 Path: {file_path}")
    print(f"  📏 Karakter: {len(full_text)}")
    return True


def cleanup():
    """Remove temp directory with all files."""
    import shutil
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
        print("🧹 Temp fájlok törölve")


def verify_index(gdrive_id: str) -> bool:
    """Verify the document was indexed by searching for it."""
    conn = sqlite3.connect(CODEX_DB)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_name, category FROM codex_fts WHERE file_path = ?",
        (f"gdrive:{gdrive_id}",),
    )
    result = cursor.fetchone()
    conn.close()

    if result:
        print(f"  ✅ Verifikálva: {result[0]} (kategória: {result[1]})")
        return True
    else:
        print(f"  ❌ NEM található a Codex-ben: gdrive:{gdrive_id}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Használat: python3 index_pdf_to_codex.py <gdrive_file_id> [<category>]")
        print("Példa: python3 index_pdf_to_codex.py 1OUvx7uKH817Md6PvitBcLN_VuCkpTNpi books")
        sys.exit(1)

    gdrive_id = sys.argv[1]
    category = sys.argv[2] if len(sys.argv) > 2 else "books"

    print(f"🔍 Google Drive ID: {gdrive_id}")
    print(f"📂 Kategória: {category}")
    print()

    try:
        # Step 1: Download
        pdf_path, file_name = download_pdf(gdrive_id)

        # Step 2: Extract text
        full_text, page_count = extract_text(pdf_path)

        # Step 3: Index to Codex
        success = index_to_codex(gdrive_id, file_name, full_text, category)

        # Step 4: Verify
        if success:
            verify_index(gdrive_id)

    except Exception as e:
        print(f"❌ Hiba: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup()

    print("\n🎉 Kész!")


if __name__ == "__main__":
    main()
