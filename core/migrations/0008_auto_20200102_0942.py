# Generated by Django 2.2.9 on 2020-01-02 09:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_auto_20200101_0951'),
    ]

    operations = [
        migrations.AlterField(
            model_name='configuration',
            name='value',
            field=models.CharField(max_length=255),
        ),
    ]
