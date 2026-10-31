from celery import shared_task

from .services import dispatch_outbox, dispatch_pending_notifications


@shared_task
def dispatch_notification(outbox_id):
    return dispatch_outbox(outbox_id)


@shared_task
def dispatch_pending_notifications_task(limit=100):
    return dispatch_pending_notifications(limit=limit)
