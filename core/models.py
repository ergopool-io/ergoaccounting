import logging
from pydoc import locate

from django.contrib.postgres.fields import ArrayField
from django.contrib.contenttypes.models import ContentType
from django.db import models as models
from frozendict import frozendict
from postgres_copy import CopyManager
from rest_framework.authtoken.models import Token


logger = logging.getLogger(__name__)

EXTRA_INFO_KEY_CHOICES = (
    ('ERGO_PRICE_USD', 'price of ergo in USD'),
    ('ERGO_PRICE_BTC', 'price of ergo in BTC')
)

EXTRA_INFO_KEY_TYPE = frozendict({
    'ERGO_PRICE_USD': 'float',
    'ERGO_PRICE_BTC': 'float'
})


CONFIGURATION_KEY_CHOICE = (
    ("POOL_BASE_FACTOR", "Pool base factor"),
    # total reward of a round
    ("TOTAL_REWARD", "TOTAL_REWARD"),
    # total_reward factor
    ("REWARD_FACTOR", "REWARD_FACTOR"),
    # pool fee factor
    ("FEE_FACTOR", "FEE_FACTOR"),
    # pool reward factor result precision
    ("REWARD_FACTOR_PRECISION", "REWARD_FACTOR_PRECISION"),
    # maximum reward anyone can receive in reward sharing
    ("MAX_REWARD", "MAX_REWARD"),
    ("PPLNS_N", "PPLNS_N"),
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
    ("CONFIRMATION_LENGTH", "confirmation length"),
    # latest allowed height for mining
    ("THRESHOLD_HEIGHT", "latest allowed height for mining"),
    # timestamp diff allowed to miner
    ("THRESHOLD_TIMESTAMP", "timestamp diff allowed to miner"),
)

CONFIGURATION_KEY_TO_TYPE = frozendict({
    "POOL_BASE_FACTOR": "int",
    "TOTAL_REWARD": "int",
    "REWARD_FACTOR": "float",
    "FEE_FACTOR": "float",
    "REWARD_FACTOR_PRECISION": "int",
    "MAX_REWARD": "int",
    "PPLNS_N": "int",
    'REWARD_ALGORITHM': 'str',
    'TRANSACTION_FEE': 'int',
    "MAX_NUMBER_OF_OUTPUTS": 'int',
    "MAX_WITHDRAW_THRESHOLD": 'int',
    "MIN_WITHDRAW_THRESHOLD": 'int',
    "DEFAULT_WITHDRAW_THRESHOLD": 'int',
    "CONFIRMATION_LENGTH": 'int',
    "THRESHOLD_HEIGHT": 'int',
    "THRESHOLD_TIMESTAMP": 'int',
})

CONFIGURATION_DEFAULT_KEY_VALUE = frozendict({
    'POOL_BASE_FACTOR': 1000,
    'TOTAL_REWARD': int(67.5e9),
    "REWARD_FACTOR": 0.96296297,
    'FEE_FACTOR': 0,
    "REWARD_FACTOR_PRECISION": 2,
    'MAX_REWARD': int(35e9),
    'PPLNS_N': 5,
    'REWARD_ALGORITHM': 'Prop',
    'TRANSACTION_FEE': 1000000,
    "MAX_NUMBER_OF_OUTPUTS": 5,
    "MAX_WITHDRAW_THRESHOLD": int(100e9),
    "MIN_WITHDRAW_THRESHOLD": int(1e9),
    "DEFAULT_WITHDRAW_THRESHOLD": int(100e9),
    "CONFIRMATION_LENGTH": 720,
    "THRESHOLD_HEIGHT": 10,
    "THRESHOLD_TIMESTAMP": 120,
})


class Miner(models.Model):
    nick_name = models.CharField(max_length=255, blank=True)
    public_key = models.CharField(max_length=256, unique=True)
    periodic_withdrawal_amount = models.BigIntegerField(null=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}'.format(self.public_key)


class Address(models.Model):
    address = models.CharField(max_length=255, blank=False, null=False, unique=True)
    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.address


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
    transaction_valid = models.BooleanField(blank=True, null=True)
    difficulty = models.BigIntegerField(blank=True, null=True)
    block_height = models.BigIntegerField(blank=True, null=True)
    parent_id = models.CharField(max_length=80, null=False, blank=False, default="0")
    next_ids = ArrayField(models.CharField(max_length=80, blank=True, null=True), blank=True, null=True, default=list)
    path = models.CharField(max_length=100, blank=True, null=True)
    pow_identity = models.CharField(max_length=200, blank=True, null=True)
    is_aggregated = models.BooleanField(default=False)
    miner_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, related_name='miner_addresses')
    is_orphaned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = CopyManager()

    def __str__(self):
        return '{}-{}'.format(self.miner.public_key, self.share)


class MinerIP(models.Model):
    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    ip = models.GenericIPAddressField(null=False, blank=False, default="1.1.1.1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["miner", "ip"]

    def __str__(self):
        return self.miner.public_key


class Transaction(models.Model):
    tx_id = models.CharField(blank=True, null=True, max_length=200)
    tx_body = models.TextField(blank=False, null=False)
    inputs = models.TextField(blank=False, null=False)  # comma-separated input boxes
    is_confirmed = models.BooleanField(default=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)


class Balance(models.Model):
    STATUS_CHOICE = (
        ("immature", "immature"),
        ("mature", "mature"),
        ("withdraw", "withdraw"),
        ("pending_withdrawal", "pending_withdrawal")
    )

    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    share = models.ForeignKey(Share, on_delete=models.CASCADE, null=True)
    balance = models.BigIntegerField(default=0)
    status = models.CharField(blank=False, choices=STATUS_CHOICE, default="immature", max_length=100)
    # will be used to generate tx, can be more or less than balance field
    actual_payment = models.BigIntegerField(default=0)
    tx = models.ForeignKey(Transaction, on_delete=models.CASCADE, null=True)
    min_height = models.IntegerField(null=True)
    max_height = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = CopyManager()

    class Meta:
        indexes = [
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return '{}-{}'.format(str(self.miner), self.balance)

    @property
    def is_orphaned(self):
        return self.status == 'mature' and self.balance < 0


class AggregateShare(models.Model):
    solved_share = models.ForeignKey(Share, on_delete=models.CASCADE)
    miner = models.ForeignKey(Miner, on_delete=models.CASCADE)
    valid_num = models.PositiveIntegerField()
    invalid_num = models.PositiveIntegerField()
    repetitious_num = models.PositiveIntegerField()
    difficulty_sum = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    objects = CopyManager()


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


class ExtraInfo(models.Model):
    key = models.CharField(max_length=255, choices=EXTRA_INFO_KEY_CHOICES, blank=False, unique=True)
    value = models.CharField(max_length=255, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key + ": " + str(self.value)


class TokenAuth(Token):
    """
    Extend last_use parameter for checking expire token.
    """
    last_use = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class HashRate(models.Model):
    network = models.FloatField()
    pool = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return str(self.created_at)

