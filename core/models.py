from django.contrib.contenttypes.models import ContentType
from django.db import models as models
from pydoc import locate
from frozendict import frozendict
import logging

logger = logging.getLogger(__name__)


CONFIGURATION_KEY_CHOICE = (
    # total reward of a round
    ("TOTAL_REWARD", "TOTAL_REWARD"),
    # maximum reward anyone can receive in reward sharing
    ("MAX_REWARD", "MAX_REWARD"),
    ("PPLNS_N", "PPLNS_N"),
    # pool fee which will be subtracted form reward before sharing
    ("FEE", "POOL_FEE"),
    # period time of hash rate
    ("PERIOD_TIME", "HASH_PERIOD_TIME"),
    # reward algorithm used for sharing reward
    ("REWARD_ALGORITHM", "REWARD_ALGORITHM"),
    # transaction fee of a transaction, 0.001
    ("TRANSACTION_FEE", "TRANSACTION_FEE"),
    # maximum number of outputs a transaction can have
    ("MAX_NUMBER_OF_OUTPUTS", "MAX_NUMBER_OF_OUTPUTS"),
    # miner can not set his withdrawal threshold smaller than this
    ("MIN_WITHDRAW_THRESHOLD", "MIN_WITHDRAW_THRESHOLD"),
    # miner can not set his withdrawal threshold bigger than this
    ("MAX_WITHDRAW_THRESHOLD", "MAX_WITHDRAW_THRESHOLD"),
    # default value for periodic withdrawal if not set by miner explicitly
    ("DEFAULT_WITHDRAW_THRESHOLD", "DEFAULT_WITHDRAW_THRESHOLD"),
    # confirmation length for balances to be mature
    ("CONFIRMATION_LENGTH", "confirmation length")
)

CONFIGURATION_KEY_TO_TYPE = frozendict({
    "TOTAL_REWARD": "float",
    "MAX_REWARD": "float",
    "PPLNS_N": "int",
    "FEE": "float",
    "PERIOD_TIME": "float",
    'REWARD_ALGORITHM': 'str',
    'TRANSACTION_FEE': 'float',
    "MAX_NUMBER_OF_OUTPUTS": 'int',
    "MAX_WITHDRAW_THRESHOLD": 'float',
    "MIN_WITHDRAW_THRESHOLD": 'float',
    "DEFAULT_WITHDRAW_THRESHOLD": 'float',
    "CONFIRMATION_LENGTH": 'int'
})

CONFIGURATION_DEFAULT_KEY_VALUE = frozendict({
    'TOTAL_REWARD': 65,
    'MAX_REWARD': 35,
    'PPLNS_N': 5,
    'FEE': 0.0,
    'PERIOD_TIME': 24 * 60 * 60,
    'REWARD_ALGORITHM': 'Prop',
    'TRANSACTION_FEE': 0.001,
    "MAX_NUMBER_OF_OUTPUTS": 5,
    "MAX_WITHDRAW_THRESHOLD": 100,
    "MIN_WITHDRAW_THRESHOLD": 1,
    "DEFAULT_WITHDRAW_THRESHOLD": 100,
    "CONFIRMATION_LENGTH": 720
})


class Miner(models.Model):
    nick_name = models.CharField(max_length=255, blank=True)
    public_key = models.CharField(max_length=256, unique=True)
    periodic_withdrawal_amount = models.FloatField(null=True)
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
        (3, "withdraw"),
        (4, "pending_withdrawal")
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
