from django.conf import settings
from cves.models import CWE, CPE, CVE, Bulletin, Vendor, Product, ProductVersion
from vulns.models import Vuln, ExploitMetadata, ThreatMetadata
from .cvesearch_bulletins import sync_bulletin_redhat, sync_bulletin_msbulletin
from pymongo import MongoClient
from cpe import CPE as _CPE
import datetime
import json
import requests
import deepdiff
import logging
logger = logging.getLogger(__name__)

COMMON_EXPLOIT_FEEDS = [
    "exploit-db",
    "packetstormsecurity.com",
    "github.com",
    "raw.githubusercontent.com",
    "youtube.com",
    "snyk.io/research/"
]

VIA_BULLETINS = [
    'redhat', 'msbulletin', 'ubuntu', 'suse', 'debian',
    'fedora', 'freebsd', 'gentoo', 'mandrake', 'mandriva', 'slackware'
]


def without_keys(d, keys):
    return {x: d[x] for x in d if x not in keys}


def _json_serial(o):
    if isinstance(o, datetime.datetime):
        return o.__str__()


def _extract_exploit_dates(published, modified):
    e_pubdate = published
    e_update = modified
    if e_pubdate is not None:
        try:
            e_pubdate = datetime.datetime.strptime(e_pubdate, "%Y-%m-%d").date()
        except Exception:
            e_pubdate = None
    if e_update is not None:
        try:
            e_update = datetime.datetime.strptime(e_update, "%Y-%m-%d").date()
        except Exception:
            e_update = None
    else:
        e_update = e_pubdate
    return e_pubdate, e_update


def sync_cwes_fromdb(from_date=None):
    cli = MongoClient(
        settings.DATABASES['mongodb']['HOST'],
        settings.DATABASES['mongodb']['PORT'])
    db = cli['cvedb']
    cwes = db.cwe

    my_cwes = CWE.objects.values_list('cwe_id', flat=True)

    for cwe in cwes.find():
        if 'CWE-'+cwe['id'] not in my_cwes:
            new_cwe = CWE(
                cwe_id="CWE-"+cwe['id'],
                name=cwe['name'],
                description=cwe['Description']
            )
            new_cwe.save()
    return True


def sync_cpes_fromdb(from_date=None):
    cli = MongoClient(
        settings.DATABASES['mongodb']['HOST'],
        settings.DATABASES['mongodb']['PORT'])
    db = cli['cvedb']
    cpes = db.cpe
    my_cpes = list(CPE.objects.values_list('vector', flat=True))

    cursor_cpes = cpes.find(no_cursor_timeout=True)
    for cpe in cursor_cpes:
        if cpe['cpe_2_2'] not in my_cpes:
            # It's a new CPE
            try:
                c = _CPE(cpe['cpe_2_2'])
                vendor, is_new_vendor = Vendor.objects.get_or_create(name=c.get_vendor()[0])
                product, is_new_product = Product.objects.get_or_create(name=c.get_product()[0], vendor=vendor)
                productversion, is_new_productversion = ProductVersion.objects.get_or_create(version=c.get_version()[0], product=product, vector=cpe['cpe_2_2'])

                new_cpe = CPE(
                    vector=cpe['cpe_2_2'],
                    title=cpe['title'],
                    vendor=vendor,
                    product=product,
                    vulnerable_products=[]
                )
                new_cpe.save()
                for p in cpe['cpe_name']:
                    if 'cpe23Uri' in p.keys():
                        new_cpe.vulnerable_products.append(p['cpe23Uri'])

                new_cpe.save()

                # Add the currect CPE to inner list
                my_cpes.append(cpe['cpe_2_2'])
            except Exception as e:
                logger.error(e)
        else:
            # Update existing CPE and check for new vulnerable products
            old_cpe = CPE.objects.filter(vector=cpe['cpe_2_2'])[0]
            vp = []
            try:
                for p in cpe['cpe_name']:
                    if 'cpe23Uri' in p.keys():
                        vp.append(p['cpe23Uri'])
                if len(vp) > len(old_cpe.vulnerable_products):
                    old_cpe.vulnerable_products = vp
                    old_cpe.save()
            except Exception as e:
                logger.error(e)
    cursor_cpes.close()
    return True


