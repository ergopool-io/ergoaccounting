# Generated by Django 2.2.9 on 2020-02-23 15:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_remove_miner_selected_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='share',
            name='transaction_valid',
            field=models.BooleanField(blank=True, null=True),
        )
    ]