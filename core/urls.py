from rest_framework import routers

from .views import *

router = routers.DefaultRouter()
router.register(r'shares', ShareView)
router.register(r'balance', BalanceView)
router.register(r'conf', ConfigurationViewSet)
router.register(r'dashboard', DashboardView, basename='Dashboard')
router.register(r'blocks', BlockView, basename='Blocks')

urlpatterns = router.urls
