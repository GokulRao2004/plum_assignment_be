"""Celery application initialization."""
from celery import Celery
from app.config import config_by_name
import os


def make_celery(config_name='development'):
    """Create and configure Celery application.
    
    Args:
        config_name: Configuration environment (development, testing, production)
    
    Returns:
        Configured Celery application instance
    """
    config = config_by_name[config_name]
    
    celery = Celery(
        'plum_backend',
        broker=config.CELERY_BROKER_URL,
        backend=config.CELERY_RESULT_BACKEND,
        include=['app.tasks.claim_processing']
    )
    
    # Update celery config from Flask config
    celery.conf.update(
        task_track_started=config.CELERY_TASK_TRACK_STARTED,
        task_time_limit=config.CELERY_TASK_TIME_LIMIT,
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
    )
    
    return celery


# Create celery instance
config_name = os.environ.get('FLASK_ENV', 'development')
celery = make_celery(config_name)
