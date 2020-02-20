import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin
from pydoc import locate
from django.utils.timezone import get_current_timezone
import requests

from django.conf import settings
from django.db.models import Q, Count, Sum, Max, Min
from django.utils import timezone
from rest_framework import filters
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.response import Response

from ErgoAccounting.settings import TOTAL_PERIOD_HASH_RATE, PERIOD_DIAGRAM, DEFAULT_STOP_TIME_STAMP_DIAGRAM, \
    LIMIT_NUMBER_CHUNK_DIAGRAM, API_KEY, NUMBER_OF_LAST_INCOME, DEFAULT_START_PAYOUT
from core.models import Share, Miner, Balance, Configuration, CONFIGURATION_DEFAULT_KEY_VALUE, \
    CONFIGURATION_KEY_TO_TYPE, Address, MinerIP, ExtraInfo, EXTRA_INFO_KEY_TYPE
from core.serializers import ShareSerializer, BalanceSerializer, MinerSerializer, ConfigurationSerializer
from core.tasks import generate_and_send_transaction
from core.utils import compute_hash_rate, RewardAlgorithm, BlockDataIterable, node_request

logger = logging.getLogger(__name__)

ERGO_EXPLORER_ADDRESS = getattr(settings, "ERGO_EXPLORER_ADDRESS")
MAX_PAGINATION_SIZE = getattr(settings, "MAX_PAGINATION_SIZE")
DEFAULT_PAGINATION_SIZE = getattr(settings, "DEFAULT_PAGINATION_SIZE")


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

        if not rep_share:
            logger.info('New share, saving.')
            if _status in ["solved", "valid"]:
                miner_address = Address.objects.get_or_create(address=serializer.validated_data.get('miner_address'),
                                                              address_miner=miner, category='miner')[0]
                lock_address = Address.objects.get_or_create(address=serializer.validated_data.get('lock_address'),
                                                             address_miner=miner, category='lock')[0]
                withdraw_address = \
                    Address.objects.get_or_create(address=serializer.validated_data.get('withdraw_address'),
                                                  address_miner=miner, category='withdraw')[0]
                # updating updated_at field
                miner_address.save()
                lock_address.save()
                withdraw_address.save()
                serializer.save(miner=miner, withdraw_address=withdraw_address, miner_address=miner_address,
                                lock_address=lock_address)

            else:
                serializer.save(miner=miner, withdraw_address=None, miner_address=None, lock_address=None)

        else:
            logger.info('Repetitious share, saving.')
            serializer.save(status="repetitious", miner=miner)
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