def sync_bulletins_fromdb(from_date=None):
    cli = MongoClient(
        settings.DATABASES['mongodb']['HOST'],
        settings.DATABASES['mongodb']['PORT'])
    db = cli['cvedb']
    vias = db.via4

    for via in vias.find():
        # Check if the VIA record has supported bulletin information
        for k in via.keys():
            if k in VIA_BULLETINS:
                _sync_bulletin_fromdb(via, k)  # via['id']: CVE-yyyy-xxxxx
    return True


def _sync_bulletin_fromdb(cve, vendor):
    cve_id = cve['id']
    _new_bulletins = []
    if vendor == 'redhat':
        _new_bulletins = sync_bulletin_redhat(cve['redhat'])
    elif vendor == 'msbulletin':
        _new_bulletins = sync_bulletin_msbulletin(cve['msbulletin'])
    # Todo: other vendors

    for new_bulletin in _new_bulletins:
        # Create or new Bulletin object
        bulletin = Bulletin.objects.filter(publicid=new_bulletin['publicid']).first()
        if bulletin is None:
            # Create new bulletin
            bulletin = Bulletin(**new_bulletin)
        else:
            # Update existing one if any change
            for v in new_bulletin.keys():
                new_value = new_bulletin[v]
                old_value = getattr(bulletin, v)

                if isinstance(old_value, datetime.date):
                    old_value = getattr(bulletin, v).date()
                if isinstance(new_value, datetime.datetime):
                    new_value = new_bulletin[v].date()

                if new_value is not None and new_value != old_value:
                    # print("'{}' vs. '{}'".format(new_bulletin[v], getattr(bulletin, v)))
                    # print('update bulletin: "{}" --> "{}"="{}"'.format(bulletin, v, new_value))
                    setattr(bulletin, v, new_value)

        bulletin.save()

        # Add / Update CVE.bulletins references
        cve = CVE.objects.filter(cve_id=cve_id).first()
        if cve is not None and bulletin not in cve.bulletins.all():
            cve.bulletins.add(bulletin)

    return True


# Sync all CVE
def sync_cves_fromdb(from_date=None, from_year=1999, to_year=None):
    cli = MongoClient(
        settings.DATABASES['mongodb']['HOST'],
        settings.DATABASES['mongodb']['PORT'])
    db = cli['cvedb']
    cves = db.cves
    vias = db.via4

    via = None

    # Workaround for pymongo.errors.CursorNotFound fucking errors
    # search CVE by year and first id
    current_year = datetime.datetime.now().year
    if to_year is not None:
        current_year = int(to_year)
    for year in range(int(from_year), int(current_year)+1):
        for fi in range(0, 10):
            cursor_cve = cves.find({'id': {'$regex': '^CVE-{}-{}'.format(year, fi)}})
            # cursor_cve = cves.find({'id': {'$regex': '^CVE-{}-{}'.format(year, fi)}}, no_cursor_timeout=True)
            cve_list = [c for c in cursor_cve]
            try:
                # for cve in cursor_cve:
                for cve in cve_list:
                    logger.info('Syncing {}'.format(cve['id']))
                    via = vias.find_one({'id': cve['id']})
                    _sync_cve_fromdb(cve, via)
                    via = None
            except Exception as e:
                logger.error("Sommething gone wrong in sync_cves_fromdb(). CursorNotFound ?")
                logger.error(e)
            finally:
                cursor_cve.close()
            # cursor_cve.close()
    return True


# Sync a single CVE
def sync_cve_fromdb(cve_id, from_date=None):
    cli = MongoClient(
        settings.DATABASES['mongodb']['HOST'],
        settings.DATABASES['mongodb']['PORT'])
    db = cli['cvedb']
    cve = db.cves.find_one({'id': cve_id})
    if cve is not None:
        via = db.via4.find_one({'id': cve['id']})
        _sync_cve_fromdb(cve, via)
        return True
    return False


