# Generated by Django 3.1.13 on 2022-04-19 14:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('custusers', '0006_auto_20210409_1930'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicaluser',
            name='changed_first_password',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='historicaluser',
            name='mfa_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='changed_first_password',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='mfa_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
