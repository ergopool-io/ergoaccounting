from django.db.models import Count, Q, Sum
from django.db import transaction

from ErgoAccounting.production import API_KEY, NODE_ADDRESS
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
        logger.info('running {} algorithm'.format(self.__class__.__name__))

        if not self.should_run_reward_algorithm(share):
            return

        # finding the penultimate valid share
        beginning_share = self.get_beginning_share(share.created_at)
        shares = Share.objects.filter(
            created_at__lte=share.created_at,
            created_at__gte=beginning_share.created_at,
            is_orphaned=False,
            status__in=["solved", "valid"],
        )

        # share reward for these shares
        self.create_balance_from_share(shares, share)

        return

    @abc.abstractmethod
    def get_beginning_share(self, considered_time):
        """
        This method calculates the first valid share based on the implemented algorithm
        :param considered_time: shares before this time are considered
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
            logger.error('Defined reward algorithm in configuration is not valid, {}' .format(algorithm))
            raise ValueError('Defined reward algorithm in configuration is not valid, {}' .format(algorithm))

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
        return shares.values_list('miner').annotate(Sum('difficulty'))

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
        total_contribution = sum(share for _, share in miners_share_count)

        # delete all related balances if it's not the first execution
        # of prop function (according to the input share)
        # TODo
        # Balance.objects.filter(share=share).delete()
        prev_balances = Balance.objects.filter(share=last_solved_share).values('miner').annotate(balance=Sum('balance'))
        miner_to_prev_balances = {bal['miner']: bal['balance'] for bal in prev_balances}
        all_considered_miners = set(list(miner_to_prev_balances.keys()) + [x[0] for x in miners_share_count])

        miner_to_contribution = {miner: contribution for (miner, contribution) in miners_share_count}
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
                    balances.append(Balance(
                        miner_id=miner_id,
                        share=last_solved_share,
                        status='immature',
                        balance=miner_reward - miner_prev_reward)
                    )

            # create and save balances to database
            Balance.objects.bulk_create(balances)
            logger.info('Balance created for all miners related to this round.')


class Prop(RewardAlgorithm):
    def get_beginning_share(self, considered_time):
        """
        This method calculates the first valid share based on prop algorithm
        :param considered_time: shares before this time are considered
        :return: first valid share based on implemented algorithm
        """
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
    def get_beginning_share(self, considered_time):
        """
        This method calculates the first valid share based on the PPLNS algorithm
        :param considered_time: shares before this time are considered
        :return: first valid share based on implemented algorithm
        """
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


def compute_hash_rate(by, to=timezone.now(), pk=None):
    """
    Function for calculate hash_rate between two time_stamp for a specific public_key or all
    miners in that round.
    :param by: timestamp for start period
    :param to: timestamp for end period if `to` not exist set default now time.
    :param pk: In the event that pk there is.
    :return: a json of public_key and hash_rate them and total hash_rate
    """
    logger.info('computing hash for pk: {}'.format(pk))
    if pk:
        shares = Share.objects.values('miner__public_key').filter(miner__public_key=pk).filter(
            Q(status='valid') | Q(status='solved'), created_at__range=(by, to)).annotate(Sum('difficulty'))
    else:
        shares = Share.objects.values('miner__public_key').filter(
            Q(status='valid') | Q(status='solved'), created_at__range=(by, to)).annotate(Sum('difficulty'))

    time = (to - by).total_seconds()
    miners = dict()
    total_hash_rate = 0
    for share in shares:
        miners[share['miner__public_key']] = dict()
        miners[share['miner__public_key']]['hash_rate'] = int((share['difficulty__sum'] / time) + 1)
        total_hash_rate = total_hash_rate + share['difficulty__sum'] if not pk else 0

    miners.update({'total_hash_rate': int((total_hash_rate / time) + 1)}) if not pk else None
    return miners


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
        kwargs = {"headers.json": header}
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
            "status": "success" if 200 <= response.status_code <= 299 else "External Error"
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
    :return: selected_address associated with miner address if one selected
             or the last used withdraw address. returns None if no withdraw address is available
    """
    if miner.selected_address is not None:
        return miner.selected_address.address

    address = Address.objects.filter(address_miner=miner, category='withdraw').order_by('-last_used').first()
    if address is not None:
        return address.address

    return None
