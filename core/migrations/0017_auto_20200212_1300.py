# Generated by Django 2.2.9 on 2020-02-12 12:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_auto_20200210_0852'),
    ]

    operations = [
        migrations.AddField(
            model_name='share',
            name='is_orphaned',
            field=models.BooleanField(default=False),
        ),
    ]