import os
from ErgoAccounting.celery import app
from celery.schedules import crontab


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUGGING") == "DEBUG"

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases
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
ALLOWED_HOSTS = os.environ.get('HOST', "").split(",")


# Explorer ergo
ERGO_EXPLORER_ADDRESS = os.environ.get("EXPLORER", "https://api-testnet.ergoplatform.com/")

# Set limitation for get blocks from explorer and query on database
MAX_PAGINATION_SIZE = 200

# For pagination requests
DEFAULT_PAGINATION_SIZE = 50

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
CELERY_BROKER_URL = os.environ.get("BROKER_URL")
#'amqp://guest:guest@localhost:5672//'


def parse_cron_tab(cron_format, default):
    try:
        parts = cron_format.split()
        if len(parts) < 5:
            return default
        return crontab(minute=parts[0], hour=parts[1], day_of_week=parts[2],
                       day_of_month=parts[3], month_of_year=parts[4])
    except:
        return default
# for interval of the periodic tasks should be set intervals should be set by env; the format is (m h d dM MY), i.e.,
# minute, hour, day of week, day of month, month of year
# some examples:
# "* * * * *" --> execute every minute
# "0 0 * * *" --> execute at midnight
# "0 */3 * * *" --> execute every three hours: 3am, 6am, 9am, noon, 3pm, 6pm, 9pm.
app.conf.beat_schedule = {
    'periodic_withdrawal': {
        'task': 'core.tasks.periodic_withdrawal',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_WITHDRAWAL_INTERVAL'), 24 * 3600),
        'args': ()
    },
    'periodic_immature_to_mature': {
        'task': 'core.tasks.immature_to_mature',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_IMMATURE_TO_MATURE_INTERVAL'), 24 * 3600),
        'args': ()
    },
    'periodic_aggregate': {
        'task': 'core.tasks.aggregate',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_AGGREGATE_INTERVAL'), 24 * 3600),
        'args': ()
    },
    'periodic_ergo_price': {
        'task': 'core.tasks.get_ergo_price',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_GET_ERGO_PRICE'), 3600),
        'args': ()
    },
    'periodic_verify_blocks': {
        'task': 'core.tasks.periodic_verify_blocks',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_VERIFY_BLOCKS'), 300),
        'args': ()
    },
}

# aggregate parameters, please set with a confidence threshold
KEEP_SHARES_WITH_DETAIL_NUM = 10
KEEP_SHARES_AGGREGATION_NUM = 710
KEEP_BALANCE_WITH_DETAIL_NUM = 720
AGGREGATE_ROOT_FOLDER = 'aggregation'
SHARE_DETAIL_FOLDER = 'shares_detail'
SHARE_AGGREGATE_FOLDER = 'shares_aggregate'
BALANCE_DETAIL_FOLDER = 'balance_detail'

# Total period calculate hash rate 1-Day (second)
TOTAL_PERIOD_HASH_RATE = 24 * 60 * 60
# Period calculate diagram 30 minute (second)
PERIOD_DIAGRAM = 30 * 60
# Default stop timestamp if not set stop
DEFAULT_STOP_TIME_STAMP_DIAGRAM = 50 * 60 * 60
# Number of Chunk
LIMIT_NUMBER_CHUNK_DIAGRAM = 1000
# Limit on get last balance
NUMBER_OF_LAST_INCOME = 1000
# time stamp for start payout if not exist
DEFAULT_START_PAYOUT = 1000000000
# period for get active miners (1 hour)
PERIOD_ACTIVE_MINERS_COUNT = 3600
# count share in specific period 1-Day (second)
TOTAL_PERIOD_COUNT_SHARE = 24 * 60 * 60


RECAPTCHA_SECRET = os.environ.get("RECAPTCHA_SECRET")
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY")

