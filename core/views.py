import logging
from datetime import datetime, timedelta
from pydoc import locate

from django.conf import settings
from django.db.models import Q, Count, Sum, Max, Min
from django.utils import timezone
from rest_framework import filters
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from core.models import Share, Miner, Balance, Configuration, CONFIGURATION_DEFAULT_KEY_VALUE, \
    CONFIGURATION_KEY_TO_TYPE, Address
from core.serializers import ShareSerializer, BalanceSerializer, MinerSerializer, ConfigurationSerializer
from core.tasks import generate_and_send_transaction
from core.utils import compute_hash_rate, RewardAlgorithm, BlockDataIterable

logger = logging.getLogger(__name__)

ERGO_EXPLORER_ADDRESS = getattr(settings, "ERGO_EXPLORER_ADDRESS")
MAX_PAGINATION_SIZE = getattr(settings, "MAX_PAGINATION_SIZE")
DEFAULT_PAGINATION_SIZE = getattr(settings, "DEFAULT_PAGINATION_SIZE")


class CustomPagination(PageNumberPagination):
    page_size = DEFAULT_PAGINATION_SIZE
    page_size_query_param = 'size'
    max_page_size = MAX_PAGINATION_SIZE
    last_page_strings = []


class ShareView(viewsets.GenericViewSet,
                mixins.CreateModelMixin):
    queryset = Share.objects.all()
    serializer_class = ShareSerializer

    def perform_create(self, serializer):
        """
        in case any share is repetitious, regardles of being valid or invalid
        we must change the status to repetitious (status=4).
        :param serializer:
        :return:
        """
        miner = Miner.objects.filter(public_key=serializer.validated_data['miner'].lower()).first()
        if not miner:
            logger.info('Miner does not exist, creating one with pk {}'.format(
                serializer.validated_data['miner'].lower()))
            miner = Miner.objects.create(public_key=serializer.validated_data['miner'].lower())
        _share = serializer.validated_data['share']
        _status = serializer.validated_data['status']
        rep_share = Share.objects.filter(share=_share)

        miner_address = Address.objects.get_or_create(address=serializer.validated_data.get('miner_address'),
                                                      address_miner=miner, category='miner')[0]
        lock_address = Address.objects.get_or_create(address=serializer.validated_data.get('lock_address'),
                                                     address_miner=miner, category='lock')[0]
        withdraw_address = Address.objects.get_or_create(address=serializer.validated_data.get('withdraw_address'),
                                                         address_miner=miner, category='withdraw')[0]
        # updating updated_at field
        miner_address.save()
        lock_address.save()
        withdraw_address.save()

        if not rep_share:
            logger.info('New share, saving.')
            serializer.save(miner=miner, miner_address=miner_address,
                            lock_address=lock_address, withdraw_address=withdraw_address)
        else:
            logger.info('Repetitious share, saving.')
            serializer.save(status="repetitious", miner=miner, miner_address=miner_address,
                            lock_address=lock_address, withdraw_address=withdraw_address)
            _status = "repetitious"
        if _status == "solved":
            logger.info('Solved share, saving.')
            RewardAlgorithm.get_instance().perform_logic(Share.objects.get(share=_share, status="solved"))


class BalanceView(viewsets.GenericViewSet,
                  mixins.CreateModelMixin,
                  mixins.UpdateModelMixin,
                  mixins.ListModelMixin, ):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    pagination_class = CustomPagination

    def perform_create(self, serializer, *args, **kwargs):
        """
        the status of the API requests are 1 as default.
        we must change them to 3, the API is only called when
        we want to withdraw, the status of withdraw is 3
        :param serializer:
        :param args:
        :param kwargs:
        :return:
        """
        serializer.save(status="withdraw")


class ConfigurationViewSet(viewsets.GenericViewSet,
                           mixins.CreateModelMixin,
                           mixins.ListModelMixin):
    serializer_class = ConfigurationSerializer
    queryset = Configuration.objects.all()
    filter_backends = (filters.SearchFilter,)
    search_fields = ('key', 'value',)

    def perform_create(self, serializer, *args, **kwargs):
        """
        we override the perform_create to create a new configuration
        or update an existing configuration.
        :param serializer:
        :param args:
        :param kwargs:
        :return:
        """
        key = serializer.validated_data['key']
        value = serializer.validated_data['value']
        configurations = Configuration.objects.filter(key=key)
        val_type = CONFIGURATION_KEY_TO_TYPE[key]
        try:
            locate(val_type)(value)

        except:
            return

        if not configurations:
            logger.info('Saving new configuration.')
            serializer.save()
        else:
            logger.info('Updating configuration')
            configuration = Configuration.objects.get(key=key)
            configuration.value = value
            configuration.save()

    def list(self, request, *args, **kwargs):
        """
        overrides list method to return list of key: value instead of list of dicts
        """
        config = dict(CONFIGURATION_DEFAULT_KEY_VALUE)
        for conf in Configuration.objects.all():
            val_type = CONFIGURATION_KEY_TO_TYPE[conf.key]
            config[conf.key] = locate(val_type)(conf.value)

        return Response(config, status=status.HTTP_200_OK)


