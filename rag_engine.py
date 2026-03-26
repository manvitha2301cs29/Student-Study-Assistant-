# rag_engine.py
# ─────────────────────────────────────────────────────────────────────────────
# Handles everything related to PDFs and FAISS vector storage
#
# WHAT THIS FILE DOES:
# 1. Extracts text from PDFs — handles 3 types:
#    a) Normal text PDF     → PyPDF2 (fast)
#    b) Mixed PDF           → pdfplumber (text + tables)
#    c) Scanned/image PDF   → pytesseract OCR
# 2. Cleans broken PDF text (word\n \nword pattern)
# 3. Splits text into chunks
# 4. Creates FAISS vector store per chat (saved to disk)
# 5. Loads FAISS from disk when old chat reopened
# 6. Searches FAISS for relevant chunks

# ─────────────────────────────────────────────────────────────────────────────

import os
import io
import re
import json
from typing import List, Optional

# PDF reading
from PyPDF2 import PdfReader
import pdfplumber
import fitz   # PyMuPDF — for image extraction

# OCR (optional — for scanned PDFs)
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
    tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
except ImportError:
    OCR_AVAILABLE = False

# LangChain + FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────
FAISS_BASE_DIR = "faiss_indexes"
CHUNK_SIZE     = 5000
CHUNK_OVERLAP  = 500

# ── LAZY EMBEDDINGS ───────────────────────────────────────────────────────────
# NOT created at module load time
# Created only when first needed (first FAISS operation)
# This prevents SSL timeout when other files import rag_engine
_embeddings_model = None

def get_embeddings_model():
    """
    Get or create the Gemini embeddings model
    Lazy initialization — only created when first called
    """
    global _embeddings_model
    if _embeddings_model is None:
        print("  ⚙️ Initializing embeddings model...")
        _embeddings_model = GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001",
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        print("  ✅ Embeddings model ready")
    return _embeddings_model


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: FAISS folder path per chat
# ─────────────────────────────────────────────────────────────────────────────
def get_faiss_path(chat_id: int) -> str:
    """Returns folder path for this chat's FAISS index"""
    path = os.path.join(FAISS_BASE_DIR, f"chat_{chat_id}")
    os.makedirs(path, exist_ok=True)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# DETECT PDF TYPE
# ─────────────────────────────────────────────────────────────────────────────
def detect_pdf_type(pdf_bytes: bytes) -> str:
    """
    Detect if PDF is:
    - text    → normal selectable text (PyPDF2 works great)
    - mixed   → text + images/tables (pdfplumber works better)
    - scanned → image only (needs OCR)
    """
    try:
        reader     = PdfReader(io.BytesIO(pdf_bytes))
        total_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                total_text += t
        avg = len(total_text.strip()) / max(len(reader.pages), 1)
        if avg < 100:
            return "scanned"
        elif avg < 500:
            return "mixed"
        else:
            return "text"
    except:
        return "mixed"


# ─────────────────────────────────────────────────────────────────────────────
# CLEAN PDF TEXT
# Fixes the 'word\n \nword\n \nword' pattern common in custom-font PDFs
# ─────────────────────────────────────────────────────────────────────────────
def clean_pdf_text(text: str) -> str:
    """
    Cleans broken PDF text where every word is on its own line

    Your PDF has pattern: 'MANVITHA\n \nREDDY\n \n2301CS29'
    Fix: replace '\n \n' (newline space newline) with a space
    """
    if not text:
        return ""

    # ── Main fix: '\n \n' between every word → replace with space ─────────────
    text = re.sub(r'\n \n', ' ', text)

    # ── Handle variations: '\n   \n' multiple spaces ──────────────────────────
    text = re.sub(r'\n\s+\n', ' ', text)

    # ── Split into lines and clean each ───────────────────────────────────────
    lines   = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            cleaned.append(stripped)

    text = '\n'.join(cleaned)

    # ── Remove 3+ consecutive newlines ────────────────────────────────────────
    text = re.sub(r'\n{3,}', '\n\n', text)

    # ── Clean multiple spaces ─────────────────────────────────────────────────
    text = re.sub(r'  +', ' ', text)

    # ── Fix comma spacing ─────────────────────────────────────────────────────
    text = re.sub(r',\s+', ', ', text)

    # ── Clean unicode ─────────────────────────────────────────────────────────
    text = text.encode('utf-8', errors='ignore').decode('utf-8')

    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION METHOD 1: PyPDF2 (fast, for normal text PDFs)
