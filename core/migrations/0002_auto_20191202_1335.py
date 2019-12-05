# Generated by Django 2.2.3 on 2019-12-02 13:35

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Configuration',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(choices=[('TOTAL_REWARD', 'TOTAL_REWARD'), ('MAX_REWARD', 'MAX_REWARD')],
                                         max_length=255)),
                ('value', models.FloatField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='Miner',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nick_name', models.CharField(blank=True, max_length=255)),
                ('public_key', models.CharField(max_length=256, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='Share',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('share', models.CharField(max_length=255)),
                ('status',
                 models.IntegerField(choices=[(1, 'solved'), (2, 'valid'), (3, 'invalid'), (4, 'repetitious')])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('miner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Miner')),
            ],
        ),
        migrations.CreateModel(
            name='Balance',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('balance', models.FloatField(default=0)),
                ('status', models.IntegerField(choices=[(1, 'immature'), (2, 'mature'), (3, 'withdraw')], default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('miner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Miner')),
                ('share', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Share')),
            ],
        ),
    ]