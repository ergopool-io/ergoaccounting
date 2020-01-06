from django.contrib.contenttypes.models import ContentType
from django.db import models as models
from pydoc import locate
import logging

logger = logging.getLogger(__name__)


CONFIGURATION_KEY_CHOICE = (
    ("TOTAL_REWARD", "TOTAL_REWARD"),
    ("MAX_REWARD", "MAX_REWARD"),
    ("PPLNS_N", "PPLNS_N"),
    ("FEE", "FEE"),
    ("PERIOD_TIME", "PERIOD_TIME"),
    ("REWARD_ALGORITHM", "REWARD_ALGORITHM"),
    ("TRANSACTION_FEE", "TRANSACTION_FEE"),
    ("MAX_NUMBER_OF_OUTPUTS", "MAX_NUMBER_OF_OUTPUTS")

)

CONFIGURATION_KEY_TO_TYPE = {
    "TOTAL_REWARD": "float",
    "MAX_REWARD": "float",
    "PPLNS_N": "int",
    "FEE": "float",
    "PERIOD_TIME": "float",
    'REWARD_ALGORITHM': 'str',
    'TRANSACTION_FEE': 'int',
    "MAX_NUMBER_OF_OUTPUTS": 'int',
}

CONFIGURATION_DEFAULT_KEY_VALUE = {
    'TOTAL_REWARD': 65,
    'MAX_REWARD': 35,
    'PPLNS_N': 5,
    'FEE': 0.0,
    'PERIOD_TIME': 24 * 60 * 60,
    'REWARD_ALGORITHM': 'Prop',
    'TRANSACTION_FEE': 1000000,
    "MAX_NUMBER_OF_OUTPUTS": 5
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
        ("solved", "solved"),
        ("valid", "valid"),
        ("invalid", "invalid"),
        ("repetitious", "repetitious")
    )

    share = models.CharField(max_length=255, blank=False)
    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    status = models.CharField(blank=False, choices=STATUS_CHOICE, max_length=100)
    transaction_id = models.CharField(max_length=80, blank=True, null=True)
    difficulty = models.BigIntegerField(blank=False)
    block_height = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}-{}'.format(self.miner.public_key, self.share)


class Balance(models.Model):
    STATUS_CHOICE = (
        (1, "immature"),
        (2, "mature"),
        (3, "withdraw")
    )

    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    share = models.ForeignKey(Share, on_delete=models.CASCADE, null=True)
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
        if attr in [key for (key, temp) in CONFIGURATION_KEY_CHOICE]:
            configurations = dict(self.all().values_list('key', 'value'))
            if attr in configurations:
                val = configurations[attr]
                val_type = CONFIGURATION_KEY_TO_TYPE[attr]

                # trying to convert value to value_type
                try:
                    val = locate(val_type)(val)
                    return val

                except:
                    # failed to convert, return default value
                    logger.error('Problem in configuration; {} with value {} is not compatible with type {}'
                                 .format(attr, val, val_type))
                    return CONFIGURATION_DEFAULT_KEY_VALUE[attr]

            return CONFIGURATION_DEFAULT_KEY_VALUE[attr]

        else:
            return super(ConfigurationManager, self).__getattribute__(attr)


class Configuration(models.Model):
    key = models.CharField(max_length=255, choices=CONFIGURATION_KEY_CHOICE, blank=False)
    value = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConfigurationManager()

    def __str__(self):
        return self.key + ":" + str(self.value)
