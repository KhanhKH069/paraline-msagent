import os
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PayloadSchemaType

def main():
    # Lấy cấu hình từ biến môi trường (như trong tài liệu)
    collection_name = os.environ.get("COLLECTION_NAME", "rag_documents")
    vector_size = int(os.environ.get("VECTOR_SIZE", "768"))
    
    # Kết nối tới Qdrant (mặc định môi trường dev port 6333)
    # Vì script này chạy trực tiếp trên server theo tài liệu nên dùng 127.0.0.1
    client = QdrantClient(host="127.0.0.1", port=6333)
    
    # Kiểm tra collection đã tồn tại chưa
    if client.collection_exists(collection_name=collection_name):
        print(f"Collection '{collection_name}' đã tồn tại — bỏ qua tạo mới.")
        return
        
    print(f"Bắt đầu tạo collection '{collection_name}' với vector_size = {vector_size}...")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    
    # Tạo payload indexes (như trong tài liệu yêu cầu)
    print("Tạo payload indexes cho 'source' (KEYWORD)...")
    client.create_payload_index(
        collection_name=collection_name, field_name="source", field_schema=PayloadSchemaType.KEYWORD
    )
    
    print("Tạo payload indexes cho 'doc_id' (KEYWORD)...")
    client.create_payload_index(
        collection_name=collection_name, field_name="doc_id", field_schema=PayloadSchemaType.KEYWORD
    )
    
    print("Tạo payload indexes cho 'chunk_index' (INTEGER)...")
    client.create_payload_index(
        collection_name=collection_name, field_name="chunk_index", field_schema=PayloadSchemaType.INTEGER
    )
    
    print("Hoàn tất khởi tạo collection trong Qdrant!")

if __name__ == "__main__":
    main()
