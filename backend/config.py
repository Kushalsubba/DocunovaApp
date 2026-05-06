import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5433/doc_scanner")
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    api_port: int = int(os.getenv("API_PORT", 8000))
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_log_level: str = os.getenv("API_LOG_LEVEL", "INFO")
    scan_directory: str = os.getenv("SCAN_DIRECTORY", "/mnt/data/documents")
    scan_interval: int = int(os.getenv("SCAN_INTERVAL", 3600))
    max_file_size: int = int(os.getenv("MAX_FILE_SIZE", 500 * 1024 * 1024))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
    milvus_db_path: str = os.getenv(
        "MILVUS_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "milvus_kush.db")
    )
    semantic_search_top_k: int = int(os.getenv("SEMANTIC_SEARCH_TOP_K", 10))
    jwt_secret: str = os.getenv("JWT_SECRET", "change-this-secret-in-production")
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    upload_dir: str = os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    )


settings = Settings()
