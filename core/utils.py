from django.db.models import Count
from django.db import transaction
from .models import Share, Balance, Configuration


def prop(share):
    """
    This function use "proportional algorithm" as a pool mining reward method.
    In fact "prop" function create a new balance for each miner involving in the mining round and
    assign a reward based on "proportional algorithm" to balances,
    by receiving a 'solved' share as input and
    computing the number of miner's valid shares for each miner
    between the input share and the last 'solved' share before the input share.
    :param share: A 'solved' share which lead to creation of a new
    block in the block chain (in normal situation)
    If the input share isn't 'solved', it will be invalid and the function do nothing.
    :return: nothing
    """
    # total reward per solved block
    TOTAL_REWARD = Configuration.objects.TOTAL_REWARD
    # maximum reward : each miner must get reward less than MAX_REWARD
    MAX_REWARD = Configuration.objects.MAX_REWARD
    # check whether the input share is 'solved' or not (valid, invalid, repetitious)
    if not share.status == "solved":
        return
    # make all requests atomic
    with transaction.atomic():
        # delete all related balances if it's not the first execution of prop function (according to the input share)
        Balance.objects.filter(share=share).delete()
        # define last solved share
        last_solved_share = share
        # finding the penultimate valid share
        penultimate_solved_share = Share.objects.filter(
            created_at__lt=last_solved_share.created_at,
            status="solved"
        ).order_by('-created_at').first()
        # the end time of this block mining round
        end_time = last_solved_share.created_at
        # the beginning time of this block mining round
        if penultimate_solved_share is not None:
            begin_time = penultimate_solved_share.created_at
            # all the valid shares between the two last solved shares
            shares = Share.objects.filter(
                created_at__lte=end_time,
                created_at__gt=begin_time,
                status__in=["solved", "valid"],
            )
        else:
            begin_time = Share.objects.all().order_by('created_at').first().created_at
            # all the valid shares before the first solved share
            shares = Share.objects.filter(
                created_at__lte=end_time,
                created_at__gte=begin_time,
                status__in=["solved", "valid"],
            )
        # total number of valid shares in this block mining round
        total_number_of_shares = shares.count()
        # a list of (miner's primary key, miner's valid shares) for this block mining round
        miners_share_count = shares.values_list('miner').annotate(Count('miner'))
        # define "balances" as a list to create and save balance objects
        balances = list()
        # for each miner, create a new balance and calculate it's reward and save it
        for (miner_id, share_count) in miners_share_count:
            balances.append(Balance(
                miner_id=miner_id,
                share=last_solved_share,
                balance=min(MAX_REWARD, TOTAL_REWARD * (share_count / total_number_of_shares)))
            )
        # create and save balances to database
        Balance.objects.bulk_create(balances)
    return


def PPLNS(share):
    """
    This function use "PPLNS algorithm" as a pool mining reward method.
    In fact 'PPLNS' function create a new balance for each miner which
    has at least one 'valid' share in the last N 'valid' or 'solved' shares
    before the input 'solved' share (the input is included too).
    So we retrieve the last 'N' 'solved' or 'valid' shares before
    the input 'solved' share (the input is included) and then we use 'prop' algorithm
    to assign rewards to involving miners.
    :param share: A 'solved' share which lead to creation of a new
    block in the block chain (in normal situation)
    If the input share isn't 'solved', it will be invalid and the function do nothing.
    :return: nothing
    """
    # total reward per solved block
    TOTAL_REWARD = Configuration.objects.TOTAL_REWARD
    # maximum reward : each miner must get reward less than MAX_REWARD
    MAX_REWARD = Configuration.objects.MAX_REWARD
    # 'PPLNS' parameter
    N = Configuration.objects.PPLNS_N
    # check whether the input share is 'solved' or not (valid, invalid, repetitious)
    if not share.status == "solved":
        return
    # make all database requests and queries atomic
    with transaction.atomic():
        # delete all related balances if it's not the first execution of 'PPLNS' function for the input share
        Balance.objects.filter(share=share).delete()
        # retrieve last N 'solved' or 'valid' shares before the input share (the input is included too)
        sliced_shares = Share.objects.filter(
            id__lte=share.id,
            status__in=["solved", "valid"]).order_by('-id')
        if sliced_shares.count() > N:
            sliced_shares = sliced_shares[:N]
        shares = Share.objects.filter(id__in=sliced_shares)
        # a list of (miner's primary key, miner's valid shares) for this block mining round
        miners_share_count = shares.values_list('miner').annotate(Count('miner'))
        # total number of objects in 'shares' queryset
        total_number_of_shares = shares.count()
        # define "balances" as a list to create and save balance objects
        balances = list()
        # for each miner, create a new balance and calculate it's reward and save it
        for (miner_id, share_count) in miners_share_count:
            balances.append(Balance(
                miner_id=miner_id,
                share=share,
                balance=min(MAX_REWARD, TOTAL_REWARD * (share_count / total_number_of_shares)))
            )
        # create and save balances to database
        Balance.objects.bulk_create(balances)
    return
