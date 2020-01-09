from rest_framework import serializers
from .models import *
import logging

logger = logging.getLogger(__name__)


class ShareSerializer(serializers.ModelSerializer):
    miner = serializers.CharField()
    difficulty = serializers.IntegerField()

    class Meta:
        model = Share
        fields = ['share', 'miner', 'status', 'transaction_id', 'block_height', 'difficulty']
        write_only_fields = ['transaction_id', 'block_height']

    def validate(self, attrs):
        """
        check request data. if we store a solved solution transaction_id and block height is required.
        otherwise these two field must be null
        :param attrs:
        :return:
        """
        # status is solved
        if attrs.get("status") == 1:
            if not attrs.get("transaction_id"):
                logger.debug('Transaction id is not provided for solved share.')
                raise serializers.ValidationError("transaction id is required when solved solution received")
            if not attrs.get("block_height"):
                logger.debug('Block height is not provided for solved share.')
                raise serializers.ValidationError("block height is required when solved solution received")
        else:
            if 'transaction_id' in attrs:
                del attrs['transaction_id']
            if 'block_height' in attrs:
                del attrs['block_height']
        return attrs


class BalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Balance
        fields = '__all__'
        read_only_fields = ['status']


class ConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Configuration
        fields = ['key', 'value']


class MinerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Miner
        fields = ['public_key', 'periodic_withdrawal_amount', 'nick_name']
        read_only_fields = ['public_key']

    def validate_periodic_withdrawal_amount(self, value):
        MIN_THRESHOLD = Configuration.objects.MIN_WITHDRAW_THRESHOLD
        MAX_THRESHOLD = Configuration.objects.MAX_WITHDRAW_THRESHOLD

        # threshold must be between specified config
        if not (MIN_THRESHOLD <= value <= MAX_THRESHOLD):
            raise serializers.ValidationError('threshold is not valid, must be between {} and {}'
                                              .format(MIN_THRESHOLD, MAX_THRESHOLD))

        return value


