from django.shortcuts import render
from rest_framework import viewsets
from .models import *
from .serializers import *
from rest_framework import generics
from django.db.models import Q
from rest_framework.views import APIView
from django.http import JsonResponse
from rest_framework.decorators import action
from rest_framework import viewsets, mixins
from rest_framework.response import Response
from rest_framework import status
import json

class ShareView(viewsets.GenericViewSet,
                mixins.CreateModelMixin,):
    queryset = Share.objects.all()
    serializer_class = ShareSerializer
    
    """
    in case any share is repetitious, regardles of being valid or invalid
    we must change the status to repetitious (status=4).
    """
    def perform_create(self, serializer, *args, **kwargs):
        if serializer.is_valid():
            _share = serializer.validated_data['share']
        rep_share = Share.objects.filter(
            share = _share)
        if not rep_share:
            serializer.save()
        else:
            serializer.save(status=4)

class BalanceView(viewsets.GenericViewSet,
                mixins.CreateModelMixin,
                mixins.UpdateModelMixin,
                mixins.ListModelMixin,):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    #change status to 3

    """
    the status of the API requests are 1 as default.
    we must change them to 3, the API is only called when 
    we want to withdraw, the status of withdraw is 3
    """
    def perform_create(self, serializer, *args, **kwargs):
        serializer.save(status =3)