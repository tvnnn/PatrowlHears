# Generated by Django 3.0.9 on 2020-09-21 12:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0007_auto_20200805_1106'),
    ]

    operations = [
        migrations.AlterField(
            model_name='datasync',
            name='mdl_name',
            field=models.CharField(choices=[('kb_vendor', 'kb_vendor'), ('kb_product', 'kb_product'), ('kb_product_version', 'kb_product_version'), ('kb_bulletin', 'kb_bulletin'), ('kb_cwe', 'kb_cwe'), ('kb_cpe', 'kb_cpe'), ('kb_cve', 'kb_cve'), ('vulns', 'vulns'), ('exploits', 'exploits'), ('threats', 'threats')], default='', max_length=50),
        ),
    ]
