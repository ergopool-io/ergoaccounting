from rest_framework.permissions import IsAuthenticated


class CustomPermission(IsAuthenticated):
    def has_permission(self, request, view):
        header_keys = [x.lower() for x in dict(request.headers).keys()]
        if 'source-ip' not in header_keys:
            # request is coming from api
            return True

        return super(CustomPermission, self).has_permission(request, view)
