import logging
from datetime import datetime, timedelta
from pydoc import locate
from urllib.parse import urljoin
import json

import django_filters as filters_rest
import requests
from django.conf import settings
from django.db.models import Q, Count, Sum, Max, Min
from django.db.utils import DataError
from django.http import QueryDict
from django.utils import timezone
from django.utils.timezone import get_current_timezone
from rest_framework import filters
from rest_framework import viewsets, mixins, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from ErgoAccounting.settings import TOTAL_PERIOD_HASH_RATE, PERIOD_DIAGRAM, DEFAULT_STOP_TIME_STAMP_DIAGRAM, \
    LIMIT_NUMBER_CHUNK_DIAGRAM, NUMBER_OF_LAST_INCOME, PERIOD_ACTIVE_MINERS_COUNT, \
    TOTAL_PERIOD_COUNT_SHARE, QR_CONFIG, DEVICE_CONFIG
from core.authentication import CustomPermission, ReadOnlyCustomPermission, ExpireTokenAuthentication
from core.models import Share, Miner, Balance, Configuration, CONFIGURATION_DEFAULT_KEY_VALUE, \
    CONFIGURATION_KEY_TO_TYPE, Address, ExtraInfo, TokenAuth as Token
from core.serializers import ShareSerializer, BalanceSerializer, MinerSerializer, ConfigurationSerializer, \
    ErgoAuthTokenSerializer, TOTPDeviceSerializer, UIDataSerializer, SupportSerializer
from core.tasks import generate_and_send_transaction, send_support_email
from core.utils import RewardAlgorithm, BlockDataIterable
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
import qrcode
import base64
from io import BytesIO
import os

logger = logging.getLogger(__name__)

ERGO_EXPLORER_ADDRESS = getattr(settings, "ERGO_EXPLORER_ADDRESS")
MAX_PAGINATION_SIZE = getattr(settings, "MAX_PAGINATION_SIZE")
DEFAULT_PAGINATION_SIZE = getattr(settings, "DEFAULT_PAGINATION_SIZE")
RECEIVERS_EMAIL_ADDRESS = getattr(settings, "RECEIVERS_EMAIL_ADDRESS")
SENDER_EMAIL_ADDRESS = getattr(settings, "SENDER_EMAIL_ADDRESS")


class CustomPagination(PageNumberPagination):
    page_size = DEFAULT_PAGINATION_SIZE
    page_size_query_param = 'size'
    max_page_size = MAX_PAGINATION_SIZE
    last_page_strings = []


class CustomPaginationLimitOffset(LimitOffsetPagination):
    default_limit = DEFAULT_PAGINATION_SIZE
    max_limit = MAX_PAGINATION_SIZE


