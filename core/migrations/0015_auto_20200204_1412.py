# Generated by Django 2.2.9 on 2020-02-04 14:12

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_auto_20200203_1235'),
    ]

    operations = [
        migrations.AddField(
            model_name='share',
            name='next_ids',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(blank=True, max_length=80, null=True), blank=True, default=list, null=True, size=None),
        ),
        migrations.AddField(
            model_name='share',
            name='parent_id',
            field=models.CharField(default='0', max_length=80),
        ),
        migrations.AddField(
            model_name='share',
            name='path',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]