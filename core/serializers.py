from rest_framework import serializers
from .models import *
import logging

logger = logging.getLogger(__name__)


class AggregateShareSerializer(serializers.ModelSerializer):
    class Meta:
        model = AggregateShare
        fields = '__all__'


class ShareSerializer(serializers.ModelSerializer):
    miner = serializers.CharField()
    miner_address = serializers.CharField(required=False)
    lock_address = serializers.CharField(required=False)
    withdraw_address = serializers.CharField(required=False)
    difficulty = serializers.IntegerField()
    client_ip = serializers.IPAddressField(allow_blank=True, write_only=True)

    def create(self, validated_data):
        # Save ip of client in table of Detail Client
        client_ip = validated_data.pop('client_ip')
        obj, exist = MinerIP.objects.get_or_create(miner=validated_data.get('miner'), ip=client_ip)
        obj.save()

        return super(ShareSerializer, self).create(validated_data)

    def validate(self, attrs):
        """
        check request data. if we store a solved solution transaction_id and block height is required.
        otherwise these two field must be null
        :param attrs:
        :return:
        """
        if attrs.get("status") == 'solved':
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

        # in status of solved or valid parent_id and next parameters is required
        if attrs.get("status") == 'solved' or attrs.get("status") == 'valid':
            if not attrs.get("parent_id"):
                logger.debug('parent id is not provided for solved share.')
                raise serializers.ValidationError("parent id is required when solved or valid solution received")
            if not attrs.get("path"):
                logger.debug('path is not provided for solved or valid share.')
                raise serializers.ValidationError("path is required when solved or valid solution received")
        else:
            if 'parent_id' in attrs:
                del attrs['parent_id']
            if 'path' in attrs:
                del attrs['path']

        return attrs

    class Meta:
        model = Share
        fields = ['share', 'miner', 'status', 'transaction_id', 'block_height', 'difficulty',
                  'created_at', 'miner_address', 'lock_address', 'withdraw_address', 'parent_id',
                  'next_ids', 'path', 'client_ip']
        write_only_fields = ['transaction_id', 'block_height', 'parent_id', 'next_ids', 'path', 'client_ip']


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


