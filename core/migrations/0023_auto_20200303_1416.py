# Generated by Django 2.2.9 on 2020-03-03 14:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_auto_20200226_1001'),
    ]

    operations = [
        migrations.AddField(
            model_name='balance',
            name='max_height',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='balance',
            name='min_height',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='balance',
            name='tx_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
