from rest_framework import routers
from django.urls import path

from rest_framework.authtoken.views import obtain_auth_token

from .views import *

router = routers.DefaultRouter()
router.register(r'shares', ShareView)
router.register(r'balance', BalanceView)
router.register(r'conf', ConfigurationViewSet)
router.register(r'user', UserApiViewSet, basename='ApiUser')
router.register(r'blocks', BlockView, basename='Blocks')
router.register(r'info', InfoViewSet, basename='Info')
router.register(r'login', ErgoAuthToken, basename='login')
router.register(r'administrator/users', AdministratorUserViewSet, basename='Administrator')

urlpatterns = router.urls
# urlpatterns += [
#     path('api-token-auth/', obtain_auth_token, name='api_token_auth'),
# ]
