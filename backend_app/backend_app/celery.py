# -*- coding: utf-8 -*-

import os
from celery import Celery
from django.conf import settings
from kombu import Exchange, Queue

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend_app.settings')

# set the default Django settings module for the 'celery' program.
app = Celery('backend_app', broker=settings.BROKER_URL)
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

# Define queues with rate limits
app.conf.task_queues = (
    Queue('default', Exchange('default'), routing_key='default'),
    Queue('alerts', Exchange('default'), routing_key='default', max_priority=10),  # Optional priority setting
    Queue('data', Exchange('default'), routing_key='default'),
)

app.conf.task_annotations = {
    'alerts': {'rate_limit': '0.5/s'}  # 1 task mỗi 2 giây cho các task trong hàng đợi 'alerts'
}

app.conf.task_default_queue = 'default'
app.conf.task_default_exchange = 'default'
app.conf.task_default_exchange_type = 'direct'
app.conf.task_default_routing_key = 'default'
