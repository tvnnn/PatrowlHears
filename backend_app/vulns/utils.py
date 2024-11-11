from django.forms.models import model_to_dict
from common.utils import cvesearch
from .models import Vuln
import logging
logger = logging.getLogger(__name__)


def _refresh_metadata_cve(cve_id):
    res = cvesearch.get_cve_references(cve_id)
    if res is None:
        return None

    data = {
        'cve_id': cve_id,
        'summary': res['raw']['summary'],
        'published': res['raw']['Published'],
        'modified': res['raw']['last-modified'],
        'assigner': res['raw'].get('assigner', None),
        'cvss': res['raw'].get('cvss', None),
        'cvss_time': res['raw'].get('cvss-time', None),
        'cvss_vector': res['raw'].get('cvss-vector', None),
        'cwe': res['raw'].get('cwe', None),
        'access': res['raw'].get('access', None),
        'impact': res['raw'].get('impact', None),
        'vulnerable_products': res['raw'].get('vulnerable_product', None),
        'is_exploitable': res['is_exploitable'],
        'exploit_ref': res['exploit_ref'],
        'exploit_info': res['exploit_info'],
        'is_confirmed': res['is_confirmed'],
        'confirm_ref': res['confirm_ref'],
        'raw': res['raw']
    }
    m = Vuln.objects.filter(cve_id=cve_id)
    if m.count() > 0:
        m.changeReason = 'cvesearch_update'
        m.update(**data)
        logger.debug("CVE '{}' updated.".format(cve_id))
        return(model_to_dict(m.first()))
    else:
        new_metadata_records = Vuln(**data)
        new_metadata_records.save()
        logger.debug("CVE '{}' created.".format(cve_id))
        return(model_to_dict(new_metadata_records))


def _prepare_cve(data):
    status_ok = True
    data = {}

    return data, status_ok


def _is_vuln_monitored(vuln, org):
    try:
        # Get monitored vulns
        if vuln in org.org_monitoring_list.vulns.all():
            return True

        monitored_products = org.org_monitoring_list.products.all()
        monitored_product_vulns = Vuln.objects.filter(products__in=monitored_products)
        if vuln in monitored_product_vulns:
            return True

    except Exception:
        pass

    return False
