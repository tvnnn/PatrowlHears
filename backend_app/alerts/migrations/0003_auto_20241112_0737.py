# Generated by Django 3.1.14 on 2024-11-12 07:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0002_auto_20210409_1928'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alertingrule',
            name='action',
            field=models.CharField(choices=[('debug', 'Debug'), ('event', 'PatrowlHears event'), ('logfile', 'Logfile'), ('email', 'Email'), ('thehive', 'TheHive alert'), ('twitter', 'Twitter message'), ('slack', 'Slack message'), ('telegram', 'Telegram message'), ('splunk', 'Splunk message')], default='debug', max_length=10),
        ),
        migrations.AlterField(
            model_name='alertingtemplate',
            name='action',
            field=models.CharField(choices=[('debug', 'Debug'), ('event', 'PatrowlHears event'), ('logfile', 'Logfile'), ('email', 'Email'), ('thehive', 'TheHive alert'), ('twitter', 'Twitter message'), ('slack', 'Slack message'), ('telegram', 'Telegram message'), ('splunk', 'Splunk message')], default='debug', max_length=10),
        ),
    ]
