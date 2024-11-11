# Generated by Django 3.1.8 on 2021-04-09 19:30

from django.db import migrations, models
import vpratings.models


class Migration(migrations.Migration):

    dependencies = [
        ('vpratings', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='historicalvprating',
            name='data',
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name='historicalvprating',
            name='score_details',
            field=models.JSONField(default=vpratings.models.get_default_scores),
        ),
        migrations.AlterField(
            model_name='vprating',
            name='data',
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name='vprating',
            name='score_details',
            field=models.JSONField(default=vpratings.models.get_default_scores),
        ),
    ]
