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
NODE_ADDRESS_BACKUP = "http://%s:%s/" % (os.environ.get("NODE_HOST_BACKUP"), os.environ.get("NODE_PORT_BACKUP")) if os.environ.get("NODE_HOST_BACKUP") else ""

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
    'periodic_handle_withdraw': {
        'task': 'core.tasks.handle_withdraw',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_HANDLE_WITHDRAW_INTERVAL'), 15 * 60),
        'args': ()
    },
    'periodic_handle_txs': {
        'task': 'core.tasks.handle_transactions',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_HANDLE_TRANSACTIONS_INTERVAL'), 25 * 60),
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
    'periodic_calculate_hash_rate': {
        'task': 'core.tasks.periodic_calculate_hash_rate',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_CALCULATE_HASH_RATE'), 300),
        'args': ()
    },
    'periodic_check_shares': {
        'task': 'core.tasks.periodic_check_shares',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_CHECK_SHARES'), 25 * 60),
        'args': ()
    },
    'periodic_check_pool_nodes': {
        'task': 'core.tasks.periodic_check_pool_nodes',
        'schedule': parse_cron_tab(os.environ.get('PERIODIC_CHECK_POOL_NODES'), 25 * 60),
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
# limit of getting block for calculate hash_rate periodic_task
LIMIT_NUMBER_BLOCK = 50
# Period check invalid shares, 30 minute (second)
PERIOD_CHECK_SHARES = 30 * 60
# The threshold for send invalid shares notice to admin
THRESHOLD_INVALID_SHARES = 8


RECAPTCHA_SECRET = os.environ.get("RECAPTCHA_SECRET")
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY")

TOTP_CONFIG = {
    # PositiveSmallIntegerField: The time step in seconds. (Default: 30)
    'step': 60,
    # BigIntegerField: The Unix time at which to begin counting steps. (Default: 0)
    't0': None,
    # PositiveSmallIntegerField: The number of digits to expect in a token (6 or 8). (Default: 6)
    'digits': None,
    # PositiveSmallIntegerField: The number of time steps in the past or future to allow.
    # For example, if this is 1, we’ll accept any of three tokens:
    # the current one, the previous one, and the next one. (Default: 1)
    'tolerance': None,
    # SmallIntegerField: The number of time steps the prover is known to deviate from our clock.
    # If OTP_TOTP_SYNC is True, we’ll update this any time we match a token that is not the current one. (Default: 0)
    'drift': -2
}
# Create config for create new device
DEVICE_CONFIG = {}
for config in TOTP_CONFIG:
    if TOTP_CONFIG[config]:
        DEVICE_CONFIG.update({config: TOTP_CONFIG[config]})

# The issuer parameter for the otpauth URL generated by config_url.
# This can be a string or a callable to dynamically set the value.(Default: None)
OTP_TOTP_ISSUER = None
# This controls the rate of throttling.
# The sequence of 1, 2, 4, 8… seconds is
# multiplied by this factor to define the delay imposed after 1, 2, 3, 4… successive failures.
# Set to 0 to disable throttling completely. (Default: 1)
OTP_TOTP_THROTTLE_FACTOR = 0
# If true, then TOTP devices will keep track of the difference between the prover’s clock and our own.
# Any time a TOTPDevice matches a token in the past or future,
# it will update drift to the number of time steps that the two sides are out of sync.
# For subsequent tokens, we’ll slide the window of acceptable tokens by this number.(Default: True)
OTP_TOTP_SYNC = None

# Config QRCODE
QR_CONFIG = {
    'QR_VERSION': 1,
    'QR_BOX_SIZE': 10,
    'QR_BORDER': 4
}

DEFAULT_TOKEN_EXPIRE = {
    # if the user doesn't use the token in this period token expires.
    'PER_USE': 24 * 60 * 60,
    # the token expires after this time.
    'TOTAL': 10 * 24 * 60 * 60
}

# Default prefix for save data of UI
DEFAULT_UI_PREFIX_DIRECTORY = os.environ.get("UI_VOLUME", os.path.join(BASE_DIR, 'ui/'))


# Config to send email
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = os.environ.get('EMAIL_PORT', '587')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'test')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', 'test')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', "yes") == "yes"
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', 'support@eropool.io')
SENDER_EMAIL_ADDRESS = os.environ.get('SENDER_EMAIL_ADDRESS', 'deploy.ergopool@gmail.com')
RECEIVERS_EMAIL_ADDRESS = os.environ.get('RECEIVERS_EMAIL_ADDRESS', ['support@ergopool.io', ])

# Number of tries to call RUN TASK after a problem arises
NUMBER_OF_RETRIES_RUN_TASK = os.environ.get("NUMBER_OF_RETRIES_RUN_TASK")
# number that define it as an exponential value that gets increased by each retry
NUMBER_START_EXPONENTIAL_RETRIES = os.environ.get("NUMBER_START_EXPONENTIAL_RETRIES")

# number of block that a node can falling behind the last block
# (Note: for example if set 3, will be checked between -3 to 3)
THRESHOLD_CHECK_HEIGHT = 3
