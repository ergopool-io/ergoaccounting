# Generated by Django 2.2.9 on 2020-01-01 09:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_auto_20191222_0821'),
    ]

    operations = [
        migrations.AlterField(
            model_name='configuration',
            name='key',
            field=models.CharField(choices=[('TOTAL_REWARD', 'TOTAL_REWARD'), ('MAX_REWARD', 'MAX_REWARD'), ('PPLNS_N', 'PPLNS_N'), ('PERIOD_TIME', 'PERIOD_TIME')], max_length=255),
        ),
    ]