class ShareView(viewsets.GenericViewSet,
                mixins.CreateModelMixin):
    authentication_classes = [SessionAuthentication, ExpireTokenAuthentication]
    permission_classes = [CustomPermission]
    queryset = Share.objects.all()
    serializer_class = ShareSerializer

    def perform_create(self, serializer):
        """
        TODO: Remove params lock_address and withdraw_address from scenario.
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

        if not rep_share:
            logger.info('New share, saving.')
            if _status in ["solved", "valid"]:
                miner_address, miner_created = Address.objects.get_or_create(
                    address=serializer.validated_data.get('miner_address'),
                    address_miner=miner, category='miner'
                )
                # updating updated_at field
                miner_address.save()
                # Check if miner_address already existed, ignore create lock_address, withdraw_address.
                if miner_created:
                    lock_address, lock_created = \
                        Address.objects.get_or_create(address=serializer.validated_data.get('lock_address'),
                                                      address_miner=miner,
                                                      category='lock')
                    # updating updated_at field
                    lock_address.save()
                    # Check if lock_address already existed, ignore create withdraw_address.
                    if lock_created:
                        withdraw_address, withdraw_created = \
                            Address.objects.get_or_create(address=serializer.validated_data.get('withdraw_address'),
                                                          address_miner=miner,
                                                          category='withdraw')
                        # updating updated_at field
                        withdraw_address.save()
                        serializer.save(miner=miner, withdraw_address=withdraw_address, miner_address=miner_address,
                                        lock_address=lock_address)
                    else:
                        serializer.save(miner=miner, withdraw_address=None, miner_address=miner_address,
                                        lock_address=lock_address)
                else:
                    serializer.save(miner=miner, withdraw_address=None, miner_address=miner_address, lock_address=None)

            else:
                serializer.save(miner=miner, withdraw_address=None, miner_address=None, lock_address=None)

        else:
            logger.info('Repetitious share, saving.')
            if _status != 'invalid':
                miner_address, miner_created = Address.objects.get_or_create(
                    address=serializer.validated_data.get('miner_address'), address_miner=miner, category='miner')
                # updating updated_at field
                miner_address.save()
                serializer.save(
                    status="repetitious", miner=miner, withdraw_address=None, miner_address=miner_address,
                    lock_address=None
                )
            else:
                serializer.save(
                    status="repetitious", miner=miner, withdraw_address=None, miner_address=None, lock_address=None
                )
            _status = "repetitious"
        if _status == "solved":
            logger.info('Solved share, saving.')
            RewardAlgorithm.get_instance().perform_logic(Share.objects.get(share=_share, status="solved"))


class BalanceView(viewsets.GenericViewSet,
                  mixins.CreateModelMixin,
                  mixins.UpdateModelMixin,
                  mixins.ListModelMixin):
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
    authentication_classes = [SessionAuthentication, ExpireTokenAuthentication]
    permission_classes = [CustomPermission]
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
        if serializer.is_valid():
            serializer.create(serializer.validated_data)

    @action(detail=False, methods=['POST'], name='batch_create')
    def batch_create(self, request):
        """
        this method creates or updates configuration with batch request like following:
        {
            "x": "y",
            "a": "b
        }
        """
        confs = []
        for key, value in request.data.items():
            confs.append({'key': key, 'value': value})

        serializer = self.get_serializer(data=confs, many=True)
        if serializer.is_valid():
            serializer.save()
            return Response(request.data, status=status.HTTP_200_OK)

        return Response({'message': 'Some fields are not valid.', "errors": serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST)

    def list(self, request, *args, **kwargs):
        """
        overrides list method to return list of key: value instead of list of dicts
        """
        config = dict(CONFIGURATION_DEFAULT_KEY_VALUE)
        for conf in Configuration.objects.all():
            val_type = CONFIGURATION_KEY_TO_TYPE[conf.key]
            config[conf.key] = locate(val_type)(conf.value)

        return Response(config, status=status.HTTP_200_OK)


class UserApiViewSet(viewsets.GenericViewSet,
                     mixins.ListModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.RetrieveModelMixin):
    model = Miner
    queryset = Miner.objects.all()
    serializer_class = MinerSerializer

    def get_object(self):
        """
        get object from miner table
        :return: miner input in url(public_key or address)
        """
        pk = self.kwargs.get('pk')
        miner = Miner.objects.filter(Q(public_key=pk.lower()) | Q(address__address=pk)).distinct()
        return miner.first()

    @action(detail=True, methods=['post'], name='withdrawal')
    def withdraw(self, request, pk=None):
        """
        this action specifies withdraw action of the miner.
        runs a celery task in case that the request is valid
        """
        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        miner = self.get_object()
        # balances with "mature", "withdraw" and "pending_withdrawal" status
        total = Balance.objects.filter(miner=miner, status__in=['mature', 'withdraw', 'pending_withdrawal']).aggregate(
            Sum('balance')).get('balance__sum')

        if total is None:
            total = 0

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

    def get_balance(self):
        """
        get balance and sort them
        :return:
        """
        self.pagination_class = CustomPaginationLimitOffset
        self.filter_backends = [filters.OrderingFilter]
        self.ordering_fields = ['date', 'amount']
        self.ordering = 'date'

        # Get object detail method call
        miner = self.get_object()
        query = self.request.query_params
        # Set timezone
        tz = get_current_timezone()
        # Set start period for get data from data_base if there is not start param set DEFAULT_START_PAYOUT
        start = int(query.get('start') or settings.DEFAULT_START_PAYOUT)
        # Rounding start time to first day
        start = int(timezone.datetime.fromtimestamp(start, tz=tz).replace(hour=0, minute=0, second=0).timestamp())
        # Set end period for get data from data_base if there is not stop param set time now
        stop = int(query.get('stop') or timezone.now().timestamp())
        # Rounding start time to end day
        stop = int(timezone.datetime.fromtimestamp(stop, tz=tz).replace(hour=23, minute=59, second=59).timestamp())
        # validate ordering params
        ordering_fields = self.ordering_fields
        ordering_fields = ordering_fields + ['-' + i for i in ordering_fields]
        field = query.get('ordering')
        order = field if field in ordering_fields else self.ordering
        # send query for get amount of payout for a miner in one day
        balances = Balance.objects.filter(
            Q(miner=miner) &
            Q(created_at__gte=timezone.datetime.fromtimestamp(start, tz=tz)) &
            Q(created_at__lte=timezone.datetime.fromtimestamp(stop, tz=tz)) &
            Q(status='withdraw')
        ).extra(
            select={
                'date': 'EXTRACT(epoch from "core_balance"."created_at"::DATE)'
            }
        ).values('date', 'max_height').annotate(amount=Sum('balance')).order_by(order)
        balances = list(balances)

        # Create response
        response = []
        for balance in balances:
            response.append({
                "date": int(balance['date']),
                "tx": None,
                "height": int(balance['max_height']),
                "amount": int(balance['amount'])
            })
        return response

    @action(detail=True, name='income')
    def income(self, request, *args, **kwargs):
        """
        return last 1000 income of user as list
        """
        miner = self.get_object()
        share = Share.objects.filter(status='solved').filter(
            Q(miner=miner) &
            Q(balance__status='immature') |
            Q(balance__status='mature')
        ).values('block_height').annotate(balance=Sum('balance__balance'))[:NUMBER_OF_LAST_INCOME]
        logger.debug("Get income for miner {}".format(miner.public_key if miner else ''))
        response = [{'height': obj['block_height'], 'balance': obj['balance']} for obj in share]
        return Response(response)

    @action(detail=True, name='payout')
    def payout(self, request, *args, **kwargs):
        """
        Get amount of payout for a miner in every day between timestamp
        """
        queryset = self.get_balance()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(queryset[:])

    @action(detail=True, name='hash_rate')
    def hash_rate(self, request, *args, **kwargs):
        """
        Returns Average and current hash_rate
        """
        miner = self.get_object()
        # Get query_params
        query = self.request.query_params
        # Set start period for get data from data_base if there is not start param set time now mines
        # DEFAULT_STOP_TIME_STAMP_DIAGRAM
        start = int(query.get('start') or timezone.now().timestamp() - DEFAULT_STOP_TIME_STAMP_DIAGRAM)
        start_frame = int(start / PERIOD_DIAGRAM)
        # Set end period for get data from data_base if there is not stop param set time now
        stop = int(query.get('stop') or timezone.now().timestamp())
        # Check number of chunk should not bigger than LIMIT_NUMBER_CHUNK_DIAGRAM
        if (stop - start) / PERIOD_DIAGRAM >= LIMIT_NUMBER_CHUNK_DIAGRAM:
            stop = min(stop, start + (LIMIT_NUMBER_CHUNK_DIAGRAM * PERIOD_DIAGRAM))
        stop_frame = int(stop / PERIOD_DIAGRAM)
        prev_chunks = int(TOTAL_PERIOD_HASH_RATE / PERIOD_DIAGRAM)
        tz = get_current_timezone()
        logger.info('computing hash rate for pk: {}'.format(miner.public_key if miner else '--'))
        shares = Share.objects.filter(
            Q(miner=miner) &
            Q(created_at__gte=timezone.datetime.fromtimestamp(start - (prev_chunks + 1) * PERIOD_DIAGRAM, tz=tz)) &
            Q(created_at__lte=timezone.datetime.fromtimestamp(stop, tz=tz)) &
            Q(status__in=['valid', 'solved'])
        ).extra(
            select={
                'frame': 'Cast(EXTRACT(epoch from "core_share"."created_at")AS INTEGER) / {}'.format(
                    str(PERIOD_DIAGRAM)
                )
            }
        ).values('frame').annotate(sum=Sum('difficulty'))

        shares = list(shares)
        response = []
        chunk = []
        index = 0
        # Sum of all difficulty shares in the period
        sum_avg = 0
        # Calculate HashRate average and current
        for i in range(start_frame - prev_chunks, stop_frame + 1):
            if index < len(shares) and shares[index]['frame'] == i:
                val = shares[index]['sum'] / PERIOD_DIAGRAM
                index += 1
            else:
                val = 0
            sum_avg += val
            chunk.append(val)
            if i >= start_frame:
                sum_avg -= chunk.pop(0)
                response.append({
                    "timestamp": i * PERIOD_DIAGRAM,
                    "avg": int(sum_avg / prev_chunks) + 1,
                    "current": int(val) + 1
                })
        return Response(response)

    @action(detail=True, name='share')
    def share(self, request, *args, **kwargs):
        """
        return valid and invalid shares of a miner between 2 time stamp
        """
        miner = self.get_object()
        # Get query_params
        query = self.request.query_params
        # Set start period for get data from data_base if there is not start param set time now mines
        # DEFAULT_STOP_TIME_STAMP_DIAGRAM
        start = int(query.get('start') or timezone.now().timestamp() - DEFAULT_STOP_TIME_STAMP_DIAGRAM)
        start_frame = int(start / PERIOD_DIAGRAM)
        # Set end period for get data from data_base if there is not stop param set time now
        stop = int(query.get('stop') or timezone.now().timestamp())
        # Check number of chunk should not bigger than LIMIT_NUMBER_CHUNK_DIAGRAM
        if (stop - start) / PERIOD_DIAGRAM >= LIMIT_NUMBER_CHUNK_DIAGRAM:
            stop = min(stop, start + (LIMIT_NUMBER_CHUNK_DIAGRAM * PERIOD_DIAGRAM))
        stop_frame = int(stop / PERIOD_DIAGRAM)
        tz = get_current_timezone()
        logger.info('get shares valid and invalid for miner: {}'.format(miner.public_key if miner else ""))
        # Add share from table share and split with status 'valid', 'solved' and 'invalid', 'repetitious'
        shares = Share.objects.filter(
            Q(miner=miner) &
            Q(created_at__gte=timezone.datetime.fromtimestamp(start, tz=tz)) &
            Q(created_at__lte=timezone.datetime.fromtimestamp(stop, tz=tz))
        ).extra(
            select={
                'frame': 'Cast(EXTRACT(epoch from "core_share"."created_at")AS INTEGER) / {}'.format(
                    str(PERIOD_DIAGRAM)
                )
            }
        ).values('frame').annotate(
            valid=Count('id', filter=Q(status__in=['valid', 'solved'])),
            invalid=Count('id', filter=Q(status__in=['invalid', 'repetitious']))
        ).order_by('frame')
        shares = list(shares)
        response = []
        index = 0
        # Create response
        for i in range(start_frame, stop_frame + 1):
            if index < len(shares) and shares[index]['frame'] == i:
                valid = shares[index]['valid']
                invalid = shares[index]['invalid']
                index += 1
            else:
                valid = 0
                invalid = 0
            if i >= start_frame:
                response.append({
                    "date": i * PERIOD_DIAGRAM,
                    "valid": int(valid),
                    "invalid": int(invalid)
                })
        return Response(response)

    def list(self, request, *args, **kwargs):
        round_start = self.get_last_solved_timestamp()
        total_row = self.get_total_params(round_start)
        if not request.user.is_authenticated:
            return Response(total_row)
        total_row['users'] = self.get_user_params(round_start)
        return Response(total_row)

    def retrieve(self, request, *args, **kwargs):
        round_start = self.get_last_solved_timestamp()
        total_row = self.get_total_params(round_start)
        total_row['users'] = self.get_user_params(round_start, kwargs.get("pk"))
        return Response(total_row)

    def get_last_solved_timestamp(self):
        """
        return last solved share timestamp. if no solved share return first share time. otherwise return current datetime
        :return:
        """
        # Timestamp of last solved share
        times = Share.objects.all().aggregate(
            last_solved=Max('created_at', filter=Q(status='solved')),
            first_share=Min('created_at')
        )
        return times.get("last_solved") or times.get("first_share") or datetime.now()

    def get_total_params(self, round_start_time):
        """
        return a list contain overall parameters on pool.
        :param round_start_time: round start time
        :return: json contain overall parameters
        """
        # Total shares count of this round and sum of difficulty in different period
        total_count = Share.objects.aggregate(
            valid=Count("id", filter=Q(created_at__gt=round_start_time) & Q(status="valid")),
            invalid=Count("id", filter=Q(created_at__gt=round_start_time) & Q(status__in=["invalid", "repetitious"])),
            sum_period_diagram_difficulty=Sum('difficulty', filter=Q(
                created_at__gte=(timezone.now() - timedelta(seconds=PERIOD_DIAGRAM))
            ) & Q(
                status__in=['valid', 'solved']
            )),
            sum_total_difficulty=Sum('difficulty', filter=Q(
                created_at__gte=(timezone.now() - timedelta(seconds=TOTAL_PERIOD_HASH_RATE))
            ) & Q(
                status__in=['valid', 'solved']
            ))
        )
        return {
            'round_valid_shares': int(total_count.get("valid", 0)),
            'round_invalid_shares': int(total_count.get("invalid", 0)),
            'timestamp': round_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            "hash_rate": {
                # Hash-rate in period PERIOD_DIAGRAM
                "current": int((total_count.get("sum_period_diagram_difficulty") or 0) / PERIOD_DIAGRAM or 1),
                # Hash-rate in period TOTAL_PERIOD_HASH_RATE
                "avg": int((total_count.get("sum_total_difficulty") or 0) / TOTAL_PERIOD_HASH_RATE or 1)
            }
        }

    def get_user_params(self, round_start_time, user_pk=None):
        """
        get all parameters for specific user or all users
        :param round_start_time: start datetime for calculation
        :param user_pk: selected user pk or address. if empty response for all users returned
        :return:
        """
        # Set the response to be all miners or just one with specified public_key or address of miner
        miners = Miner.objects.filter(
            Q(public_key=user_pk) |
            Q(address__address=user_pk)
        ) if user_pk else Miner.objects

        # Shares of this round and balances of user
        total_balance = Miner.objects.filter(pk__in=miners.values('pk')).values('public_key').annotate(
            immature=Sum('balance__balance', filter=Q(balance__status="immature")),
            mature=Sum('balance__balance', filter=Q(balance__status="mature")),
            withdraw=Sum('balance__balance', filter=Q(balance__status="withdraw")),
        ).order_by('public_key')

        round_shares = Miner.objects.filter(pk__in=miners.values('pk')).values('public_key').annotate(
            valid_shares=Count('share__id', filter=Q(share__created_at__gt=round_start_time,
                                                     share__status__in=["solved", "valid"]), distinct=True),
            invalid_shares=Count('share__id', filter=Q(share__created_at__gt=round_start_time,
                                                       share__status__in=["repetitious", "invalid"]), distinct=True),
            sum_period_diagram_difficulty=Sum('share__difficulty', filter=Q(
                share__status__in=['valid', 'solved']
            ) & Q(
                share__created_at__gte=(timezone.now() - timedelta(seconds=PERIOD_DIAGRAM))
            )),
            sum_total_difficulty=Sum('share__difficulty', filter=Q(
                share__status__in=['valid', 'solved']
            ) & Q(
                share__created_at__gte=(timezone.now() - timedelta(seconds=TOTAL_PERIOD_HASH_RATE))
            ))
        ).order_by('public_key')

        round_share = round_shares.first() or {}
        logger.info('Get user params for miner: {}'.format(round_share.get('public_key') if user_pk else None))
        response = {}
        temp = {}
        for balance in total_balance:
            public_key = balance.pop('public_key')
            temp[public_key] = balance

        for share in round_shares:
            public_key = share.pop('public_key')
            if public_key not in temp.keys():
                temp[public_key] = {}
            temp[public_key].update(share)

        def convert_row(row_dict):
            return {
                "round_valid_shares": int(row_dict.get("valid_shares") or 0),
                "round_invalid_shares": int(row_dict.get("invalid_shares") or 0),
                "immature": int(row_dict.get("immature") or 0),
                "mature": int(row_dict.get("mature") or 0),
                "withdraw": int(row_dict.get("withdraw") or 0),
                "hash_rate": {
                    "current": int((row_dict.get("sum_period_diagram_difficulty") or 0) / PERIOD_DIAGRAM) or 1,
                    "avg": int((row_dict.get("sum_total_difficulty") or 0) / TOTAL_PERIOD_HASH_RATE) or 1
                }
            }

        if user_pk:
            response[user_pk] = convert_row(temp[list(temp.keys())[0]] if len(round_shares) > 0 else {})
        else:
            for item in temp:
                response[item] = convert_row(temp[item])
        return response


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


class InfoViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    View set for get information of pool and network
    """

    def list(self, request, *args, **kwargs):
        """
        :param request:
        :param args:
        :param kwargs:
        :return: {
                "hash_rate": {
                    "network": int,
                    "pool": int
                },
                "miners": int,
                "active_miners": int,
                "price": int,
                "blocks_in_hour": float
            }
        """
        # Calculate hash_rate of network with getting last block between now time and past PERIOD_DIAGRAM
        url = urljoin(ERGO_EXPLORER_ADDRESS, 'blocks')
        query = {
            'startDate': int(timezone.now().timestamp() - PERIOD_DIAGRAM) * 1000,
            'endDate': int(timezone.now().timestamp()) * 1000
        }
        try:
            data_explorer = requests.get(url, query)
            if not 200 <= data_explorer.status_code <= 299:
                raise requests.exceptions.RequestException(data_explorer.json())
        except requests.exceptions.RequestException as e:
            logger.error("Can not resolve response from Explorer")
            logger.error(e)
            return Response({'status': 'error', 'message': str(e)})
        items = data_explorer.json().get('items')
        difficulty_network = 0
        for item in items:
            difficulty_network += item.get('difficulty')
        # Calculate HashRate of pool
        pool_hash_rate = Share.objects.aggregate(
            sum_total_difficulty=Sum('difficulty', filter=Q(
                created_at__gte=(timezone.now() - timedelta(seconds=PERIOD_DIAGRAM))
            ) & Q(
                status__in=['valid', 'solved']
            )))
        # Number of miner in table Miner
        count_miner = Miner.objects.count()

        # Get blocks solved in past hour
        solution_count = Share.objects.filter(
            Q(created_at__gte=(timezone.now() - timedelta(seconds=TOTAL_PERIOD_COUNT_SHARE))) &
            Q(status='solved') &
            Q(transaction_valid=True)
        ).distinct().count()

        # Active Miner in past hour
        active_miners_count = Miner.objects.filter(
            minerip__updated_at__gte=(timezone.now() - timedelta(seconds=PERIOD_ACTIVE_MINERS_COUNT))
        ).distinct().count()
        # Set value of response

        price_btc = ExtraInfo.objects.filter(key='ERGO_PRICE_BTC').first()
        price_usd = ExtraInfo.objects.filter(key='ERGO_PRICE_USD').first()
        price_btc = None if price_btc is None else float(price_btc.value)
        price_usd = None if price_usd is None else float(price_usd.value)

        response = {
            "hash_rate": {
                "network": int(difficulty_network / PERIOD_DIAGRAM) + 1,
                "pool": int((pool_hash_rate.get("sum_total_difficulty") or 0) / PERIOD_DIAGRAM) or 1
            },
            "miners": count_miner,
            "active_miners": active_miners_count,
            "price": {
                'btc': price_btc,
                'usd': price_usd
            },
            "blocks_in_hour": solution_count / (TOTAL_PERIOD_COUNT_SHARE / 3600)
        }

        return Response(response)