def _sync_cve_fromdb(cve, via):
    # start_time = time()
    _new_cve = {
        'cve_id': cve['id'],
        'summary': cve.get('summary', None),
        'published': cve.get('Published', None),
        'modified': cve.get('Modified', None),
        'assigner': cve.get('assigner', None),
        'cvss': cve.get('cvss', None),
        'cvss_time': cve.get('cvss-time', None),
        'cvss_vector': cve.get('cvss-vector', None),
        'access': cve.get('access', None),
        'impact': cve.get('impact', None),
        'vulnerable_products': [],
        'references': {},
    }
    # Set CWE
    cwe_id = cve.get('cwe', None)
    _cwe = CWE.objects.filter(cwe_id=cwe_id).first()
    if _cwe is not None:
        _new_cve.update({'cwe': _cwe})

    # Set vulnerable products (CPE vectors)
    for vp in cve['vulnerable_product']:
        _new_cve['vulnerable_products'].append(vp)

    # Set reference links
    refs = []
    for ref in cve['references']:
        refs.append(ref)
    _new_cve['references'].update({'others': refs})

    cur_cve = CVE.objects.filter(cve_id=cve['id']).first()
    if cur_cve is None:
        # Create it
        try:
            cur_cve = CVE(**_new_cve)
            cur_cve.save()
        except Exception as e:
            logger.error(e)
    else:
        # Update it
        has_update = False
        for v in _new_cve.keys():
            if _new_cve[v] != getattr(cur_cve, v):
                has_update = True
                setattr(cur_cve, v, _new_cve[v])
        if has_update is True:
            cur_cve.save()

    cur_cve.save()
    # logger.info("Elapsed to CVE update: {}".format(time() - start_time))

    # Update Products
    try:
        cpes = {}
        for vp in cur_cve.vulnerable_products:
            c = _CPE(vp)
            v = c.get_vendor()[0]
            p = c.get_product()[0]
            s = c.get_version()[0]
            if v not in cpes.keys():
                cpes.update({v: {}})
            if p not in cpes[v].keys():
                cpes[v].update({p: []})
            if s not in cpes[v][p]:
                cpes[v][p].append(s)

        for cpes_vendor in cpes.keys():
            vendor, inv = Vendor.objects.get_or_create(name=cpes_vendor)

            for cpe_product in cpes[cpes_vendor].keys():
                product, inp = Product.objects.get_or_create(name=cpe_product, vendor=vendor)
                if product.id not in cur_cve.products.all().only('id').values_list('id', flat=True):
                    cur_cve.products.add(product)

                # for cpe_version in cpes[cpes_vendor][cpe_product]:
                #     productversion, inpv = ProductVersion.objects.get_or_create(version=cpe_version, product=product, vector=vp)
                #     if productversion.id not in cur_cve.productversions.all().only('id').values_list('id', flat=True):
                #         cur_cve.productversions.add(productversion)

    except Exception as e:
        logger.error(e)

    # logger.info("Elapsed to Products updates: {}".format(time() - start_time))

    # Update VIA references (if any)
    if via and bool(deepdiff.DeepDiff(without_keys(via, ['id', '_id']), cur_cve.references, ignore_order=True)):
        cur_cve.references = without_keys(via, ['id', '_id'])
        cur_cve.save(update_fields=["references"])

    # Create or update Vuln (metrics)
    sync_vuln_fromcve(cve=cur_cve)
    # logger.info("Elapsed to VIA updates (Finished): {}".format(time() - start_time))


def sync_via_fromdb(from_date=None):
    cli = MongoClient(
        settings.DATABASES['mongodb']['HOST'],
        settings.DATABASES['mongodb']['PORT'])
    db = cli['cvedb']
    vias = db.via4

    my_cves = CVE.objects.values_list('cve_id', flat=True)

    current_year = datetime.datetime.now().year
    for year in range(1999, current_year+1):
        for fi in range(0, 10):
            cursor_via = vias.find({'id': {'$regex': '^CVE-{}-{}'.format(year, fi)}})
            via_list = [v for v in cursor_via]
            for via in via_list:
                # for via in cursor_via:
                if via['id'] in my_cves:
                    cve = CVE.objects.get(cve_id=via['id'])
                    cve.references = {
                        'refmap': via.get('refmap', []),
                        'sources': without_keys(via, ['id', 'refmap', '_id'])
                    }
                    cve.save(update_fields=["references"])
                    # Create / Update Vuln
                    # sync_exploits_fromvia(cve=cve)
                    # break
            cursor_via.close()
    return True


