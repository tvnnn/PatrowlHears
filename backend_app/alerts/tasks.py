from celery import shared_task
from django.conf import settings
from .utils import send_email_message
from backend_app import slack
from backend_app import telegram
import time
from datetime import datetime
import json
import requests
import logging
logger = logging.getLogger(__name__)


@shared_task(bind=True, acks_late=True)
def send_email_message_task(self, short, long, template, recipients):
    logger.debug("Entering 'send_email_message_task'")
    send_email_message(short, long, template, recipients)
    return True


@shared_task(bind=True, acks_late=True)
def send_slack_message_task(self, message, apitoken, channel):
    logger.debug("Entering 'send_slack_message_task'")
    slack.send_slack_message(message, apitoken, channel)
    return True

@shared_task(bind=True, acks_late=True)
def telegram_alert_vuln_task(self, vuln_id, type):
    logger.debug("Entering 'telegram_alert_vuln_task'")
    from organizations.models import Organization
    for org in Organization.objects.all():
        if org.org_settings.alerts_telegram_enabled is True and org.org_settings.alerts_telegram['new_vuln'] is True and org.org_settings.alerts_telegram['bot_token'] != "" and org.org_settings.alerts_telegram['chat_id'] != "":
            from vulns.models import Vuln
            from vulns.utils import _is_vuln_monitored
            vuln = Vuln.objects.filter(id=vuln_id).first()
            # if _is_vuln_monitored(vuln, org):
            if type == "new":
                bot_token = org.org_settings.alerts_telegram['bot_token']
                chat_id = org.org_settings.alerts_telegram['chat_id']
                affected_products = ", ".join(["*{}* ({})".format(p.name.replace('_', ' ').title(), p.vendor.name.replace('_', ' ').title()) for p in vuln.products.all()])
                if vuln.reflinks:
                    references = "\n".join(f"- {link}" for link in vuln.reflinks)
                else:
                    references = "None"
                message = (f"*New vulnerability found!*\n"
                        f"*CVE ID:* [{vuln.cveid}](https://www.cve.org/CVERecord?id={vuln.cveid})\n"
                        f"*Summary:* {vuln.summary}\n"
                        f"*CVSSv3 Vector:* {vuln.cvss3_vector}\n"
                        f"*CVSSv3 Score:* {vuln.cvss3}\n"
                        f"*Assigner:* {vuln.assigner}\n"
                        f"*Affected Products:* {affected_products}\n"
                        f"*References:*\n {references}")
                telegram.send_message(bot_token, chat_id, message)
                time.sleep(2)
                return True
            else:
                return True
        else:
            return True
    

@shared_task(bind=True, acks_late=True)
def slack_alert_vuln_task(self, vuln_id, type="new"):
    from vulns.models import Vuln
    from organizations.models import Organization

    logger.debug("Entering 'slack_alert_vuln_task'")
    vuln = Vuln.objects.filter(id=vuln_id).first()
    if vuln is None:
        return False
    if type == "update":
        prefix = "PatrowlHears // Vulnerability changes detected ! {}, Score: {}".format(vuln.cveid, vuln.score)
    else:
        prefix = "PatrowlHears // New vulnerability found ! {}, Score: {}".format(vuln.cveid, vuln.score)
    curr_date = datetime.now().strftime("%B %d,%Y - %H:%M:%S")
    vuln_link = "<{}/#/vulns/{}|Direct link>".format(settings.BASE_URL, vuln.id)
    vuln_exploit_count = vuln.exploitmetadata_set.count()
    #@Todo: add organization exploits

    metrics = "\
        - Is Exploitable? {}\n\
        - Is Confirmed? {}\n\
        - In the Wild? {}\n\
        - In the News? {}".format(
        vuln.is_exploitable,
        vuln.is_confirmed,
        vuln.is_in_the_news,
        vuln.is_in_the_wild
    )

    affected_products = ", ".join(["*{}* ({})".format(p.name.replace('_', ' ').title(), p.vendor.name.replace('_', ' ').title()) for p in vuln.products.all()])

    for org in Organization.objects.all():
        if org.org_settings.alerts_slack_enabled is True and org.org_settings.alerts_slack['update_vuln'] is True and org.org_settings.alerts_slack['url'] != "":
            webhook_url = org.org_settings.alerts_slack['url']
            # slack_data = {'text': "Vulnerability changes detected: [PH-{}@{}] {}".format(vuln.id, vuln.score, vuln.summary)}
            banner = "[{}] *{}* - Score:*{}* - Exploits:*{}* - CVSSv2:*{}*".format(
                vuln_link,
                vuln.cveid,
                vuln.score,
                vuln_exploit_count + vuln.orgexploitmetadata_set.count(),
                vuln.cvss
            )

            slack_data = {
                "text": prefix,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "{}\n>{}\n{}".format(banner, vuln.summary, metrics)
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Affected products: {}".format(affected_products)
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "Last updated: {} by *PatrowlHears Slack alerting*".format(curr_date)
                            }
                        ]
                    }
                ]
            }
            try:
                response = requests.post(
                    webhook_url, data=json.dumps(slack_data),
                    headers={'Content-Type': 'application/json'}
                )
                if response.status_code != 200:
                    raise ValueError(
                        'Request to slack returned an error %s, the response is:\n%s'
                        % (response.status_code, response.text)
                    )
            except Exception as e:
                logger.error(e)
    return True
