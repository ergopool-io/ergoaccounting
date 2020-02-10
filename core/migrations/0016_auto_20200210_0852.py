# Generated by Django 2.2.9 on 2020-02-10 08:52

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_auto_20200204_1412'),
    ]

    operations = [
        migrations.CreateModel(
            name='MinerIP',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip', models.GenericIPAddressField(default='1.1.1.1')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('miner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Miner')),
            ],
            options={
                'unique_together': {('miner', 'ip')},
            },
        ),
    ]
