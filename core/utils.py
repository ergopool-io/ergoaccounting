from django.db.models import Q, Sum, Min, Max
from django.db import transaction

from .models import Share, Balance, Configuration, Address
from django.utils import timezone
from urllib.parse import urljoin
import json
import sys
import abc
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)
ERGO_EXPLORER_ADDRESS = getattr(settings, "ERGO_EXPLORER_ADDRESS")
MAX_PAGINATION_SIZE = getattr(settings, "MAX_PAGINATION_SIZE")
DEFAULT_PAGINATION_SIZE = getattr(settings, "DEFAULT_PAGINATION_SIZE")
API_KEY = getattr(settings, "API_KEY")
NODE_ADDRESS = getattr(settings, "NODE_ADDRESS")


class RewardAlgorithm(metaclass=abc.ABCMeta):
    def perform_logic(self, share):
        """
        a pool mining reward method based on number of shares of each miner.
        In fact this function create a new balance for each miner involving in the mining round and
        assign a reward based on number of shares of each miner to balances,
        by receiving a 'solved' share as input and
        computing the number of miner's valid shares for each miner
        between the input share and the last 'solved' share before the input share.
        :param share:
        :param share: A 'solved' share which lead to creation of a new
        block in the block chain (in normal situation)
        If the input share isn't 'solved', it will be invalid and the function do nothing.
        :return: nothing
        """
        logger.info('running {} reward algorithm for share {}.'.format(self.__class__.__name__, share.share))

        if not self.should_run_reward_algorithm(share):
            logger.debug('quiting reward algorithm, should not run now!')
            return

        # finding the penultimate valid share
        beginning_share = self.get_beginning_share(share)
        shares = Share.objects.filter(
            created_at__lte=share.created_at,
            created_at__gte=beginning_share.created_at,
            is_orphaned=False,
            status__in=["solved", "valid"],
        )

        # share reward for these shares
        self.create_balance_from_share(shares, share)

    @abc.abstractmethod
    def get_beginning_share(self, share):
        """
        This method calculates the first valid share based on the implemented algorithm
        :param share: current share
        :return: first valid share based on implemented algorithm
        """
        return

    @staticmethod
    def get_instance():
        """
        This method returns an instance of appropriate reward algorithm based on configuration
        :return: an instance of appropriate reward algorithm
        """
        module = sys.modules[__name__]
        algorithm = Configuration.objects.REWARD_ALGORITHM

        try:
            class_ = getattr(module, algorithm)
            logger.info('Reward algorithm is {}'.format(class_))
            return class_()

        except:
            logger.error('Defined reward algorithm in configuration is not valid, {}'.format(algorithm))
            raise ValueError('Defined reward algorithm in configuration is not valid, {}'.format(algorithm))

    def should_run_reward_algorithm(self, share):
        """
        evaluates if reward algorithm should be run
        :param share: last solved share
        :return: whether reward algorithm should be run or not
        """
        # check whether the input share is 'solved' or not (valid, invalid, repetitious)
        return share.status == 'solved'

    def get_reward_to_share(self):
        """
        calculates real reward to share between shares of a round
        :return: real reward to be shared
        """
        # total reward considering pool fee and reward factor
        REWARD_FACTOR = Configuration.objects.REWARD_FACTOR
        PRECISION = Configuration.objects.REWARD_FACTOR_PRECISION
        TOTAL_REWARD = round((Configuration.objects.TOTAL_REWARD / 1e9) * REWARD_FACTOR, PRECISION)
        TOTAL_REWARD = int(TOTAL_REWARD * 1e9)
        return int(TOTAL_REWARD * (1 - Configuration.objects.FEE_FACTOR))

    def get_miner_shares(self, shares):
        """
        :param shares: share objects to be considered in calculating miners' share (as in money share not Share object)
        :return: list of tuples (miner, share)
        """
        return shares.values_list('miner').annotate(Sum('difficulty'), Min('block_height'),
                                                    Max('block_height'))

    def create_balance_from_share(self, shares, last_solved_share):
        """
        This method shares the reward between shares of each miner
        :param shares: all the valid shares to be considered
        :param last_solved_share: last solved share
        :return: nothing
        """
        # maximum reward : each miner must get reward less than MAX_REWARD
        MAX_REWARD = Configuration.objects.MAX_REWARD
        # total reward per solved block, i.e, TOTAL_REWARD - FEE
        REWARD = self.get_reward_to_share()
        # total number of valid shares in this block mining round
        # total_contribution = shares.count()
        # a list of (miner's primary key, miner's valid shares) for this block mining round
        # miners_share_count = shares.values_list('miner').annotate(Count('difficulty'))
        miners_share_count = list(self.get_miner_shares(shares))
        total_contribution = sum(share for _, share, _, _ in miners_share_count)

        # delete all related balances if it's not the first execution
        # of prop function (according to the input share)
        prev_balances = Balance.objects.filter(share=last_solved_share).values('miner').annotate(balance=Sum('balance'))
        logger.info('prev balances len: {}.'.format(last_solved_share.share, prev_balances.count()))
        miner_to_prev_balances = {bal['miner']: bal['balance'] for bal in prev_balances}
        all_considered_miners = set(list(miner_to_prev_balances.keys()) + [x[0] for x in miners_share_count])

        logger.info('miners related to this share: {}.'.format(len(all_considered_miners)))
        logger.info('prev miners related to this share: {}.'.format(len(miner_to_prev_balances)))

        miner_to_contribution = {miner: contribution for (miner, contribution, _, _) in miners_share_count}
        miner_to_height = {miner: (min_height, max_height) for (miner, _, min_height, max_height)
                           in miners_share_count}
        with transaction.atomic():
            # define "balances" as a list to create and save balance objects
            balances = list()
            # for each miner, create a new balance and calculate it's reward and save it
            # for (miner_id, share_count) in miners_share_count:
            for miner_id in all_considered_miners:
                contribution = miner_to_contribution.get(miner_id, 0)
                miner_reward = min(MAX_REWARD, int(REWARD * (contribution / total_contribution)))
                miner_prev_reward = miner_to_prev_balances.get(miner_id, 0)
                if miner_reward != miner_prev_reward:
                    # here we should either increase immature balances or create orphaned immature
                    # balance to decrease miner's reward
                    logger.info('balance of miner {} changes to {}, prev one is {}.'.
                                format(miner_id, miner_reward, miner_prev_reward))
                    min_height = miner_to_height[miner_id][0]
                    max_height = miner_to_height[miner_id][1]
                    balances.append(Balance(
                        miner_id=miner_id,
                        share=last_solved_share,
                        status='immature',
                        balance=miner_reward - miner_prev_reward,
                        min_height=min_height,
                        max_height=max_height),
                    )

            # create and save balances to database
            logger.info('bulk creating balances {}.'.format(len(balances)))
            Balance.objects.bulk_create(balances)
            logger.info('Balance created for all miners related to this round.')


