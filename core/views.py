from django.db.models import Q, Count, Sum
from datetime import datetime, timedelta
from rest_framework import filters
from rest_framework import viewsets, mixins
from rest_framework.response import Response
from core.utils import compute_hash_rate
from django.utils import timezone

from .serializers import *
from core.models import Configuration
from .utils import prop


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
            miner = Miner.objects.create(public_key=serializer.validated_data['miner'].lower())
        _share = serializer.validated_data['share']
        _status = serializer.validated_data['status']
        rep_share = Share.objects.filter(share=_share)
        if not rep_share:
            serializer.save(miner=miner)
        else:
            serializer.save(status="repetitious", miner=miner)
            _status = "repetitious"
        if _status == "solved":
            prop(Share.objects.get(share=_share, status="solved"))


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
            serializer.save()
        else:
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
            last_solved=models.Max('created_at', filter=Q(status='solved')),
            first_share=models.Min('created_at')
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