# ─────────────────────────────────────────────────────────────────────────────
def extract_text_pypdf2(pdf_bytes: bytes) -> str:
    """Extract text using PyPDF2 with cleaning"""
    text = ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        print(f"  📄 Pages: {len(reader.pages)}")
        for i, page in enumerate(reader.pages):
            try:
                raw = page.extract_text()
                if raw is None:
                    continue
                cleaned = clean_pdf_text(str(raw))
                if cleaned.strip():
                    text += f"\n[Page {i+1}]\n{cleaned}\n"
                    print(f"  ✅ Page {i+1}: {len(cleaned)} chars")
            except Exception as e:
                print(f"   Page {i+1} error: {e}")
    except Exception as e:
        print(f"   PyPDF2 error: {e}")
        return ""
    return text if text else ""


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION METHOD 2: pdfplumber (for mixed PDFs with tables)
# ─────────────────────────────────────────────────────────────────────────────
def extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    """Extract text + tables using pdfplumber"""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    # Extract text
                    raw = page.extract_text()
                    if raw:
                        cleaned = clean_pdf_text(raw)
                        if cleaned.strip():
                            text += f"\n[Page {i+1}]\n{cleaned}\n"

                    # Extract tables
                    tables = page.extract_tables()
                    for table in tables:
                        text += "\n[TABLE]\n"
                        for row in table:
                            row_clean = [str(c) if c else "" for c in row]
                            text += " | ".join(row_clean) + "\n"
                        text += "[END TABLE]\n"

                except Exception as e:
                    print(f"   pdfplumber page {i+1}: {e}")
    except Exception as e:
        print(f"   pdfplumber error: {e}")
        return ""
    return text if text else ""


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION METHOD 3: OCR (for scanned/image PDFs)
# ─────────────────────────────────────────────────────────────────────────────
def extract_text_ocr(pdf_bytes: bytes) -> str:
    """Extract text from scanned PDFs using Tesseract OCR"""
    if not OCR_AVAILABLE:
        print("   OCR not available — install pytesseract + Tesseract")
        return ""
    text = ""
    try:
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i in range(len(pdf_doc)):
            page = pdf_doc[i]
            mat  = fitz.Matrix(2.0, 2.0)   # 2x zoom = better OCR quality
            pix  = page.get_pixmap(matrix=mat)
            img  = Image.open(io.BytesIO(pix.tobytes("png")))
            raw  = pytesseract.image_to_string(img, lang="eng")
            if raw.strip():
                text += f"\n[Page {i+1} OCR]\n{raw.strip()}\n"
                print(f"   OCR page {i+1}: {len(raw)} chars")
        pdf_doc.close()
    except Exception as e:
        print(f"   OCR error: {e}")
        return ""
    return text if text else ""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXTRACTOR — tries all methods automatically
# ─────────────────────────────────────────────────────────────────────────────
def extract_text_from_pdfs(pdf_files: list) -> str:
    """
    Smart extraction — picks best method automatically
    ALWAYS returns a string, never None

    For each PDF:
    1. Read bytes
    2. Detect type (text/mixed/scanned)
    3. Try methods in order until one gives good results
    4. Fallback to next method if current fails
    """
    full_text = ""

    for pdf in pdf_files:
        pdf_name = getattr(pdf, 'name', 'PDF')
        print(f"\n Processing: {pdf_name}")

        # Read bytes
        try:
            if hasattr(pdf, 'seek'):
                pdf.seek(0)
            pdf_bytes = pdf.read() if hasattr(pdf, 'read') else bytes(pdf)
            print(f"   Size: {len(pdf_bytes)} bytes")
        except Exception as e:
            print(f"   ❌ Cannot read file: {e}")
            continue

        if not pdf_bytes:
            print("  ❌ Empty file!")
            continue

        # Detect type and set method order
        pdf_type = detect_pdf_type(pdf_bytes)
        print(f"   Type: {pdf_type}")

        if pdf_type == "text":
            methods = ["pypdf2", "pdfplumber"]
        elif pdf_type == "mixed":
            methods = ["pdfplumber", "pypdf2"]
        else:
            methods = ["ocr", "pdfplumber", "pypdf2"]

        extracted = ""

        # Try each method until one works
        for method in methods:
            print(f"   Trying: {method}")
            try:
                if method == "pypdf2":
                    result = extract_text_pypdf2(pdf_bytes)
                elif method == "pdfplumber":
                    result = extract_text_pdfplumber(pdf_bytes)
                elif method == "ocr" and OCR_AVAILABLE:
                    result = extract_text_ocr(pdf_bytes)
                else:
                    print(f"  ⏭️ Skipping {method}")
                    continue

                result = result if isinstance(result, str) else ""

                if len(result.strip()) > 50:
                    print(f"   '{method}' worked: {len(result)} chars")
                    extracted = result
                    break
                else:
                    print(f"   '{method}' too little: {len(result.strip())} chars")

            except Exception as e:
                print(f"   '{method}' failed: {e}")
                continue

        extracted = extracted if isinstance(extracted, str) else ""
        print(f"   Extracted: {len(extracted.strip())} chars")
        full_text += extracted

    # Final safety
    full_text = full_text if isinstance(full_text, str) else ""

    if not full_text.strip():
        raise ValueError(
            "Could not extract text from PDF.\n"
            "Make sure it contains selectable text (not a scanned image)."
        )

    print(f"\n Total extracted: {len(full_text)} chars")
    return full_text


