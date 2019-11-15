from rest_framework import viewsets, mixins

from .serializers import *
from .utils import prop
class ShareView(viewsets.GenericViewSet,
                mixins.CreateModelMixin, ):
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
            prop(Share.objects.get(share = _share, status=1))

    

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