#
# {
# 	"blocks": [
# 		{
# 			"type": "section",
# 			"text": {
# 				"type": "mrkdwn",
# 				"text": "[<https://hears.patrowl.io/#/vuln/21324|PH-21324>][Score=80][E=3] CVE-2020-2222\n>qsoshdfkusgd"
# 			}
# 		},
# 		{
# 			"type": "context",
# 			"elements": [
# 				{
# 					"type": "mrkdwn",
# 					"text": "Last updated: Jan 1, 2019"
# 				}
# 			]
# 		}
# 	]
# }


@shared_task(bind=True, acks_late=True)
def email_instant_report_exploitable_task(self, vuln_id):
    from vulns.models import Vuln
    from vulns.utils import _is_vuln_monitored
    from organizations.models import Organization
    # print('in email_instant_report_exploitable_task', vuln_id)
    logger.debug("Entering 'email_instant_report_exploitable_task'")

    try:
        vuln = Vuln.objects.filter(id=vuln_id).first()
        if vuln is not None:
            for org in Organization.objects.filter(is_active=True):
                if org.org_settings.enable_instant_email_report_exploitable is True and _is_vuln_monitored(vuln, org):
                    send_email_message_task.apply_async(
                        args=[
                            "[PatrowlHears] PH-{} / Vulnerability has known exploit(s)".format(vuln.id),
                            vuln.to_dict(),
                            'vuln',
                            org.org_settings.alerts_emails
                        ],
                        queue='alerts',
                        retry=False
                    )
            # job = group([refresh_vuln_score_task.s(vuln.id) for vuln in vulns])
            # result = job.apply_async()
            # with allow_join_result():
            #     return result.get()
    except Exception as e:
        logger.error("Error in 'email_instant_report_exploitable_task'", e)


@shared_task(bind=True, acks_late=True)
def email_instant_report_cvss_change_task(self, vuln_id):
    from vulns.models import Vuln
    from vulns.utils import _is_vuln_monitored
    from organizations.models import Organization
    logger.debug("Entering 'email_instant_report_cvss_change_task'")

    try:
        vuln = Vuln.objects.filter(id=vuln_id).first()
        if vuln is not None:
            for org in Organization.objects.filter(is_active=True):
                if org.org_settings.enable_instant_email_report_cvss is True and float(vuln.cvss) >= float(org.org_settings.enable_instant_email_report_cvss_value) and _is_vuln_monitored(vuln, org):
                    send_email_message_task.apply_async(
                        args=[
                            "[PatrowlHears] PH-{} / Vulnerability CVSSv2 reach alert threshold".format(vuln.id),
                            vuln.to_dict(),
                            'vuln',
                            org.org_settings.alerts_emails
                        ],
                        queue='alerts',
                        retry=False
                    )
    except Exception as e:
        logger.error("Error in 'email_instant_report_cvss_change_task'", e)


@shared_task(bind=True, acks_late=True)
def email_instant_report_cvss3_change_task(self, vuln_id):
    from vulns.models import Vuln
    from vulns.utils import _is_vuln_monitored
    from organizations.models import Organization
    logger.debug("Entering 'email_instant_report_cvss3_change_task'")

    try:
        vuln = Vuln.objects.filter(id=vuln_id).first()
        if vuln is not None:
            for org in Organization.objects.filter(is_active=True):
                if org.org_settings.enable_instant_email_report_cvss3 is True and float(vuln.cvss3) >= float(org.org_settings.enable_instant_email_report_cvss3_value) and _is_vuln_monitored(vuln, org):
                    send_email_message_task.apply_async(
                        args=[
                            "[PatrowlHears] PH-{} / Vulnerability CVSSv3 reach alert threshold".format(vuln.id),
                            vuln.to_dict(),
                            'vuln',
                            org.org_settings.alerts_emails
                        ],
                        queue='alerts',
                        retry=False
                    )
    except Exception as e:
        logger.error("Error in 'email_instant_report_cvss3_change_task'", e)


@shared_task(bind=True, acks_late=True)
def email_instant_report_score_change_task(self, vuln_id, vuln_score):
    from vulns.models import Vuln
    from vulns.utils import _is_vuln_monitored
    from organizations.models import Organization
    logger.debug("Entering 'email_instant_report_score_change_task'")

    try:
        vuln = Vuln.objects.filter(id=vuln_id).first()
        if vuln is not None:
            for org in Organization.objects.filter(is_active=True):
                if org.org_settings.enable_instant_email_report_score is True and int(vuln_score) >= int(org.org_settings.enable_instant_email_report_score_value) and _is_vuln_monitored(vuln, org):
                    send_email_message_task.apply_async(
                        args=[
                            "[PatrowlHears] PH-{} / Vulnerability Score reach alert threshold".format(vuln.id),
                            vuln.to_dict(),
                            'vuln',
                            org.org_settings.alerts_emails
                        ],
                        queue='alerts',
                        retry=False
                    )
    except Exception as e:
        logger.error("Error in 'email_instant_report_score_change_task'", e)
