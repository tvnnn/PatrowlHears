from celery import shared_task
from django.apps import apps
from cves.models import Vendor, Product, CPE
from .utils import _run_datasync, _run_datasync_model
from common.utils.constants import DATASYNC_MODELS
from common.feeds.metadata import import_exploit
from common.feeds.vulns import import_cpe, import_cve, sync_exploits_fromvia, import_feedvuln
import logging
logger = logging.getLogger(__name__)


@shared_task(bind=True, acks_late=True)
def run_datasync_task(self, limit, since, to):
    _run_datasync(
        limit=limit,
        since=since,
        to=to
    )
    return True


@shared_task(bind=True, acks_late=True)
def run_datasync_model_task(self, model, limit, since, to, store):
    _run_datasync_model(
        model_class=apps.get_model(DATASYNC_MODELS[model]),
        model_name=model,
        limit=limit,
        since=since,
        to=to,
        store=store
    )
    return True


@shared_task(bind=True, acks_late=True)
def run_datasync_models_task(self, limit, since, to, store):
    for m in DATASYNC_MODELS.keys():
        _run_datasync_model(
            model_class=apps.get_model(DATASYNC_MODELS[m]),
            model_name=m,
            limit=limit,
            since=since,
            to=to,
            store=store
        )
    return True


@shared_task(bind=True, acks_late=False, ignore_result=False)
def import_exploit_task(self, data):
    e = import_exploit(data=data)
    if 'status' in e.keys() and e['status'] == 'error':
        logger.error(e['reason'])
    return True


@shared_task(bind=True, acks_late=False, ignore_result=False)
def import_cpe_task(self, vector, title, product, vendor):
    return import_cpe(vector, title, product, vendor)


# @shared_task(bind=True, acks_late=False, ignore_result=False)
# def import_cpe_task(self, data):
    return import_cpe(data)

@shared_task(bind=True, acks_late=False, ignore_result=False)
def import_cpe_batch_task(cpe_data_batch):
    cpe_objects = []
    for cpe_vector, details, product_id, vendor_id in cpe_data_batch:
        try:
            product = Product.objects.get(id=product_id)
            vendor = Vendor.objects.get(id=vendor_id)
            if not CPE.objects.filter(vector=cpe_vector).exists():
                cpe_objects.append(CPE(
                    vector=cpe_vector,
                    data=details,
                    product=product,
                    vendor=vendor
                ))
        except (Product.DoesNotExist, Vendor.DoesNotExist):
            continue

    if cpe_objects:
        CPE.objects.bulk_create(cpe_objects)

    return True

@shared_task(bind=True, acks_late=False, ignore_result=False)
def import_cve_task(self, data):
    return import_cve(data)


@shared_task(bind=True, acks_late=False, ignore_result=False)
def import_via_task(self, cve_id, data):
    return sync_exploits_fromvia(cve_id, data)


@shared_task(bind=True, acks_late=False, ignore_result=False)
def import_feedvuln_task(self, data, filename, filename_hash):
    return import_feedvuln(data, filename, filename_hash)