class PPS(RewardAlgorithm):
    def should_run_reward_algorithm(self, share):
        return share.status in ['valid', 'solved']

    def get_beginning_share(self, share):
        """
        This method calculates the first valid share based on the implemented algorithm
        :param share: current share
        :return: first valid share based on implemented algorithm
        """
        return share

    def get_reward_to_share(self):
        """
        calculates real reward to share between shares of a round
        :return: real reward to be shared
        """
        # total reward considering pool fee and reward factor
        REWARD_FACTOR = Configuration.objects.REWARD_FACTOR
        PRECISION = Configuration.objects.REWARD_FACTOR_PRECISION
        TOTAL_REWARD = round((Configuration.objects.TOTAL_REWARD / 1e9) * REWARD_FACTOR, PRECISION)
        TOTAL_REWARD = int(TOTAL_REWARD * 1e9)
        SOLUTION_REWARD = int(TOTAL_REWARD * (1 - Configuration.objects.FEE_FACTOR))
        return SOLUTION_REWARD / Configuration.objects.POOL_BASE_FACTOR


class Prop(RewardAlgorithm):
    def get_beginning_share(self, share):
        """
        This method calculates the first valid share based on prop algorithm
        :param share: current share
        :return: first valid share based on implemented algorithm
        """
        considered_time = share.created_at
        penultimate_solved_share = Share.objects.filter(
            created_at__lt=considered_time,
            status="solved",
            is_orphaned=False
        ).order_by('-created_at').first()

        beginning_share = Share.objects.all(). \
            filter(status__in=['solved', 'valid'], is_orphaned=False).order_by('created_at').first()

        # there are more than one solved
        if penultimate_solved_share is not None:
            beginning_share = Share.objects.filter(
                created_at__lte=considered_time,
                created_at__gt=penultimate_solved_share.created_at,
                status__in=['valid', 'solved'],
                is_orphaned=False
            ).order_by('created_at').first()

        return beginning_share