class UserApiViewSet(viewsets.GenericViewSet,
                     mixins.ListModelMixin,
                     mixins.RetrieveModelMixin):
    model = Miner
    queryset = Miner.objects.all()

    def get_object(self):
        """
        get object from miner table
        :return: miner input in url(public_key or address)
        """
        pk = self.kwargs.get('pk')
        miner = Miner.objects.filter(Q(public_key=pk) | Q(address__address=pk)).distinct()
        return miner

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
        miner = self.get_object().first()
        query = self.request.query_params
        # Set timezone
        tz = get_current_timezone()
        # Set start period for get data from data_base if there is not start param set DEFAULT_START_PAYOUT
        start = int(query.get('start') or DEFAULT_START_PAYOUT)
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
        ).values('date').annotate(amount=Sum('balance')).order_by(order)
        balances = list(balances)

        # Create response
        response = []
        for balance in balances:
            response.append({
                "date": int(balance['date']),
                "tx": None,
                "height": None,
                "amount": int(balance['amount'])
            })
        return response

    @action(detail=True, name='income')
    def income(self, request, *args, **kwargs):
        """
        return last 1000 income of user as list
        """
        miner = self.get_object().first()
        share = Share.objects.filter(status='solved').filter(
            Q(miner=miner) &
            Q(balance__status='immature') |
            Q(balance__status='mature')
        ).values('block_height').annotate(balance=Sum('balance__balance'))[:NUMBER_OF_LAST_INCOME]
        logger.debug("Get income for miner {}".format(miner.public_key))
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
        miner = self.get_object().first()
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
        logger.info('computing hash rate for pk: {}'.format(miner.public_key))
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
                    "avg": int(sum_avg / prev_chunks),
                    "current": int(val)
                })
        return Response(response)

    @action(detail=True, name='share')
    def share(self, request, *args, **kwargs):
        """
        return valid and invalid shares of a miner between 2 time stamp
        """
        miner = self.get_object().first()
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
        logger.info('get shares valid and invalid for miner: {}'.format(miner.public_key))
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
        # Total shares count of this round
        total_count = Share.objects.filter(created_at__gt=round_start_time).aggregate(
            valid=Count("id", filter=Q(status="valid")),
            invalid=Count("id", filter=Q(status__in=["invalid", "repetitious"]))
        )
        miners_hash_rate = compute_hash_rate(timezone.now() - timedelta(seconds=Configuration.objects.PERIOD_TIME))
        return {
            'round_valid_shares': int(total_count.get("valid", 0)),
            'round_invalid_shares': int(total_count.get("invalid", 0)),
            'timestamp': round_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'hash_rate': int(miners_hash_rate.get('total_hash_rate', 1)),
        }

    def get_user_params(self, round_start_time, user_pk=None):
        """
        get all parameters for specific user or all users
        :param round_start_time: start datetime for calculation
        :param user_pk: selected user pk or address. if empty response for all users returned
        :return:
        """
        request = self.request
        # Set the response to be all miners or just one with specified public_key or address of miner
        miners = Miner.objects.filter(
            Q(public_key=user_pk) |
            Q(address__address=user_pk)
        ) if user_pk else Miner.objects

        # Shares of this round and balances of user
        round_shares = Miner.objects.filter(pk__in=miners.values('pk')).values('public_key').annotate(
            valid_shares=Count('id', filter=Q(share__created_at__gt=round_start_time, share__status="valid")),
            invalid_shares=Count('id', filter=Q(share__created_at__gt=round_start_time, share__status="invalid")),
            immature=Sum('share__balance__balance', filter=Q(share__balance__status="immature")),
            mature=Sum('share__balance__balance', filter=Q(share__balance__status="mature")),
            withdraw=Sum('share__balance__balance', filter=Q(share__balance__status="withdraw")),
        )
        round_share = round_shares.first() or {}
        public_key_hash_rate = round_share.get('public_key') if user_pk else None
        miners_hash_rate = compute_hash_rate(
            timezone.now() - timedelta(seconds=Configuration.objects.PERIOD_TIME),
            pk=public_key_hash_rate
        )
        logger.info('Current hash rate: {}'.format(miners_hash_rate))
        response = {}

        def convert_row(row_dict):
            return {
                "round_valid_shares": int(row_dict.get("valid_shares") or 0),
                "round_invalid_shares": int(row_dict.get("invalid_shares") or 0),
                "immature": int(row_dict.get("immature") or 0),
                "mature": int(row_dict.get("mature") or 0),
                "withdraw": int(row_dict.get("withdraw") or 0),
                "hash_rate": int(miners_hash_rate.get(row_dict.get("public_key"), {}).get("hash_rate") or 1),
            }
        if user_pk:
            response[user_pk] = convert_row(round_shares[0] if len(round_shares) > 0 else {})
        else:
            for item in round_shares:
                response[item.get("public_key")] = convert_row(item)
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
        total = Balance.objects.filter(miner=miner, status__in=['mature', 'withdraw', 'pending_withdrawal']).aggregate(
            Sum('balance')).get('balance__sum')

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
        pool_hash_rate = compute_hash_rate(timezone.now() - timedelta(seconds=PERIOD_DIAGRAM))
        # Number of miner in table Miner
        count_miner = Miner.objects.count()
        # Get blocks solved in past hour
        shares = Share.objects.filter(
            Q(created_at__range=(timezone.now() - timedelta(seconds=3600), timezone.now())) &
            Q(status='solved')
        ).values('transaction_id')
        # Check should be there is transaction_id in the wallet
        count = 0
        for share in shares:
            data_node = node_request('wallet/transactionById?id={}'.format(share['transaction_id']),
                                     {
                                         'accept': 'application/json',
                                         'content-type': 'application/json',
                                         'api_key': API_KEY
                                     })
            if data_node['status'] == 'success':
                count += 1
            else:
                logger.debug("response of node api 'wallet/transactionById' {}".format(data_node['response']))
        # Active Miner in past hour
        active_miners_count = Miner.objects.filter(
            minerip__updated_at__range=(timezone.now() - timedelta(seconds=3600), timezone.now())
        ).distinct().count()
        # Set value of response

        price_btc = ExtraInfo.objects.filter(key='ERGO_PRICE_BTC').first()
        price_usd = ExtraInfo.objects.filter(key='ERGO_PRICE_USD').first()
        price_btc = None if price_btc is None else float(price_btc.value)
        price_usd = None if price_usd is None else float(price_usd.value)

        response = {
            "hash_rate": {
                "network": int(difficulty_network/PERIOD_DIAGRAM) + 1,
                "pool": pool_hash_rate['total_hash_rate']
            },
            "miners": count_miner,
            "active_miners": active_miners_count,
            "price": {
                'btc': price_btc,
                'usd': price_usd
            },
            "blocks_in_hour": count / 3600
        }

        return Response(response)

