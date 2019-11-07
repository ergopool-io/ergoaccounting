from django.urls import reverse
from django.db.models import CharField
from django.db.models import FloatField
from django.db.models import IntegerField
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.contrib.auth import models as auth_models
from django.db import models as models

class Miner(models.Model):
    nick_name = models.CharField(max_length=255, blank=True)
    public_key = models.CharField(max_length=256, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}'.format(self.public_key)


class Share(models.Model):
    STATUS_CHOICE =(
        (1, "solved"),
        (2, "valid"),
        (3, "invalid"),
        (4, "repetitious"))
    
    share = models.CharField(max_length = 255,blank=False)
    miner = models.ForeignKey("Miner", on_delete=models.CASCADE)   
    nonce = models.IntegerField(blank=False)
    status = models.IntegerField(blank=False,choices=STATUS_CHOICE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}-{}'.format(self.miner.public_key, self.share)


class Balance(models.Model):
    STATUS_CHOICE = (
        (1, "immature"),
        (2, "mature"),
        (3, "withdraw"))

    miner = models.ForeignKey("Miner", on_delete=models.CASCADE)   
    share = models.CharField(max_length = 255,blank=True, null=True)
    balance = models.FloatField(default = 0)
    status = models.IntegerField(blank=False, choices=STATUS_CHOICE, default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}-{}'.format(self.public_key, self.balance)