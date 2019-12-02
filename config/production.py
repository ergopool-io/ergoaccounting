# # Database
# # https://docs.djangoproject.com/en/2.2/ref/settings/#databases
import os

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'admin',
        'USER': 'admin',
        'PASSWORD': 'admin',
        'HOST': 'db',  # same as the docker-compose service
        'PORT': 5432,
    }
}
# Allowed Hosts
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', os.environ.get('HOST')]