class DashboardView(viewsets.GenericViewSet,
                    mixins.ListModelMixin,
                    mixins.RetrieveModelMixin):

    def get_queryset(self):
        return None

    def list(self, request, *args, **kwargs):
        return self.get_response(request)

    def retrieve(self, request, *args, **kwargs):
        return self.get_response(request, kwargs.get("pk").lower())

    def get_response(self, request, pk=None):
        """
        Returns information for this round of shares.
        In the response, there is total shares count of this round and information about each miner balances.
        If the pk is set in url parameters, then information is just about that miner.
        :param request:
        :param pk:
        :return:
        """
        # Timestamp of last solved share
        times = Share.objects.all().aggregate(
            last_solved=Max('created_at', filter=Q(status='solved')),
            first_share=Min('created_at')
        )
        last_solved_timestamp = times.get("last_solved") or times.get("first_share") or datetime.now()
        # Set the response to be all miners or just one with specified pk
        miners = Miner.objects.filter(public_key=pk) if pk else Miner.objects

        # Total shares count of this round
        total_count = Share.objects.filter(created_at__gt=last_solved_timestamp).aggregate(
            valid=Count("id", filter=Q(status="valid")),
            invalid=Count("id", filter=Q(status__in=["invalid", "repetitious"]))
        )

        # Shares of this round and balances of user
        round_shares = miners.values('public_key').annotate(
            valid_shares=Count('id', filter=Q(share__created_at__gt=last_solved_timestamp, share__status="valid")),
            invalid_shares=Count('id', filter=Q(share__created_at__gt=last_solved_timestamp, share__status="invalid")),
            immature=Sum('share__balance__balance', filter=Q(share__balance__status="immature")),
            mature=Sum('share__balance__balance', filter=Q(share__balance__status="mature")),
            withdraw=Sum('share__balance__balance', filter=Q(share__balance__status="withdraw")),
        )
        miners_hash_rate = compute_hash_rate(timezone.now() - timedelta(seconds=Configuration.objects.PERIOD_TIME))
        logger.info('Current hash rate: {}'.format(miners_hash_rate))
        miners_info = dict()
        for item in round_shares:
            miners_info[item['public_key']] = dict()
            miners_info[item['public_key']]['round_valid_shares'] = item['valid_shares']
            miners_info[item['public_key']]['round_invalid_shares'] = item['invalid_shares']
            miners_info[item['public_key']]['immature'] = item['immature'] if item['immature'] else 0
            miners_info[item['public_key']]['mature'] = item['mature'] if item['mature'] else 0
            miners_info[item['public_key']]['withdraw'] = item['withdraw'] if item['withdraw'] else 0
            if item['public_key'] in miners_hash_rate:
                miners_info[item['public_key']]['hash_rate'] = miners_hash_rate[item['public_key']]['hash_rate']

        response = {
            'round_valid_shares': total_count.get("valid", 0),
            'round_invalid_shares': total_count.get("invalid", 0),
            'timestamp': last_solved_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'hash_rate': miners_hash_rate['total_hash_rate'],
            'users': miners_info
        }
        return Response(response)


class BlockView(viewsets.GenericViewSet,
                mixins.ListModelMixin):
    pagination_class = CustomPagination

    def get_queryset(self):
        """
        get remote and process it
        :return:
        """

        return BlockDataIterable(self.request)

    def list(self, request, *args, **kwargs):
        """
        return a paginated list of block elements
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        queryset = self.get_queryset()
        if isinstance(queryset, dict):
            return Response(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(queryset[:])


class MinerView(viewsets.GenericViewSet, mixins.UpdateModelMixin):
    model = Miner
    serializer_class = MinerSerializer
    queryset = Miner.objects.all()
    lookup_field = 'public_key'

    @action(detail=True, methods=['post'])
    def set_address(self, request, public_key=None):
        """
        miner can set it's preferred address
        """
        miner = self.get_object()
        address = request.data.get('address', None)
        if address is None:
            return Response({'message': 'address field must be present.'}, status=status.HTTP_400_BAD_REQUEST)

        miner_address = Address.objects.filter(address_miner=miner, address=address).first()
        if miner_address is None:
            return Response({'message': "provided address is not present in miner's address list."},
                            status=status.HTTP_400_BAD_REQUEST)

        miner.selected_address = miner_address
        miner.save()
        return Response({'message': 'address successfully was set for miner.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], name='withdrawal')
    def withdraw(self, request, public_key=None):
        """
        this action specifies withdraw action of the miner.
        runs a celery task in case that the request is valid
        """
        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        miner = self.get_object()
        # balances with "mature", "withdraw" and "pending_withdrawal" status
        total = Balance.objects.filter(miner=miner, status__in=['mature', 'withdraw', 'pending_withdrawal']).aggregate(Sum('balance')).get('balance__sum')

        requested_amount = request.data.get('withdraw_amount')
        try:
            requested_amount = int(requested_amount)
            if requested_amount <= 0:
                raise Exception()

        except:
            return Response({'message': 'withdraw_amount field is not valid.'}, status=status.HTTP_400_BAD_REQUEST)

        if requested_amount < TRANSACTION_FEE:
            return Response(
                {'message': 'withdraw_amount must be bigger than transaction fee: {}.'.format(TRANSACTION_FEE)},
                status=status.HTTP_400_BAD_REQUEST)

        if requested_amount > total:
            return Response({'message': 'withdraw_amount is bigger than total balance.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # creating a pending_withdrawal status
        balance = Balance.objects.create(miner=miner, balance=-requested_amount, status="pending_withdrawal")
        generate_and_send_transaction.delay([(miner.public_key, requested_amount, balance.pk)],
                                            subtract_fee=True)
        return Response({'message': 'withdrawal was successful.',
                         'data': {'balance': total - requested_amount}}, status=status.HTTP_200_OK)
