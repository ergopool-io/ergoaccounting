import os
from ErgoAccounting.celery import app

# # Database
# # https://docs.djangoproject.com/en/2.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'db_accounting',
        'USER': 'admin',
        'PASSWORD': 'admin',
        'HOST': 'db',  # same as the docker-compose service
        'PORT': 5432,
    }
}
# Allowed Hosts
ALLOWED_HOSTS = ['127.0.0.1', os.environ.get('HOST'), os.environ.get("INTERNAL_HOST")]


# Explorer ergo
ERGO_EXPLORER_ADDRESS = os.environ.get("EXPLORER", "https://api-testnet.ergoplatform.com/")

# Set limitation for get blocks from explorer and query on database
MAX_PAGINATION = 200

# For pagination requests
DEFAULT_PAGINATION = 50

# Address Node (ex: "http://127.0.0.1:9053/")
NODE_ADDRESS = "http://%s:%s/" % (os.environ.get("NODE_HOST"), os.environ.get("NODE_PORT", "9052"))

# Secret Key of Node(apiKey) (ex: "623f4e8e440007f45020afabbf56d8ba43144778757ea88497c794ad529a0433")
API_KEY = os.environ.get("SECRET")

# Logging config
# You may want to uncomment mail handler in production!
# you should get the logger like this whenever you need it: logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[%(asctime)s] %(levelname)-8s [%(module)s:%(funcName)s:%(lineno)d]: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'level': LOG_LEVEL,
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'formatter': 'verbose',
            'filename': os.path.join(BASE_DIR, '.important.log')
        },
        # 'mail': {
        #     'level': 'CRITICAL',
        #     'class': 'django.utils.log.AdminEmailHandler',
        #     'formatter': 'verbose',
        # },
    },
    'loggers': {
        'core': {
            'handlers': ['console', 'file'],
            'propagate': True,
            'level': LOG_LEVEL,
        }
    }
}

# set your approprate broker url, e.g, rabbitmq or redis
broker_url = os.environ.get("BROKER_URL")
#'amqp://guest:guest@localhost:5672//'

# for interval of the periodic task PERIODIC_WITHDRAWAL_INTERVAL should be set
# default interval is 24h, it is also possible to change the crontime to a
# specific time in day, e.g, 00:00am
app.conf.beat_schedule = {
    'periodic_withdrawal': {
        'task': 'core.tasks.periodic_withdrawal',
        'schedule': os.environ.get('PERIODIC_WITHDRAWAL_INTERVAL', 24 * 3600),
        'args': ()
    },
}

