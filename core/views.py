from rest_framework.response import Response
from django.db.models import Q, Count, Sum
from rest_framework.views import APIView
from rest_framework import viewsets, mixins, filters
from .serializers import *
from .utils import prop
from .models import *


class ShareView(viewsets.GenericViewSet,
                mixins.CreateModelMixin):
    queryset = Share.objects.all()
    serializer_class = ShareSerializer

    def perform_create(self, serializer, *args, **kwargs):
        """
        in case any share is repetitious, regardles of being valid or invalid
        we must change the status to repetitious (status=4).
        :param serializer:
        :param args:
        :param kwargs:
        :return:
        """

        _share = serializer.validated_data['share']
        _status = serializer.validated_data['status']
        rep_share = Share.objects.filter(share=_share)
        if not rep_share:
            serializer.save()
        else:
            serializer.save(status=4)
            _status = 4
        if _status == 1:
            prop(Share.objects.get(share=_share, status=1))


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


class DashboardView(APIView):
    def get(self, request, pk=None):
        """
        Returns information for this round of shares.
        In the response, there is total shares count of this round and information about each miner balances.
        If the pk is set in url parameters, then information is just about that miner.
        :param request:
        :param pk:
        :return:
        """
        # Timestamp of last solved share
        last_solved_timestamp = Share.objects.filter(status=1).order_by('-created_at').first().created_at

        # Set the response to be all miners or just one with specified pk
        miners = Miner.objects.filter(public_key=pk) if pk else Miner.objects

        # Total shares count of this round
        total_count = Share.objects.filter(created_at__gt=last_solved_timestamp, status=2).count()

        # Shares of this round and balances of user
        round_shares = miners.values('public_key').annotate(
            share_count=Count('id', filter=Q(share__created_at__gt=last_solved_timestamp, share__status=2)),
            immature=Sum('share__balance__balance', filter=Q(share__balance__status=1)),
            mature=Sum('share__balance__balance', filter=Q(share__balance__status=2)),
            withdraw=Sum('share__balance__balance', filter=Q(share__balance__status=3)),
        )

        # Dictionary of miners with their balances and shares for response
        miners_info = dict()
        for item in round_shares:
            miners_info[item['public_key']] = dict()
            miners_info[item['public_key']]['round_shares'] = item['share_count']
            miners_info[item['public_key']]['immature'] = item['immature'] if item['immature'] else 0
            miners_info[item['public_key']]['mature'] = item['mature'] if item['mature'] else 0
            miners_info[item['public_key']]['withdraw'] = item['withdraw'] if item['withdraw'] else 0

        response = {
            'round_shares': total_count,
            'timestamp': last_solved_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'users': miners_info
        }
        return Response(response)


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
