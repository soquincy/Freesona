from pypdf import PdfReader
from utils.chroma import get_collection

def ingest_pdf_to_kb(file_path: str):
    collection = get_collection()
    
    # Check if collection is valid before accessing .add
    if collection is None:
        print("Failed to initialize ChromaDB collection.")
        return
        
    reader = PdfReader(file_path)
    
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            collection.add(
                documents=[text],
                metadatas=[{"source": file_path, "page": i}],
                ids=[f"{file_path}_page_{i}"]
            )
            print(f"Added page {i} from {file_path}")