# ─────────────────────────────────────────────────────────────────────────────
# SPLIT INTO CHUNKS
# ─────────────────────────────────────────────────────────────────────────────
def split_text_into_chunks(text: str) -> List[str]:
    """Split large text into overlapping chunks for FAISS"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""]
    )
    chunks = splitter.split_text(text)
    print(f" Split into {len(chunks)} chunks")
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# CREATE AND SAVE FAISS
# ─────────────────────────────────────────────────────────────────────────────
def create_and_save_faiss(chunks: List[str], chat_id: int) -> FAISS:
    """Convert chunks to embeddings and save FAISS index to disk"""
    print(f" Creating FAISS for chat {chat_id}...")

    # Lazy load embeddings — only initialized here, not at import
    vector_store = FAISS.from_texts(
        texts     = chunks,
        embedding = get_embeddings_model()
    )

    faiss_path = get_faiss_path(chat_id)
    vector_store.save_local(faiss_path)

    # Save raw chunks alongside FAISS for Agent 1 full scan
    chunks_path = os.path.join(faiss_path, "chunks.json")
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)

    print(f" FAISS saved → {faiss_path}")
    return vector_store


# ─────────────────────────────────────────────────────────────────────────────
# LOAD FAISS FROM DISK
# ─────────────────────────────────────────────────────────────────────────────
def load_faiss(chat_id: int) -> Optional[FAISS]:
    """Load existing FAISS index from disk for a chat"""
    faiss_path = get_faiss_path(chat_id)
    index_file = os.path.join(faiss_path, "index.faiss")

    if not os.path.exists(index_file):
        return None

    try:
        vs = FAISS.load_local(
            faiss_path,
            get_embeddings_model(),       # lazy load here too
            allow_dangerous_deserialization=True
        )
        print(f" FAISS loaded for chat {chat_id}")
        return vs
    except Exception as e:
        print(f" FAISS load error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH FAISS
# ─────────────────────────────────────────────────────────────────────────────
def search_faiss(query: str, chat_id: int, k: int = 4) -> List[str]:
    """
    Search FAISS for most relevant chunks for a query
    Used by:
    - Agent 1: find topics in PDF
    - Agent 3: get notes-based explanation
    - Agent 5: get PDF context for follow-up questions
    """
    vs = load_faiss(chat_id)
    if not vs:
        return []
    docs   = vs.similarity_search(query, k=k)
    chunks = [doc.page_content for doc in docs]
    print(f" Found {len(chunks)} chunks for: '{query[:50]}'")
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# GET ALL CHUNKS (for Agent 1 full topic scan)
# ─────────────────────────────────────────────────────────────────────────────
def get_all_chunks(chat_id: int) -> List[str]:
    """Return all stored chunks — Agent 1 scans ALL of them for topics"""
    chunks_path = os.path.join(get_faiss_path(chat_id), "chunks.json")
    if not os.path.exists(chunks_path):
        return []
    with open(chunks_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# ADD MORE PDFs (multi-PDF support)
# ─────────────────────────────────────────────────────────────────────────────
def add_pdfs_to_faiss(pdf_files: list, chat_id: int) -> FAISS:
    """Merge new PDFs into existing FAISS index for a chat"""
    new_text   = extract_text_from_pdfs(pdf_files)
    new_chunks = split_text_into_chunks(new_text)
    existing   = load_faiss(chat_id)

    if existing:
        existing.add_texts(new_chunks)
        faiss_path  = get_faiss_path(chat_id)
        existing.save_local(faiss_path)

        all_chunks  = get_all_chunks(chat_id) + new_chunks
        chunks_path = os.path.join(faiss_path, "chunks.json")
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(all_chunks, f, ensure_ascii=False)

        print(f" Added {len(new_chunks)} chunks to chat {chat_id}")
        return existing
    else:
        return create_and_save_faiss(new_chunks, chat_id)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE — called by graph.py when student uploads PDF
# ─────────────────────────────────────────────────────────────────────────────
def process_pdfs_for_chat(pdf_files: list, chat_id: int) -> dict:
    """Full pipeline: Extract → Split → Embed → Save FAISS"""
    print(f"\n Processing PDFs for chat {chat_id}...")

    raw_text = extract_text_from_pdfs(pdf_files)

    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("Text extraction failed or returned empty")

    word_count = len(raw_text.split())
    chunks     = split_text_into_chunks(raw_text)

    if not chunks:
        raise ValueError("No chunks produced")

    create_and_save_faiss(chunks, chat_id)

    print(f" Done: {word_count} words, {len(chunks)} chunks")
    return {
        "word_count"  : word_count,
        "chunk_count" : len(chunks),
        "chat_id"     : chat_id,
        "status"      : "success"
    }


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────
def faiss_exists(chat_id: int) -> bool:
    """Check if FAISS index exists for a chat"""
    return os.path.exists(
        os.path.join(get_faiss_path(chat_id), "index.faiss")
    )
