from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _
from core import utils
from .models import *
import logging
import django_otp

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
        if not validated_data.get('miner').ip == client_ip:
            validated_data.get('miner').ip = client_ip
            validated_data.get('miner').save()
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
            if not attrs.get("pow_identity"):
                logger.error('pow_identity field must be present for solved shares.')
                raise serializers.ValidationError("pow_identity field must be present for solved shares.")
            if not attrs.get("transaction_id"):
                logger.error('Transaction id is not provided for solved share.')
                raise serializers.ValidationError("transaction id is required when solved solution received")
            if not attrs.get("block_height"):
                logger.error('Block height is not provided for solved share.')
                raise serializers.ValidationError("block height is required when solved solution received")
        else:
            if 'transaction_id' in attrs:
                del attrs['transaction_id']
            if 'block_height' in attrs:
                del attrs['block_height']

        # in status of solved or valid parent_id and next parameters is required
        if attrs.get("status") == 'solved' or attrs.get("status") == 'valid':
            if not attrs.get("parent_id"):
                logger.error('parent id is not provided for solved share.')
                raise serializers.ValidationError("parent id is required when solved or valid solution received")
            if not attrs.get("path"):
                logger.error('path is not provided for solved or valid share.')
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
                  'next_ids', 'path', 'client_ip', 'pow_identity']
        write_only_fields = ['transaction_id', 'block_height', 'parent_id', 'next_ids', 'path', 'client_ip', 'pow_identity']


class BalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Balance
        fields = '__all__'
        read_only_fields = ['status']


class ConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Configuration
        fields = ['key', 'value']

    def create(self, validated_data):
        key = validated_data['key']
        value = validated_data['value']
        configurations = Configuration.objects.filter(key=key)
        val_type = CONFIGURATION_KEY_TO_TYPE[key]
        try:
            locate(val_type)(value)

        except:
            return

        if not configurations:
            logger.info('Saving new configuration.')
            super().create(validated_data)
        else:
            logger.info('Updating configuration')
            configuration = Configuration.objects.get(key=key)
            configuration.value = value
            configuration.save()

    def save(self, **kwargs):
        pass


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


class ErgoAuthTokenSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    username = serializers.CharField(label=_("Username"))
    password = serializers.CharField(
        label=_("Password"),
        style={'input_type': 'password'},
        trim_whitespace=False
    )
    recaptcha_code = serializers.CharField(label="recaptcha code")
    otp_token = serializers.CharField(label="OTP_Token", required=False)

    def validate_recaptcha_code(self, value):
        if not utils.verify_recaptcha(value):
            raise ValidationError("please verify recaptcha code")

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        if username and password:
            user = authenticate(request=self.context.get('request'),
                                username=username, password=password)

            # The authenticate call simply returns None for is_active=False
            # users. (Assuming the default ModelBackend authentication
            # backend.)
            if not user:
                msg = _('Unable to log in with provided credentials.')
                raise serializers.ValidationError(msg, code='authorization')
        else:
            msg = _('Must include "username" and "password".')
            raise serializers.ValidationError(msg, code='authorization')
        # check that the user has an OTP device or not.
        if django_otp.user_has_device(user=user, confirmed=True):
            # for users that have OTP device, OTP-token is required.
            if not attrs.get('otp_token'):
                raise ValidationError("For this user, Two-Step verification is active so OTP Token is required.")
            # checked OTP Token that is valid or not
            if not django_otp.match_token(user, attrs.get('otp_token')):
                raise ValidationError("OTP Token is invalid.", code='authorization')
        attrs['user'] = user
        return attrs


class TOTPDeviceSerializer(serializers.Serializer):
    pass


class UIDataSerializer(serializers.Serializer):
    data = serializers.JSONField()

    class Meta:
        fields = ['data']


class SupportSerializer(serializers.Serializer):
    recaptcha_code = serializers.CharField(label="recaptcha code")
    name = serializers.CharField(required=False)
    email = serializers.EmailField()
    subject = serializers.CharField(required=False)
    message = serializers.CharField()

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    def validate_recaptcha_code(self, value):
        if not utils.verify_recaptcha(value):
            raise ValidationError("please verify recaptcha code")

    class Meta:
        field = '__all__'
