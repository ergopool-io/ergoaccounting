from rest_framework import serializers
from .models import *


class ShareSerializer(serializers.ModelSerializer):
    miner = serializers.CharField()

    class Meta:
        model = Share
        fields = ['share', 'miner', 'status', 'transaction_id', 'block_height']
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
                raise serializers.ValidationError("transaction id is required when solved solution received")
            if not attrs.get("block_height"):
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
