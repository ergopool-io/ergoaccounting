# Generated by Django 2.2.9 on 2019-12-22 08:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_auto_20191211_1029'),
    ]

    operations = [
        migrations.AddField(
            model_name='share',
            name='difficulty',
            field=models.BigIntegerField(blank=False),
            preserve_default=False,
        ),
    ]