from django.contrib.contenttypes.models import ContentType
from django.db import models as models

KEY_CHOICES = (
    ("TOTAL_REWARD", "TOTAL_REWARD"),
    ("MAX_REWARD", "MAX_REWARD"),
    ("N", "N"),
    ("CONFIRMATION_LENGTH", "CONFIRMATION_LENGTH"))

DEFAULT_KEY_VALUES = {
    'TOTAL_REWARD': 65,
    'MAX_REWARD': 35,
    'N': 5,
    'CONFIRMATION_LENGTH': 10,
}


class Miner(models.Model):
    nick_name = models.CharField(max_length=255, blank=True)
    public_key = models.CharField(max_length=256, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}'.format(self.public_key)


class Share(models.Model):
    STATUS_CHOICE = (
        (1, "solved"),
        (2, "valid"),
        (3, "invalid"),
        (4, "repetitious"))

    share = models.CharField(max_length=255, blank=False)
    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    status = models.IntegerField(blank=False, choices=STATUS_CHOICE)
    transaction_id = models.CharField(max_length=40, blank=True, null=True)
    block_height = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}-{}'.format(self.miner.public_key, self.share)


class Balance(models.Model):
    STATUS_CHOICE = (
        (1, "immature"),
        (2, "mature"),
        (3, "withdraw"))

    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    share = models.ForeignKey(Share, on_delete=models.CASCADE)
    balance = models.FloatField(default=0)
    status = models.IntegerField(blank=False, choices=STATUS_CHOICE, default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}-{}'.format(str(self.miner), self.balance)


class ConfigurationManager(models.Manager):

    def __getattr__(self, attr):
        """
        overriding __gerattr__ to create new 2 attributes for Configuration.object based on KEY_CHOICES.
        :param attr:
        :return:
        """
        if attr in [key for (key, temp) in KEY_CHOICES]:
            configurations = self.get_queryset().all()
            if attr not in configurations:
                return DEFAULT_KEY_VALUES[attr]
            else:
                return self.get_queryset().get(key=attr)
        else:
            return super(ConfigurationManager, self).__getattribute__(attr)


class Configuration(models.Model):
    key = models.CharField(max_length=255, choices=KEY_CHOICES, blank=False)
    value = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConfigurationManager()

    def __str__(self):
        return self.key + ":" + str(self.value)
