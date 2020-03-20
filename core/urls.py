from rest_framework import routers
from django.urls import path, re_path
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
router.register(r'totp', TOTPDeviceViewSet, basename='TOTP Device')
router.register(r'ui', UIDataViewSet, basename='UI Data')
router.register(r'support', SupportViewSet, basename='Support')

urlpatterns = router.urls
urlpatterns += [
    # path('api-token-auth/', obtain_auth_token, name='api_token_auth'),
    re_path('ui/(?P<url>.*)/$', UIDataViewSet.as_view({'get': 'list', 'post': 'create'}), name='default'),
]