class UserFilter(filters_rest.FilterSet):
    """
    For set filter of range on users
    TODO: implement filter on status field
    """
    STATUS_CHOICES = (
        ('active', 'active'),
        ('inactive', 'inactive')
    )
    valid_shares = filters_rest.RangeFilter()
    sum_period_diagram_difficulty = filters_rest.RangeFilter()
    # status = filters_rest.ChoiceFilter(choices=STATUS_CHOICES)

    class Meta:
        fields = ["valid_shares", "sum_period_diagram_difficulty"]


class AdministratorUserViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    This viewSet use for show information of miner to admin
    """
    queryset = Miner.objects.all()
    pagination_class = CustomPaginationLimitOffset
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['user', 'hash_rate', 'valid_shares', 'invalid_shares', 'last_ip', 'status']
    original_ordering = {
        'user': 'public_key',
        '-user': '-public_key',
        'last_ip': 'ip',
        '-last_ip': '-ip',
        'hash_rate': 'sum_period_diagram_difficulty',
        '-hash_rate': '-sum_period_diagram_difficulty'
    }
    ordering = 'user'

    # For session authentication
    authentication_classes = [SessionAuthentication, ExpireTokenAuthentication]
    # For token authentication
    permission_classes = [CustomPermission]

    def get_miners(self):
        """
        Function for get miners from data_base
        :return: miners
        """
        # validate ordering params
        ordering_fields = self.ordering_fields
        ordering_fields = ordering_fields + ['-' + i for i in ordering_fields]
        field = self.request.query_params.get('ordering')
        order = field if field in ordering_fields else self.ordering
        # change query params to original ordering field
        if order in self.original_ordering:
            order = self.original_ordering[order]

        miners = Miner.objects.values('public_key', 'ip').annotate(
            sum_period_diagram_difficulty=Sum('share__difficulty',
                                              filter=Q(
                                                  share__status__in=['valid', 'solved']
                                              ) & Q(
                                                  share__created_at__gte=(
                                                          timezone.now() - timedelta(seconds=PERIOD_DIAGRAM)))),
            valid_shares=Count('share__id', filter=Q(share__status__in=["solved", "valid"]), distinct=True),
            invalid_shares=Count('share__id', filter=Q(share__status__in=["repetitious", "invalid"]), distinct=True
                                 )).order_by(order)
        # change hash_rate params to sum_period_diagram_difficulty_min for set query and
        # multiplication in PERIOD_DIAGRAM for set range filter on hash_rate
        request_get = dict(self.request.GET)
        if 'hash_rate_min' in request_get:
            request_get['sum_period_diagram_difficulty_min'] = str(int(request_get['hash_rate_min'][0]) * PERIOD_DIAGRAM)
            request_get.pop('hash_rate_min')
        if 'hash_rate_max' in request_get:
            request_get['sum_period_diagram_difficulty_max'] = str(int(request_get['hash_rate_max'][0]) * PERIOD_DIAGRAM)
            request_get.pop('hash_rate_max')
        # convert dict to query_dict
        data_request = {}
        for i in request_get:
            data_request.update({i: request_get[i][0]} if isinstance(request_get[i], list) else {i: request_get[i]})
        data_request_query = QueryDict('', mutable=True)
        data_request_query.update(data_request)
        # set filters on query except ip filter
        miners = UserFilter(data_request_query, queryset=miners).qs
        # set range filter on last_ip
        if 'last_ip_min' in data_request_query and 'last_ip_max' in data_request_query:
            miners = miners.filter(Q(ip__range=[data_request_query['last_ip_min'], data_request_query['last_ip_max']]))
        elif 'last_ip_min' in data_request_query:
            miners = miners.filter(Q(ip__gte=data_request_query['last_ip_min']))
        elif 'last_ip_max' in data_request_query:
            miners = miners.filter(Q(ip__lte=data_request_query['last_ip_max']))

        return miners

    def list(self, request, *args, **kwargs):

        def convert_row(row_dict):
            """
            Function for create response
            :param row_dict: dictionary of data
            :return: template of data
            """
            return {
                "user": str(row_dict.get("public_key")),
                "hash_rate": int((row_dict.get("sum_period_diagram_difficulty") or 0) / PERIOD_DIAGRAM) or 1,
                "valid_shares": int(row_dict.get("valid_shares") or 0),
                "invalid_shares": int(row_dict.get("invalid_shares") or 0),
                "last_ip": row_dict.get("ip"),
                "status": "active"
            }
        # set pagination on response
        try:
            page = self.paginate_queryset(self.get_miners())
        except DataError as e:
            logging.info("Filter range for last_ip is invalid.")
            logging.info(e)
            raise ValidationError("Filter range for last_ip is invalid.")
        response = []
        if page is not None:
            for item in page:
                response.append(convert_row(item))
            return self.get_paginated_response(response)
        return Response(response)


class ErgoAuthToken(viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.ListModelMixin):
    serializer_class = ErgoAuthTokenSerializer
    queryset = Token.objects.all()
    DEFAULT_TOKEN_EXPIRE = getattr(settings, "DEFAULT_TOKEN_EXPIRE")

    def list(self, request, *args, **kwargs):
        """
        this api view return all required configuration to authenticate to system
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        return Response({"site_key": settings.RECAPTCHA_SITE_KEY})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        # Checking state that the token of user expired and generate new token for this user.
        if not created:
            if not (timezone.now() - timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['PER_USE'])) < token.last_use or\
                    not (timezone.now() - timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['TOTAL'])) < token.created:
                token.delete()
                token = Token.objects.create(user=user)
        headers = self.get_success_headers(serializer.data)
        return Response({'token': token.key}, status=status.HTTP_201_CREATED, headers=headers)