def sync_exploits_fromvia(vuln_id=None, cve=None, from_date=None):
    if vuln_id is None and cve is None:
        return False
    vuln = None
    if vuln_id is not None:
        vuln = Vuln.objects.prefetch_related('cve').filter(id=vuln_id).first()
    elif cve is not None:
        vuln = Vuln.objects.prefetch_related('cve').filter(cve=cve).first()
    if vuln is None:
        return False
    logger.debug("Syncing vuln '{}' --> '{}'".format(vuln, vuln.cve_id))

    reflinks = []
    reflinkids = {}

    refs = vuln.cve.references
    ## Others (from the CVE bulletin)
    if 'others' in refs.keys():
        reflinks = refs['others']

    ## Exploit-DB
    if 'exploit-db' in refs.keys():
        vuln.is_exploitable = True
        vuln.is_confirmed = True
        for e in refs['exploit-db']:
            exploitdb_id = e.get('id')
            e_pubdate, e_update = _extract_exploit_dates(
                e.get('published', None), e.get('modified', None)
            )
            _new_exploit = {
                'vuln': vuln,
                'publicid': e.get('id', 'n/a'),
                'link': e.get('source', 'https://www.exploit-db.com/exploits/{}'.format(exploitdb_id)),
                'notes': "{}-{}\n{}".format(e['id'], e.get('title', '-'), e.get('description', '-')),
                'trust_level': 'trusted',
                'tlp_level': 'white',
                'source': 'exploit-db',
                'availability': 'public',
                'type': 'exploitation',
                'maturity': 'functional',
                'published': e_pubdate,
                'modified': e_update,
                'raw': e
            }
            ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
            _new_exploit.update({'hash': ex_hash})
            ex = ExploitMetadata.objects.filter(
                vuln=vuln, link=_new_exploit['link']).first()
            if ex is None:
                new_exploit = ExploitMetadata(**_new_exploit)
                new_exploit.save()
                reflinks.append('https://www.exploit-db.com/exploits/{}'.format(exploitdb_id))
                reflinkids.update({'edb': exploitdb_id})

    ## Metasploit
    if 'metasploit' in refs.keys():
        vuln.is_exploitable = True
        vuln.is_confirmed = True
        for e in refs['metasploit']:
            e_pubdate, e_update = _extract_exploit_dates(
                e.get('published', None), e.get('modified', None)
            )
            _new_exploit = {
                'vuln': vuln,
                'publicid': e.get('id', 'n/a'),
                'link': e.get('source', 'https://github.com/rapid7/metasploit-framework/blob/master//modules/'),
                'notes': "{}-{}\n{}\n\nLinks:\n{}".format(
                    e['id'],
                    e.get('title', '-'),
                    e.get('description', '-'),
                    e.get('references', '-')
                ),
                'trust_level': 'trusted',
                'tlp_level': 'white',
                'source': 'metasploit',
                'availability': 'public',
                'type': 'exploitation',
                'maturity': 'functional',
                'published': e_pubdate,
                'modified': e_update,
                'raw': e
            }
            ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
            _new_exploit.update({'hash': ex_hash})
            ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
            if ex is None:
                new_exploit = ExploitMetadata(**_new_exploit)
                new_exploit.save()
                reflinks.extend(e.get('references', []))

    ## PacketStorm
    if 'packetstorm' in refs.keys():
        vuln.is_exploitable = True
        vuln.is_confirmed = True
        for e in refs['packetstorm']:
            e_pubdate, e_update = _extract_exploit_dates(
                e.get('published', None), e.get('modified', None)
            )
            _new_exploit = {
                'vuln': vuln,
                'publicid': e.get('id', 'n/a'),
                'link': e.get('source', 'https://github.com/rapid7/metasploit-framework/blob/master//modules/'),
                'notes': "{}-{}\n{}".format(
                    e['id'],
                    e.get('title', '-'),
                    e.get('data source', '-'),
                ),
                'trust_level': 'trusted',
                'tlp_level': 'white',
                'source': 'packetstorm',
                'availability': 'public',
                'type': 'exploitation',
                'maturity': 'functional',
                'published': e_pubdate,
                'modified': e_update,
                'raw': e
            }
            ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
            _new_exploit.update({'hash': ex_hash})
            ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
            if ex is None:
                new_exploit = ExploitMetadata(**_new_exploit)
                new_exploit.save()
                reflinks.append(e.get('source', None))
                reflinks.append(e.get('data source', None))

    ## Vulnerability-lab
    if 'vulner lab' in refs.keys():
        vuln.is_exploitable = True
        vuln.is_confirmed = True
        for e in refs['vulner lab']:
            e_pubdate, e_update = _extract_exploit_dates(
                e.get('published', None), e.get('modified', None)
            )
            _new_exploit = {
                'vuln': vuln,
                'publicid': e.get('id', 'n/a'),
                'link': e.get('source', 'n/a'),
                'notes': "{}-{}".format(
                    e['id'],
                    e.get('title', '-')
                ),
                'trust_level': 'trusted',
                'tlp_level': 'white',
                'source': 'vulnerabilty-lab',
                'availability': 'public',
                'type': 'exploitation',
                'maturity': 'functional',
                'published': e_pubdate,
                'modified': e_update,
                'raw': e
            }
            ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
            _new_exploit.update({'hash': ex_hash})
            ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
            if ex is None:
                new_exploit = ExploitMetadata(**_new_exploit)
                new_exploit.save()
                reflinks.append(e.get('source', None))

    ## Seebug
    if 'Seebug' in refs.keys():
        for e in refs['Seebug']:
            if e['bulletinFamily'] == 'exploit':
                vuln.is_exploitable = True
                vuln.is_confirmed = True
                e_pubdate, e_update = _extract_exploit_dates(
                    e.get('published', None), e.get('modified', None)
                )
                link = ''
                if 'source' in e.keys():
                    link = e['source']
                elif 'id' in e.keys():
                    ssvid = "https://www.seebug.org/vuldb/ssvid-{}".format(
                        e['id'].split(':')[1]
                    )
                    link = ssvid
                _new_exploit = {
                    'vuln': vuln,
                    'publicid': e.get('id', 'n/a'),
                    'link': link,
                    'notes': "{}-{}\n{}".format(
                        e['id'],
                        e.get('title', '-'),
                        e.get('description', '-')
                    ),
                    'trust_level': 'trusted',
                    'tlp_level': 'white',
                    'source': 'seebug',
                    'availability': 'public',
                    'type': 'exploitation',
                    'maturity': 'functional',
                    'published': e_pubdate,
                    'modified': e_update,
                    'raw': e
                }
                ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
                _new_exploit.update({'hash': ex_hash})
                ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
                if ex is None:
                    new_exploit = ExploitMetadata(**_new_exploit)
                    new_exploit.save()
                    reflinks.append(link)

    ## Talos
    if 'talos' in refs.keys():
        vuln.is_exploitable = True
        vuln.is_confirmed = True
        for e in refs['talos']:
            e_pubdate, e_update = _extract_exploit_dates(
                e.get('published', None), e.get('modified', None)
            )
            _new_exploit = {
                'vuln': vuln,
                'publicid': e.get('id', 'n/a'),
                'link': e.get('source', 'n/a'),
                'notes': "{}-{}".format(
                    e['id'],
                    e.get('title', '-')
                ),
                'trust_level': 'trusted',
                'tlp_level': 'white',
                'source': 'talos',
                'availability': 'public',
                'type': 'exploitation',
                'maturity': 'functional',
                'published': e_pubdate,
                'modified': e_update,
                'raw': e
            }
            ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
            _new_exploit.update({'hash': ex_hash})
            ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
            if ex is None:
                new_exploit = ExploitMetadata(**_new_exploit)
                new_exploit.save()
                reflinks.append(e.get('source', None))

    ## Nessus DB
    if 'nessus' in refs.keys():
        vuln.is_confirmed = True
        for e in refs['nessus']:
            e_pubdate, e_update = _extract_exploit_dates(
                e.get('published', None), e.get('modified', None)
            )
            e_info = {
                'exploit_available': False,
                'exploit_available_from': []
            }
            if 'sourceData' in e.keys():
                if '"exploitability_ease", value:"Exploits are available"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info.update({'exploit_available': True})
                if '"exploitability_ease", value:"No exploit is required"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info.update({'exploit_available': True})
                if '"exploit_available", value:"true"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info.update({'exploit_available': True})
                if '"exploit_framework_core", value:"true"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info['exploit_available_from'].append("Core Impact")
                if '"exploit_framework_metasploit", value:"true"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info['exploit_available_from'].append("Metasploit")
                if '"exploit_framework_canvas", value:"true"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info['exploit_available_from'].append("Canvas")
                if '"exploit_framework_exploithub", value:"true"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info['exploit_available_from'].append("ExploitHub")
                if '"exploit_framework_d2_elliot", value:"true"' in e['sourceData']:
                    vuln.is_exploitable = True
                    e_info['exploit_available_from'].append("Elliot")
                if '"in_the_news", value:"true"' in e['sourceData']:
                    vuln.is_in_the_news = True
                if '"exploited_by_malware", value:"true"' in e['sourceData']:
                    vuln.is_in_the_wild = True

            if e_info['exploit_available'] is True:
                _new_exploit = {
                    'vuln': vuln,
                    'publicid': e.get('plugin id', 'n/a'),
                    'link': e.get('source', 'n/a'),
                    'notes': "{}-{}\nFramework(s):{}\n{}".format(
                        e['plugin id'],
                        e.get('title', '-'),
                        ", ".join(e_info['exploit_available_from']),
                        e.get('description', '-')
                    ),
                    'trust_level': 'trusted',
                    'tlp_level': 'white',
                    'source': 'nessus',
                    'availability': 'public',
                    'type': 'exploitation',
                    'maturity': 'functional',
                    'published': e_pubdate,
                    'modified': e_update,
                    'raw': e
                }
                ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
                _new_exploit.update({'hash': ex_hash})
                ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
                if ex is None:
                    new_exploit = ExploitMetadata(**_new_exploit)
                    new_exploit.save()
                    reflinks.append(e.get('source', None))

    ## THN
    if 'the hacker news' in refs.keys():
        vuln.is_in_the_news = True
        for t in refs['the hacker news']:
            t_pubdate, t_update = _extract_exploit_dates(
                t.get('published', None), t.get('modified', None)
            )
            _new_threat = {
                'vuln': vuln,
                'link': t.get('source', 'n/a'),
                'notes': "{}".format(t.get('title', '-')),
                'trust_level': 'trusted',
                'tlp_level': 'white',
                'source': 'the-hacker-news',
                'is_in_the_news': True,
                'published': t_pubdate,
                'modified': t_update,
                'raw': t
            }
            th = ThreatMetadata.objects.filter(vuln=vuln, link=_new_threat['link']).first()
            if th is None:
                new_threat = ThreatMetadata(**_new_threat)
                new_threat.save()
                reflinks.append(t.get('source', None))

    ## REFMAP
    if 'refmap' in refs.keys():
        reflinkids.update(refs['refmap'])

        # Confirm
        if 'confirm' in refs['refmap'].keys():
            vuln.is_confirmed = True
            for c in refs['refmap']['confirm']:
                reflinks.append(c)

        # SecurityFocus
        if 'bid' in refs['refmap'].keys():
            for b in refs['refmap']['bid']:
                reflinks.append('https://www.securityfocus.com/bid/{}'.format(b))

        # IBM X-Force
        # if 'xf' in refs['refmap'].keys():
        #     for xf in refs['refmap']['xf']:
        #         reflinks.append('https://exchange.xforce.ibmcloud.com/vulnerabilities/{}'.format(xf))

        # misc
        if 'misc' in refs['refmap'].keys():
            for b in refs['refmap']['misc']:
                reflinks.append(b)
                if b.endswith(".pdf") or b.endswith(".py"):
                    vuln.is_exploitable = True
                    _new_exploit = {
                        'vuln': vuln,
                        'publicid': 'n/a',
                        'link': b,
                        'notes': "PoC or exploit found:\n{}".format(b),
                        'trust_level': 'unknown',
                        'tlp_level': 'white',
                        'source': 'misc',
                        'availability': 'public',
                        'type': 'unknown',
                        'maturity': 'poc',
                        'published': datetime.date.today(),
                        'modified': datetime.date.today(),
                        'raw': b
                    }
                    ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
                    _new_exploit.update({'hash': ex_hash})
                    ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
                    if ex is None:
                        new_exploit = ExploitMetadata(**_new_exploit)
                        new_exploit.save()

                for feed in COMMON_EXPLOIT_FEEDS:
                    if feed in b:
                        vuln.is_exploitable = True
                        _new_exploit = {
                            'vuln': vuln,
                            'publicid': 'n/a',
                            'link': b,
                            'notes': "PoC or exploit found:\n{}".format(b),
                            'trust_level': 'unknown',
                            'tlp_level': 'white',
                            'source': 'misc',
                            'availability': 'public',
                            'type': 'unknown',
                            'maturity': 'poc',
                            'published': datetime.date.today(),
                            'modified': datetime.date.today(),
                            'raw': b
                        }
                        ex_hash = hash(json.dumps(_new_exploit, sort_keys=True, default=_json_serial))
                        _new_exploit.update({'hash': ex_hash})
                        ex = ExploitMetadata.objects.filter(vuln=vuln, link=_new_exploit['link']).first()
                        if ex is None:
                            new_exploit = ExploitMetadata(**_new_exploit)
                            new_exploit.save()

    # Update reflinks and reflinkids
    reflinks.extend(vuln.reflinks)
    if sorted(vuln.reflinks) != sorted(set(reflinks)) or (not reflinkids.items() <= vuln.reflinkids.items()):
        vuln.reflinks = sorted(set(reflinks))
        vuln.reflinkids.update(reflinkids)
        vuln.save()
    return True


