from rest_framework.permissions import IsAuthenticated, BasePermission, SAFE_METHODS
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from core.models import TokenAuth
from datetime import timedelta
from django.conf import settings


class CustomPermission(IsAuthenticated):
    def has_permission(self, request, view):
        header_keys = [x.lower() for x in dict(request.headers).keys()]
        if 'source-ip' not in header_keys:
            # request is coming from api
            return True

        return super(CustomPermission, self).has_permission(request, view)


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class ExpireTokenAuthentication(TokenAuthentication):
    model = TokenAuth
    DEFAULT_TOKEN_EXPIRE = getattr(settings, "DEFAULT_TOKEN_EXPIRE")

    def authenticate_credentials(self, key):
        """
        In this function Inspired by authenticate_credentials of TokenAuthentication and
         added checking the expired token state.
        :param key:
        :return:
        """
        try:
            token = self.model.objects.select_related('user').get(key=key)
        except self.model.DoesNotExist:
            raise AuthenticationFailed(_('Invalid token.'))

        if not (timezone.now() - timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['PER_USE'])) < token.last_use or\
                not (timezone.now() - timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['TOTAL'])) < token.created:
            raise AuthenticationFailed(_('Expired token.'))

        if not token.user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        token.save()
        return (token.user, token)
