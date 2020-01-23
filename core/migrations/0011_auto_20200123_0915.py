# Generated by Django 2.2.9 on 2020-01-23 09:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_auto_20200109_1129'),
    ]

    operations = [
        migrations.AlterField(
            model_name='balance',
            name='balance',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='balance',
            name='status',
            field=models.IntegerField(choices=[(1, 'immature'), (2, 'mature'), (3, 'withdraw'), (4, 'pending_withdrawal')], default=1),
        ),
        migrations.AlterField(
            model_name='configuration',
            name='key',
            field=models.CharField(choices=[('TOTAL_REWARD', 'TOTAL_REWARD'), ('MAX_REWARD', 'MAX_REWARD'), ('PPLNS_N', 'PPLNS_N'), ('FEE', 'POOL_FEE'), ('PERIOD_TIME', 'HASH_PERIOD_TIME'), ('REWARD_ALGORITHM', 'REWARD_ALGORITHM'), ('TRANSACTION_FEE', 'TRANSACTION_FEE'), ('MAX_NUMBER_OF_OUTPUTS', 'MAX_NUMBER_OF_OUTPUTS'), ('MIN_WITHDRAW_THRESHOLD', 'MIN_WITHDRAW_THRESHOLD'), ('MAX_WITHDRAW_THRESHOLD', 'MAX_WITHDRAW_THRESHOLD'), ('DEFAULT_WITHDRAW_THRESHOLD', 'DEFAULT_WITHDRAW_THRESHOLD'), ('CONFIRMATION_LENGTH', 'confirmation length')], max_length=255),
        ),
        migrations.AlterField(
            model_name='miner',
            name='periodic_withdrawal_amount',
            field=models.BigIntegerField(null=True),
        ),
        migrations.AlterField(
            model_name='share',
            name='difficulty',
            field=models.BigIntegerField(),
        ),
    ]