def sync_vuln_fromcve(cve):
    _vuln_data = {
        'cve': cve,
        'cveid': cve.cve_id,
        'summary': cve.summary,
        'published': cve.published,
        'modified': cve.modified,
        'assigner': cve.assigner,
        'cvss': cve.cvss,
        'cvss_time': cve.cvss_time,
        'cvss_vector': cve.cvss_vector,
        'cwe': cve.cwe,
        'vulnerable_products': cve.vulnerable_products,
        'access': cve.access,
        'impact': cve.impact
    }
    vuln = Vuln.objects.filter(cve=cve).first()
    if vuln is None:
        vuln = Vuln(**_vuln_data)
        vuln.save()
    else:
        has_update = False
        for v in _vuln_data.keys():
            if _vuln_data[v] != getattr(vuln, v):
                has_update = True
                setattr(vuln, v, _vuln_data[v])
        if has_update is True:
            vuln.save()

    # Sync Products & Product versions
    for cp in cve.products.all():
        if cp not in vuln.products.all():
            vuln.products.add(cp)

    vuln.update_product_versions()

    # productversions_list = list(vuln.productversions.only('id').values_list('id', flat=True))
    # for cpv in cve.productversions.only('id').values_list('id', flat=True):
    #     if cpv not in productversions_list:
    #         vuln.productversions.add(cpv)
    #         productversions_list.append(cpv)
    vuln.save()

    sync_exploits_fromvia(vuln.id)
    return vuln


