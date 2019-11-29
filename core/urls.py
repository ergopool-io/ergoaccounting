from django.urls import path
from rest_framework import routers

from .views import *

router = routers.DefaultRouter()
router.register(r'shares', ShareView)
router.register(r'balance', BalanceView)

urlpatterns = router.urls
