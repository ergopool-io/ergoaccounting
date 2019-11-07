from django.urls import path , include
from .views import *
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'shares', ShareView)
router.register(r'balance', BalanceView)

urlpatterns = router.urls