from celery import shared_task

from .pairing import cleanup_pairing_codes as cleanup_pairing_codes_service


@shared_task
def cleanup_pairing_codes():
    return cleanup_pairing_codes_service()
