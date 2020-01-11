from django.db.models import Q, Count, Sum, Max, Min
from datetime import datetime, timedelta
from rest_framework import filters
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from django.utils import timezone
from urllib.parse import urljoin, urlencode, urlparse, parse_qsl, urlunparse
import requests
import logging
from django.conf import settings
from core.utils import compute_hash_rate, RewardAlgorithm
from core.models import Share, Miner, Balance, Configuration
from core.serializers import ShareSerializer, BalanceSerializer, MinerSerializer, ConfigurationSerializer
from ErgoAccounting.settings import ERGO_EXPLORER_ADDRESS, MAX_PAGINATION, DEFAULT_PAGINATION
from core.tasks import generate_and_send_transaction

logger = logging.getLogger(__name__)

ERGO_EXPLORER_ADDRESS = getattr(settings, "ERGO_EXPLORER_ADDRESS")
MAX_PAGINATION = getattr(settings, "MAX_PAGINATION")
DEFAULT_PAGINATION = getattr(settings, "DEFAULT_PAGINATION")


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
            serializer.save(miner=miner)
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

    # change status to 3

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
        serializer.save(status=3)


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
        if not configurations:
            logger.info('Saving new configuration.')
            serializer.save()
        else:
            logger.info('Updating configuration')
            configuration = Configuration.objects.get(key=key)
            configuration.value = value
            configuration.save()


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
            immature=Sum('share__balance__balance', filter=Q(share__balance__status=1)),
            mature=Sum('share__balance__balance', filter=Q(share__balance__status=2)),
            withdraw=Sum('share__balance__balance', filter=Q(share__balance__status=3)),
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


class BlockView(viewsets.GenericViewSet):
    pagination_class = PageNumberPagination
    pagination_class.page_size = DEFAULT_PAGINATION

    def get_queryset(self):
        """
        Return response of address Explorer of ergo
        This function get response and check data if a block mined by miner of in pool set flag 'inPool': True in json item
        In this function set limit in number get block from explorer
        :return:mined block
        """
        query = dict()
        base = urljoin(ERGO_EXPLORER_ADDRESS, 'blocks')
        # Create url for send to explorer and set limit for get blocks.
        for param in self.request.query_params:
            # Remove param page from request to Explorer
            if param == 'page':
                continue
            value = self.request.query_params.get(param)
            # limitation use for limited query on data_base with get limit block
            if param == 'limit' and int(value) > MAX_PAGINATION:
                value = MAX_PAGINATION
            query[param] = value
        # if in request not use limit set limitation policy pool
        if 'limit' not in query:
            query['limit'] = str(MAX_PAGINATION)
        url_parts = list(urlparse(base))
        base_query = dict(parse_qsl(url_parts[4]))
        base_query.update(query)
        url_parts[4] = urlencode(base_query)
        url = urlunparse(url_parts)

        try:
            # Send request to Ergo_explorer for get blocks
            response = requests.get(url).json()
            logger.info("Get response from url {}".format(url))
        except requests.exceptions.RequestException as e:
            logger.error("Can not resolve response from explorer")
            logger.error(e)
            return {'status': 'error'}
        heights = list()
        for item in response['items']:
            heights.append(item.get('height'))
        # get shares that mined block in our pool and are in response of explorer
        # and set flag 'inpool' on this block
        shares = Share.objects.values('block_height').filter(Q(status='solved'), block_height__in=heights)
        heights_share = list()
        for share in shares:
            heights_share.append(share['block_height'])
        for item in response.get('items'):
            if item.get('height') in heights_share:
                item.update({"inPool": True})
                logger.info("Set flag inPool true for height {}".format(item.get('height')))
            else:
                item.update({"inPool": False})
        return response

    def list(self, request):
        queryset = self.get_queryset()
        # set pagination on response
        try:
            page = self.paginate_queryset(queryset['items'])
        except Exception as e:
            logger.error("Pagination query set have bug.")
            logger.error(e)
            return Response({
                "message": 'No more record.',
                "data": {}
            }, status=status.HTTP_404_NOT_FOUND)
        if page is not None:
            response = {
                'items': page,
                'total': queryset['total']
            }
            return self.get_paginated_response(response)
        logger.debug("Items is None")
        return Response(
            {"message": 'There isn\'t record', "data": {}}, status=status.HTTP_200_OK)


class MinerView(viewsets.GenericViewSet, mixins.UpdateModelMixin):
    model = Miner
    serializer_class = MinerSerializer
    queryset = Miner.objects.all()
    lookup_field = 'public_key'

    @action(detail=True, methods=['post'], name='withdrawal')
    def withdraw(self, request, public_key=None):
        """
        this action specifies withdraw action of the miner.
        runs a celery task in case that the request is valid
        """
        miner = self.get_object()
        balances = Balance.objects.filter(miner=miner, status__in=[2, 3])
        total = sum(b.balance for b in balances)

        requested_amount = request.data.get('withdraw_amount')
        try:
            requested_amount = float(requested_amount)
            if requested_amount <= 0:
                raise Exception()

        except:
            return Response({'message': 'withdraw_amount field is not valid.'}, status=status.HTTP_400_BAD_REQUEST)

        if requested_amount > total:
            return Response({'message': 'withdraw_amount is bigger than total balance.'},
                            status=status.HTTP_400_BAD_REQUEST)

        generate_and_send_transaction.delay([(miner.public_key, int(requested_amount * 1e9))], subtract_fee=True)
        return Response({'message': 'withdrawal was successful.',
                         'data': {'balance': total - requested_amount}}, status=status.HTTP_200_OK)
