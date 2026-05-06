from elasticsearch import Elasticsearch
from typing import List, Dict, Any
from config import settings
import json

class SearchEngine:
    def __init__(self):
        self.es = Elasticsearch(settings.elasticsearch_url)

    def index_document(self, doc_id: str, content: str, metadata: Dict[str, Any]):
        """Index a document in Elasticsearch"""
        doc = {
            'content': content,
            'filename': metadata.get('filename', ''),
            'file_path': metadata.get('file_path', ''),
            'file_type': metadata.get('file_type', ''),
            'author': metadata.get('author', ''),
            'creation_date': metadata.get('creation_date', ''),
            'language': metadata.get('language', 'en'),
            'page_count': metadata.get('page_count', 1),
            'category': metadata.get('category', '')
        }

        self.es.index(index='documents', id=doc_id, document=doc)

    def search(self, query: str, filters: Dict[str, Any] = None, limit: int = 20) -> Dict[str, Any]:
        """Perform full-text search"""
        if filters is None:
            filters = {}

        # Build query
        es_query = {
            'query': {
                'bool': {
                    'must': [
                        {
                            'multi_match': {
                                'query': query,
                                'fields': ['content', 'filename']
                            }
                        }
                    ],
                    'filter': []
                }
            },
            'size': limit,
            'highlight': {
                'fields': {
                    'content': {}
                }
            }
        }

        # Add filters
        if filters.get('file_type'):
            es_query['query']['bool']['filter'].append({
                'term': {'file_type': filters['file_type']}
            })

        if filters.get('language'):
            es_query['query']['bool']['filter'].append({
                'term': {'language': filters['language']}
            })

        response = self.es.search(index='documents', body=es_query)

        results = []
        for hit in response['hits']['hits']:
            result = {
                'id': hit['_id'],
                'score': hit['_score'],
                'filename': hit['_source']['filename'],
                'file_path': hit['_source']['file_path'],
                'file_type': hit['_source']['file_type'],
                'snippet': hit.get('highlight', {}).get('content', [''])[0][:200] + '...',
                'author': hit['_source'].get('author'),
                'creation_date': hit['_source'].get('creation_date'),
                'page_count': hit['_source'].get('page_count')
            }
            results.append(result)

        return {
            'total_results': response['hits']['total']['value'],
            'results': results
        }

    def delete_document(self, doc_id: str):
        """Delete a document from the index"""
        try:
            self.es.delete(index='documents', id=doc_id)
        except:
            pass  # Document might not exist

    def create_index(self):
        """Create the documents index"""
        try:
            if not self.es.indices.exists(index='documents'):
                self.es.indices.create(index='documents')
        except Exception as e:
            print(f"Error creating index: {e}")