def get_cve_references(cve_id):
    is_exploitable = False
    exploit_ref = []
    exploit_info = {}
    is_confirmed = False
    confirm_ref = []

    try:
        r = requests.get(settings.CVESEARCH_URL+"/api/cve/"+cve_id)
        cve = r.json()
    except Exception:
        logger.exception("Bad request to CVE-SEARCH")
        return None

    if not cve:
        logger.error("CVE '{}' not found".format(cve_id))
        return None

    ## Exploit-DB
    if 'exploit-db' in cve.keys():
        is_exploitable = True
        for e in cve['exploit-db']:
            exploit_ref.append(e['source'])
    if 'references' in cve.keys():
        for r in cve['references']:
            if 'exploit-db' in r:
                is_exploitable = True
                exploit_ref.append(r)
    if 'refmap' in cve.keys() and 'misc' in cve['refmap'].keys():
        for r in cve['refmap']['misc']:
            if 'exploit-db' in r:
                is_exploitable = True
                exploit_ref.append(r)

    ## Metasploit
    if 'metasploit' in cve.keys():
        is_exploitable = True
        for m in cve['metasploit']:
            exploit_ref.append(m['source'])

    ## PackeStorm
    if 'packetstorm' in cve.keys():
        is_exploitable = True
        for p in cve['packetstorm']:
            exploit_ref.append(p['data source'])
            exploit_ref.append(p['source'])

    ## vulnerability-lab
    if 'vulner lab' in cve.keys():
        is_exploitable = True
        for v in cve['vulner lab']:
            exploit_ref.append(v['source'])

    ## Seebug
    if 'Seebug' in cve.keys():
        for e in cve['Seebug']:
            if e['bulletinFamily'] == 'exploit':
                is_exploitable = True
                if 'source' in e.keys():
                    exploit_ref.append(e['source'])
                elif 'id' in e.keys():
                    ssvid = "https://www.seebug.org/vuldb/ssvid-{}".format(
                        e['id'].split(':')[1]
                    )
                    exploit_ref.append(ssvid)
                # if 'description' in e.keys():
                #     exploit_desc.append(e['description'])

    ## Nessus DB
    if 'nessus' in cve.keys():
        exploit_info.update({
            'exploitability_ease': 'No known exploits are available',
            'exploit_available': False,
            'exploit_framework_core': False,
            'exploit_framework_metasploit': False,
            'in_the_news': False
        })
        for n in cve['nessus']:
            if 'sourceData' in n.keys():
                if '"exploitability_ease", value:"Exploits are available"' in n['sourceData']:
                    is_exploitable = True
                    exploit_info.update({'exploitability_ease': 'Exploits are available'})
                if '"exploitability_ease", value:"No exploit is required"' in n['sourceData']:
                    is_exploitable = True
                    exploit_info.update({'exploitability_ease': 'No exploit is required'})
                if '"exploit_available", value:"true"' in n['sourceData']:
                    is_exploitable = True
                    exploit_info.update({'exploit_available': True})
                if '"exploit_framework_core", value:"true"' in n['sourceData']:
                    is_exploitable = True
                    exploit_info.update({'exploit_framework_core': True})
                if '"exploit_framework_metasploit", value:"true"' in n['sourceData']:
                    is_exploitable = True
                    exploit_info.update({'exploit_framework_metasploit': True})
                if '"in_the_news", value:"true"' in n['sourceData']:
                    exploit_info.update({'in_the_news': True})

            # Todo: Check CVSS score/vector and update value if not set

    if 'references' in cve.keys():
        exploit_feeds = [
            "exploit-db.com",
            "github.com",
            "raw.githubusercontent.com",
            "youtube.com"
        ]
        # if 'misc' in cve['refmap'].keys():
        for link in cve['references']:
            if link.endswith(".pdf"):
                exploit_ref.append(link)
            elif link.endswith(".py"):
                exploit_ref.append(link)
            for feed in exploit_feeds:
                if feed in link:
                    is_exploitable = True
                    exploit_ref.append(link)

    if 'refmap' in cve.keys():
        if 'confirm' in cve['refmap'].keys():
            is_confirmed = True
            for link in cve['refmap']['confirm']:
                confirm_ref.append(link)

    return {
        'is_exploitable': is_exploitable,
        'exploit_ref': sorted(set(exploit_ref)),
        'exploit_info': exploit_info,
        'is_confirmed': is_confirmed,
        'confirm_ref': confirm_ref,
        'raw': cve,
        'source': 'cvesearch'
    }