class PPLNS(RewardAlgorithm):
    def get_beginning_share(self, share):
        """
        This method calculates the first valid share based on the PPLNS algorithm
        :param share: current share
        :return: first valid share based on implemented algorithm
        """
        considered_time = share.created_at
        N = Configuration.objects.PPLNS_N
        prev_shares = Share.objects.filter(
            created_at__lte=considered_time,
            status__in=["solved", "valid"],
            is_orphaned=False
        ).order_by('-created_at')

        # more than N shares, slicing
        if prev_shares.count() > N:
            prev_shares = prev_shares[:N]

        return prev_shares[prev_shares.count() - 1]


def node_request(api, header=None, data=None, params=None, request_type="get"):
    """
    Function for request to node
    :param api: string
    :param header: dict
    :param data: For request post use this
    :param request_type: For select ypt of request get or post
    :param params: query string
    :return: response of request
    """
    if header is None:
        header = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'api_key': API_KEY
        }

    try:
        # check allowed methods
        if request_type not in ['get', 'post', 'put', 'patch', 'option']:
            return {"status": "error", "response": "invalid request type"}
        # requests kwargs generated
        kwargs = {"headers": header}
        # append data to kwargs if exists
        if data:
            kwargs["data"] = json.dumps(data)
        if params:
            kwargs["params"] = params
        # call requests method according to request_type
        response = getattr(requests, request_type)(urljoin(NODE_ADDRESS, api), **kwargs)
        response_json = response.json()
        # check status code 2XX range is success
        return {
            "response": response_json,
            "status": "success" if 200 <= response.status_code <= 299 else
            ("not-found" if response.status_code == 404 else "External Error")
        }
    except requests.exceptions.RequestException as e:
        logger.error("Can not resolve response from node")
        logger.error(e)
        response = {'status': 'error', 'message': 'Can not resolve response from node'}
        raise Exception(response)


class BlockDataIterable(object):

    def __init__(self, request):
        """
        save remote queries
        TODO we can change this api to call node blocks instead of interacting explorer
        :param request:
        """
        queries = dict(request.GET)
        page_index = int(request.GET.get("page", 1)) - 1
        page_size = min(int(request.GET.get("size", DEFAULT_PAGINATION_SIZE)), MAX_PAGINATION_SIZE)
        offset = page_size * page_index
        limit = page_size
        queries.pop("page", 0)
        queries.pop("size", 0)
        queries.update({"offset": offset, "limit": limit})
        self.queries = queries
        self._status = None
        self._count = None
        self._values = None

    def load_remote_data(self):
        """
        load explorer data and store it in some cache variables
        :return: noting
        """
        try:
            url = urljoin(ERGO_EXPLORER_ADDRESS, 'blocks')
            # Send request to Ergo_explorer for get blocks
            response = requests.get(url, self.queries)
            response = response.json()
            logger.info("Get response from url {}".format(url))
            self._values = response.get("items", [])
            self._count = response.get("total", 0)
            self._status = "success"
            self.set_flags()
        except requests.exceptions.RequestException as e:
            logger.error("Can not resolve response from explorer")
            logger.error(e)
            self._status = "error"
            self._count = 0
            self._values = {"error": "can`t connect to explorer"}

    def set_flags(self):
        """
        scan a list of blocks and set pool flag on them if mined with pool
        :return: nothing
        """
        heights = [item.get("height") for item in self._values]
        solved_heights = set(
            Share.objects.values_list('block_height', flat=True).filter(Q(status='solved'), block_height__in=heights))
        for item in self._values:
            item['pool'] = item.get("height") in solved_heights

    def __getitem__(self, item):
        """
        get a list of blocks data
        :param item: not used because this class has only current page of data
        :return:
        """
        if self._values is None:
            # if cache is empty we must load remote data
            self.load_remote_data()
        return self._values

    def __len__(self):
        """
        get total elements
        :return:
        """
        if self._values is None:
            # if cache is empty we must load remote data
            self.load_remote_data()
        return self._count


def get_miner_payment_address(miner):
    """
    :param miner: a miner object
    :return: miner address associated with the given miner
    """
    address = Address.objects.filter(address_miner=miner, category='miner').order_by('-last_used').first()
    if address is not None:
        return address.address

    logger.error('miner {} does not have an address for withdrawal.'.format(miner.public_key))
    return None


def verify_recaptcha(recaptcha_code):
    """
    Function for verify recaptcha with service google
    :param recaptcha_code:
    :return:
    """
    if settings.RECAPTCHA_SECRET:
        url = "https://www.google.com/recaptcha/api/siteverify"
        post_data = {
            "secret": settings.RECAPTCHA_SECRET,
            "response": recaptcha_code
        }
        response = requests.post(url, data=post_data).json()
        return response.get('success')
    return True