class TOTPDeviceViewSet(viewsets.GenericViewSet, mixins.CreateModelMixin,):
    serializer_class = TOTPDeviceSerializer
    queryset = TOTPDevice.objects.all()
    # For session authentication
    authentication_classes = [ExpireTokenAuthentication]
    # For token authentication
    permission_classes = [CustomPermission]

    @staticmethod
    def get_qr_code(device_url):
        """
        Create QR code base64 from otp-url
        """
        qr = qrcode.QRCode(version=QR_CONFIG.get('QR_VERSION'), error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=QR_CONFIG.get('QR_BOX_SIZE'), border=QR_CONFIG.get('QR_BORDER'))
        qr.add_data(device_url)
        qr.make(fit=True)
        img = qr.make_image()
        output = BytesIO()
        img.save(output)
        qr_data = output.getvalue()
        output.close()
        return base64.b64encode(qr_data).decode('ascii')

    def create(self, request, *args, **kwargs):
        """
        Create or reload new device for user.
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        device_config = DEVICE_CONFIG.copy()
        device_config.update({
            'user': request.user,
            'name': request.user.username,
            'confirmed': True
        })
        # TODO: It is possible for AnonymousUser to get an exception because permission_classes set CustomPermission.
        # Create new device totp if not exist
        device, flag = TOTPDevice.objects.update_or_create(**device_config)
        # if device for this user exist generate new secret key and update device
        if not flag:
            device.key = random_hex(20)
            device.save()
        return Response({'qrcode': self.get_qr_code(device.config_url)}, status=status.HTTP_201_CREATED)


class UIDataViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.CreateModelMixin):
    serializer_class = UIDataSerializer
    # For session authentication
    authentication_classes = [ExpireTokenAuthentication]
    # For token authentication
    permission_classes = [ReadOnlyCustomPermission]

    DEFAULT_UI_PREFIX_DIRECTORY = getattr(settings, 'DEFAULT_UI_PREFIX_DIRECTORY')

    def perform_authentication(self, request):
        if request.method not in SAFE_METHODS:
            super(UIDataViewSet, self).perform_authentication(request)

    def get_queryset(self):
        return None

    def list(self, request, *args, **kwargs):
        """
        If exist a file with name last prefix in URL, returns them.
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        # get the full path
        path = self.request.parser_context.get('kwargs').get('url')
        # split / if exist end of path
        dir = os.path.dirname(path)
        # get json from file
        try:
            with open(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, path), "r") as read_file:
                json_data = json.load(read_file)
        except FileNotFoundError:
            logger.error("no such file or directory in path {}".format(
                os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, path))
            )
            return Response({'error': 'No such file or directory !'}, status=status.HTTP_404_NOT_FOUND)
        except NotADirectoryError:
            logger.error("this path is wrong {}".format(
                os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, path))
            )
            return Response({'error': 'This path is wrong.'}, status=status.HTTP_400_BAD_REQUEST)
        except IsADirectoryError:
            logger.error("this path is wrong because exist a directory with same name in path {}".format(
                os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, dir))
            )
            return Response({
                'error': 'This path is wrong because exist a directory with same name in this path.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except json.JSONDecodeError as e:
            logger.error("can't decode json in path {}". format(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, dir)))
            logger.error(e)
            return Response({'error': 'Data was corrupted !'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(json_data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """
        create directory and file also write data in file
        last prefix in url is name file.
        Note: the data input should be structure of JSON for example must use double-quote not quote.
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # get the full path
        path = self.request.parser_context.get('kwargs').get('url')
        # split / if exist end of path
        dir = os.path.dirname(path)
        # Create directory
        try:
            os.makedirs(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, dir), mode=0o750, exist_ok=True)
        except OSError as e:
            logger.error("Creating a directory for path {} give a problem ".format(
                os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, dir))
            )
            logger.error(e)
            return Response({
                'error': 'Creating a directory for this path give a problem !!'
            }, status=status.HTTP_400_BAD_REQUEST)
        # Write data in file
        try:
            with open(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, path), 'w') as outfile:
                json.dump(serializer.data['data'], outfile)
        except IsADirectoryError:
            logger.error("this path is wrong because exist a directory with same name in path {}".format(
                os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, dir))
            )
            return Response({
                'error': 'This path is wrong because exist a directory with same name in this path.'
            }, status=status.HTTP_400_BAD_REQUEST)

        headers = self.get_success_headers(serializer.data)
        return Response({'reason': 'Saved data!'}, status=status.HTTP_201_CREATED, headers=headers)


class SupportViewSet(viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.ListModelMixin):
    """
    a API for send information of support form to admin system email.
    """
    serializer_class = SupportSerializer

    def list(self, request, *args, **kwargs):
        """
        return site_key for RECAPTCHA.
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        return Response({"site_key": settings.RECAPTCHA_SITE_KEY})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        headers = self.get_success_headers(serializer.data)
        data = serializer.data
        # Create message for send to admin system
        message = "Name: %s\nEmail: %s\nMessage: %s" % (data.get('name'), data.get('email'), data.get('message'))
        send_support_email.delay(data.get('subject', 'No Subject'), message)
        return Response({'status': ['ok']}, status=status.HTTP_200_OK, headers=headers)
