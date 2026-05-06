from sqlalchemy import Column, String, Integer, BigInteger, Text, TIMESTAMP, ForeignKey, Enum, JSON, UUID, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
import uuid
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum('admin', 'user', name='user_role'), nullable=False, default='user')
    created_at = Column(TIMESTAMP, default=datetime.utcnow)


class Document(Base):
    __tablename__ = 'documents'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    file_type = Column(String(50), index=True)
    file_size = Column(BigInteger)
    file_hash = Column(String(64), unique=True, index=True)
    content = Column(Text)
    category = Column(String(50), index=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    modified_at = Column(TIMESTAMP, default=datetime.utcnow)
    scanned_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    status = Column(Enum('pending', 'processing', 'indexed', 'failed', name='document_status'), index=True)

    __table_args__ = (
        Index('ix_document_filename_status', 'filename', 'status'),
        Index('ix_document_created_at_desc', 'created_at'),
    )


class Metadata(Base):
    __tablename__ = 'metadata'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), index=True)
    author = Column(String(255), index=True)
    creation_date = Column(TIMESTAMP)
    language = Column(String(10), index=True)
    page_count = Column(Integer)
    custom_tags = Column(JSONB)

    __table_args__ = (
        Index('ix_metadata_document_id', 'document_id'),
    )


class SearchIndex(Base):
    __tablename__ = 'search_index'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), index=True)
    full_text_vector = Column(TSVECTOR)
    embedding = Column(JSONB)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('ix_search_index_document_id', 'document_id'),
    )


class ScanLog(Base):
    __tablename__ = 'scan_logs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(String(255), index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), index=True)
    action = Column(Enum('added', 'updated', 'deleted', 'failed', name='scan_action'), index=True)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, index=True)
    error_message = Column(Text)

    __table_args__ = (
        Index('ix_scan_logs_document_id_timestamp', 'document_id', 'timestamp'),
    )
