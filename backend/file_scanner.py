import os
import hashlib
from pathlib import Path
from typing import List, Dict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config import settings

class FileInfo:
    def __init__(self, path: str, filename: str = None, file_type: str = None, file_size: int = None, file_hash: str = None):
        self.path = path
        self.filename = filename or os.path.basename(path)
        self.file_type = file_type or self._detect_file_type(path)
        self.file_size = file_size if file_size is not None else (os.path.getsize(path) if os.path.exists(path) else 0)
        self.file_hash = file_hash or (self._calculate_hash(path) if os.path.exists(path) else None)
        self.modified_at = os.path.getmtime(path) if os.path.exists(path) else None

    def _detect_file_type(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        mime_types = {
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.jpg': 'image/jpeg',
            '.png': 'image/png',
            '.tiff': 'image/tiff',
            '.zip': 'application/zip',
            '.rar': 'application/x-rar-compressed'
        }
        return mime_types.get(ext, 'application/octet-stream')

    def _calculate_hash(self, path: str) -> str:
        hash_md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

def scan_directory(directory: str) -> List[FileInfo]:
    """Recursively scan directory for files"""
    files = []
    for root, dirs, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(root, filename)
            if os.path.isfile(file_path):
                file_info = FileInfo(file_path)
                if file_info.file_size <= settings.max_file_size:
                    files.append(file_info)
    return files

def detect_file_type(path: str) -> str:
    """Detect file type"""
    file_info = FileInfo(path)
    return file_info.file_type

def calculate_file_hash(path: str) -> str:
    """Calculate file hash"""
    file_info = FileInfo(path)
    return file_info.file_hash

class FileWatcher(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_created(self, event):
        if not event.is_directory:
            self.callback(event.src_path, 'created')

    def on_modified(self, event):
        if not event.is_directory:
            self.callback(event.src_path, 'modified')

    def on_deleted(self, event):
        if not event.is_directory:
            self.callback(event.src_path, 'deleted')

def watch_directory(directory: str, callback):
    """Watch directory for changes"""
    event_handler = FileWatcher(callback)
    observer = Observer()
    observer.schedule(event_handler, directory, recursive=True)
    observer.start()
    return observer