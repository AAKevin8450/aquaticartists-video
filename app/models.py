"""
Data models for the application.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
import json


@dataclass
class File:
    """File model representing uploaded files."""
    id: Optional[int] = None
    filename: str = ''
    s3_key: str = ''
    file_type: str = ''  # 'video' or 'image'
    size_bytes: int = 0
    content_type: str = ''
    uploaded_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'File':
        """Create from dictionary."""
        if isinstance(data.get('metadata'), str):
            data['metadata'] = json.loads(data['metadata'])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AnalysisJob:
    """Analysis job model for tracking video/image analysis."""
    id: Optional[int] = None
    job_id: str = ''
    file_id: int = 0
    analysis_type: str = ''
    status: str = 'SUBMITTED'  # SUBMITTED, IN_PROGRESS, COMPLETED, FAILED
    parameters: Dict[str, Any] = field(default_factory=dict)
    results: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        # Convert None to null in JSON
        return {k: v for k, v in data.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisJob':
        """Create from dictionary."""
        # Handle JSON string conversion
        if isinstance(data.get('parameters'), str):
            data['parameters'] = json.loads(data['parameters'])
        if isinstance(data.get('results'), str):
            data['results'] = json.loads(data['results'])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FaceCollection:
    """Face collection model for Rekognition face collections."""
    id: Optional[int] = None
    collection_id: str = ''
    collection_arn: str = ''
    created_at: Optional[str] = None
    face_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FaceCollection':
        """Create from dictionary."""
        if isinstance(data.get('metadata'), str):
            data['metadata'] = json.loads(data['metadata'])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Transcript:
    """Transcript model for local video transcription."""
    id: Optional[int] = None
    file_path: str = ''
    file_size_bytes: int = 0
    file_modified_time: float = 0.0
    duration_seconds: Optional[float] = None
    language: Optional[str] = None
    model_used: str = ''
    transcript_text: Optional[str] = None
    transcript_segments: Optional[List[Dict[str, Any]]] = None
    word_timestamps: Optional[List[Dict[str, Any]]] = None
    confidence_score: Optional[float] = None
    processing_time_seconds: Optional[float] = None
    status: str = 'PENDING'  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transcript':
        """Create from dictionary."""
        # Handle JSON string conversion
        for field in ['transcript_segments', 'word_timestamps', 'metadata']:
            if isinstance(data.get(field), str):
                data[field] = json.loads(data[field])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Analysis type constants
class AnalysisType:
    """Analysis type constants."""
    # Video analysis types
    VIDEO_LABELS = 'video_labels'
    VIDEO_FACES = 'video_faces'
    VIDEO_FACE_SEARCH = 'video_face_search'
    VIDEO_PERSONS = 'video_persons'
    VIDEO_CELEBRITIES = 'video_celebrities'
    VIDEO_MODERATION = 'video_moderation'
    VIDEO_TEXT = 'video_text'
    VIDEO_SEGMENTS = 'video_segments'

    # Image analysis types
    IMAGE_LABELS = 'image_labels'
    IMAGE_FACES = 'image_faces'
    IMAGE_FACE_COMPARE = 'image_face_compare'
    IMAGE_FACE_SEARCH = 'image_face_search'
    IMAGE_CELEBRITIES = 'image_celebrities'
    IMAGE_MODERATION = 'image_moderation'
    IMAGE_TEXT = 'image_text'
    IMAGE_PPE = 'image_ppe'
    IMAGE_CUSTOM_LABELS = 'image_custom_labels'

    # Job status constants
    STATUS_SUBMITTED = 'SUBMITTED'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'


# Transcript status constants
class TranscriptStatus:
    """Transcript status constants."""
    PENDING = 'PENDING'
    IN_PROGRESS = 'IN_PROGRESS'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


# Rekognition API method mappings
REKOGNITION_VIDEO_METHODS = {
    AnalysisType.VIDEO_LABELS: ('start_label_detection', 'get_label_detection'),
    AnalysisType.VIDEO_FACES: ('start_face_detection', 'get_face_detection'),
    AnalysisType.VIDEO_FACE_SEARCH: ('start_face_search', 'get_face_search'),
    AnalysisType.VIDEO_PERSONS: ('start_person_tracking', 'get_person_tracking'),
    AnalysisType.VIDEO_CELEBRITIES: ('start_celebrity_recognition', 'get_celebrity_recognition'),
    AnalysisType.VIDEO_MODERATION: ('start_content_moderation', 'get_content_moderation'),
    AnalysisType.VIDEO_TEXT: ('start_text_detection', 'get_text_detection'),
    AnalysisType.VIDEO_SEGMENTS: ('start_segment_detection', 'get_segment_detection'),
}
