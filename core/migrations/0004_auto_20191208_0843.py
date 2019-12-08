# Generated by Django 2.2 on 2019-12-08 08:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_auto_20191205_1246'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='share',
            name='status',
        ),
        migrations.AlterField(
            model_name='configuration',
            name='key',
            field=models.CharField(choices=[('TOTAL_REWARD', 'TOTAL_REWARD'), ('MAX_REWARD', 'MAX_REWARD'), ('N', 'N')], max_length=255),
        ),
        migrations.AddField(
            model_name='share',
            name='status',
            field=models.CharField(choices=[('solved', 'solved'), ('valid', 'valid'), ('invalid', 'invalid'),
                                            ('repetitious', 'repetitious')], default="invalid", max_length=100),
            preserve_default=False,
        ),
    ]
