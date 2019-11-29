from django.urls import path
from rest_framework import routers

from .views import *

router = routers.DefaultRouter()
router.register(r'shares', ShareView)
router.register(r'balance', BalanceView)
router.register(r'conf', ConfigurationViewSet)
router.register(r'dashboard', DashboardView, basename='Dashboard')

urlpatterns = router.urls #+ [
#     path('dashboard/', DashboardView.as_view()),
#     path('dashboard/<str:pk>', DashboardView.as_view())
# ]
