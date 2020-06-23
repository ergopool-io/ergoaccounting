import logging
import os
from datetime import datetime, timedelta
from hashlib import blake2b
from pathlib import Path
from urllib.parse import urljoin

from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum, Count, Max, Min
from pycoingecko import CoinGeckoAPI

from ErgoAccounting.celery import app
from core.models import Miner, Balance, Configuration, Share, AggregateShare, ExtraInfo, HashRate
from core.utils import node_request, get_miner_payment_address, RewardAlgorithm

logger = logging.getLogger(__name__)

ERGO_EXPLORER_ADDRESS = getattr(settings, "ERGO_EXPLORER_ADDRESS")

@app.task
def periodic_withdrawal():
    """
    A task which for every miner, calculates his balance and if it is above some threshold
    (whether default one or one specified by the miner), calls the generate_and_send_transaction
    to withdraw the balance.
    :return:
    """
    logger.info('running periodic withdrawal.')
    miners = Miner.objects.all()

    pk_to_miner = {
        miner.public_key: miner for miner in miners
    }

    # miners to their balances
    pk_to_total_balance = {
        miner.public_key: 0 for miner in miners
    }

    # miners to min and max height of his balances
    pk_to_height = {
        miner.public_key: (None, None) for miner in miners
    }

    # update miners balances, balances with "withdraw", "pending_withdrawal" and "mature" status
    balances = Balance.objects.filter(status__in=["mature", "withdraw", "pending_withdrawal"]).\
        values('miner__public_key').annotate(balance=Sum('balance'), min_height=Min('min_height'),
                                             max_height=Max('max_height'))
    for balance in balances:
        pk_to_total_balance[balance['miner__public_key']] += balance['balance']
        pk_to_height[balance['miner__public_key']] = (balance['min_height'], balance['max_height'])

    DEFAULT_WITHDRAW_THRESHOLD = Configuration.objects.DEFAULT_WITHDRAW_THRESHOLD
    outputs = []
    # check every miners balances!
    for miner in miners:
        threshold = miner.periodic_withdrawal_amount
        if threshold is None:
            threshold = DEFAULT_WITHDRAW_THRESHOLD

        balance = pk_to_total_balance.get(miner.public_key)
        if balance >= threshold:
            logger.info('we will withdraw for miner {} value of {}.'.format(miner.public_key, balance))
            # above threshold (whether default one or the one specified by the miner)
            outputs.append((miner.public_key, balance))

    # call the appropriate function for withdrawal
    try:
        logger.info('we will withdraw for {} miners.'.format(len(outputs)))
        # Creating balance object with pending_withdrawal status
        outputs = sorted(outputs)
        objects = [Balance(miner=pk_to_miner.get(pk), status="pending_withdrawal", balance=-balance,
                           min_height=pk_to_height[pk][0], max_height=pk_to_height[pk][1]) for pk, balance in outputs]
        Balance.objects.bulk_create(objects)
        outputs = [(x[0], x[1], objects[i].pk) for i, x in enumerate(outputs)]
        generate_and_send_transaction(outputs)

    except Exception as e:
        logger.critical('could not periodically withdraw due to exception, probably in node connection, {}.'.format(e))


@app.task
def generate_and_send_transaction(outputs, subtract_fee=False):
    """
    This function generates transactions for each chunk of outputs based on configuration
    parameter, for example if len(outputs) is 40 and the so called parameter is 15 then it generates
    three transactions where they contain 15, 15, 10 outputs each
    miners with specified pks in output must be present.
    Checking whether requested withdrawal is valid or not must be done before calling this function!
    Raises Exception if node returns error.
    :param outputs: list of tuples (pk, value, id), value must be erg * 1e9. so for 10 ergs, value is 10e9;
    id: id of balance object with status pending_withdrawal associated with this item
    :param subtract_fee: whether to subtract fee from each output or not
    :return: nothing
    :effect: creates balance for miners specified by each pk. must remove pending balances in any case
    """
    logger.info('withdrawing for {} requests'.format(len(outputs)))
    pk_to_miner = {
        miner.public_key: miner for miner in Miner.objects.filter(public_key__in=[x[0] for x in outputs])
    }

    # this function removes pending_withdrawal balances related to the outputs
    def remove_pending_balances(outputs):
        Balance.objects.filter(pk__in=[x[2] for x in outputs]).delete()

    # if output is empty
    if not outputs:
        logger.debug('quiting sending txs, no request.')
        return

    pk_to_address = {
        miner.public_key: get_miner_payment_address(miner) for _, miner in pk_to_miner.items()
    }

    pk_to_height = {
        bal.miner.public_key: (bal.min_height, bal.max_height)
        for bal in Balance.objects.filter(pk__in=[x[2] for x in outputs])
    }

    invalid_requests = [(pk, amount, obj_id) for pk, amount, obj_id in outputs if pk_to_address[pk] is None]
    if invalid_requests:
        logger.error("some miners don't have valid payment addresses!, {}".format([x[0] for x in invalid_requests]))

    remove_pending_balances(invalid_requests)
    outputs = [(pk, amount, obj_id) for pk, amount, obj_id in outputs if pk_to_address[pk] is not None]

    MAX_NUMBER_OF_OUTPUTS = Configuration.objects.MAX_NUMBER_OF_OUTPUTS
    TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE

    # getting all unspent boxes
    res = node_request('wallet/boxes/unspent')
    if res['status'] != 'success':
        logger.critical('can not retrieve boxes from node. quiting sending txs, {}.'.format(res))
        remove_pending_balances(outputs)
        return

    boxes = res['response']
    logger.debug('boxes to use potentially for generating txs len: {}'.format(len(boxes)))
    # creating chunks of size MAX_NUMBER_OF_OUTPUT from outputs

    to_use_box_ind = 0
    # generate and send transaction for each chunk
    for chuck_start in range(0, len(outputs), MAX_NUMBER_OF_OUTPUTS):
        chunk = outputs[chuck_start:chuck_start + MAX_NUMBER_OF_OUTPUTS]
        needed_erg = sum(x[1] for x in chunk)
        needed_erg += TRANSACTION_FEE if not subtract_fee else 0
        to_use_boxes = []
        to_use_boxes_value_sum = 0
        # take enough boxes for this chunk value sum
        while to_use_box_ind < len(boxes) and to_use_boxes_value_sum < needed_erg:
            box = boxes[to_use_box_ind]
            res = node_request(urljoin('utxo/byIdBinary/', box['box']['boxId']))
            if res['status'] != 'success':
                logger.critical('can not retrieve box info from node, box: {}, response: {}. quiting sending txs.'
                                .format(box, res))
                to_use_box_ind += 1
                remove_pending_balances(outputs[chuck_start:])
                return

            byte = res['response']['bytes']
            to_use_boxes.append(byte)
            to_use_boxes_value_sum += box['box']['value']
            to_use_box_ind += 1

        if to_use_boxes_value_sum < needed_erg:
            logger.critical('not enough ergs for withdrawal! quiting.')
            remove_pending_balances(outputs[chuck_start:])
            return

        data = {
            'requests': [{
                'address': pk_to_address[x[0]],
                'value': x[1] - (TRANSACTION_FEE if subtract_fee else 0)
            } for x in chunk],
            'fee': TRANSACTION_FEE,
            'inputsRaw': to_use_boxes
        }

        res = None
        try:
            res = node_request('wallet/transaction/send', data=data, request_type='post')
        except Exception as e:
            logger.critical('error while sending payments, {}.'.format(e))

        remove_pending_balances(chunk)
        if res['status'] == 'success':
            logger.info('tx was sent successfully, {}.'.format(res))
            balances = [Balance(miner=pk_to_miner[pk], balance=-value, status="withdraw",
                                tx_id=res['response'], min_height=pk_to_height[pk][0],
                                max_height=pk_to_height[pk][1])for pk, value, _ in chunk]
            Balance.objects.bulk_create(balances)

        else:
            logger.critical('can not create and send the transaction {}, response: {}'.format(data, res))
            remove_pending_balances(outputs[chuck_start + MAX_NUMBER_OF_OUTPUTS:])
            logger.error('quiting sending remaining transactions.')
            return


@app.task
def immature_to_mature():
    """
    function to convert immature balances to mature ones periodically if their confirmation_num
    is at least some threshold
    :return: nothing
    :effect: changes status of specified balances to mature
    """
    logger.info('running immature to mature task.')

    def make_share_orphaned(share):
        """
        makes a share orphaned
        :param share: the share that needs to be orphaned
        :return: None
        """
        share.is_orphaned = True
        share.save()

        if share.status == 'solved':
            # creating equivalent mature balances with negative balance
            balances = Balance.objects.filter(share=share, status='immature')
            duplicate_balances = [b for b in balances]
            balances.update(status='mature')
            for b in duplicate_balances:
                b.id = None
                b.balance = -b.balance
                b.status = 'mature'

            Balance.objects.bulk_create(duplicate_balances)

    block_threshold = 3
    # getting current height
    res = node_request('info')
    if res['status'] != 'success':
        logger.critical('can not get info from node! quiting immature_to_mature.')
        return

    res = res['response']
    current_height = res['fullHeight']
    CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH

    # getting all shares with immature balances which have been created at least in CONFIRMATION_LENGTH block ago
    shares = Share.objects.filter(balance__status="immature", block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                  status='solved', is_orphaned=False).distinct().order_by('created_at')
    # no shares to do anything for
    if shares.count() == 0:
        return

    first_one = shares.first()
    first_valid_share = RewardAlgorithm.get_instance().get_beginning_share(first_one.created_at)
    all_considered_shares = Share.objects.filter(created_at__lte=shares.last().created_at,
                                                 created_at__gte=first_valid_share.created_at,
                                                 status__in=['solved', 'valid'], is_orphaned=False)

    threshold = all_considered_shares.aggregate(max=Max('block_height'), min=Min('block_height'))
    res = node_request('blocks/chainSlice', params={'fromHeight': threshold['min'] - block_threshold,
                                                    'toHeight': threshold['max'] + block_threshold})
    if res['status'] != 'success':
        logger.critical('Can not get headers.json from node, exiting immature_to_mature!')
        return

    headers = res['response']
    ids = set(h['id'] for h in headers)

    for share in all_considered_shares:
        if share.parent_id not in ids or len(ids.intersection(share.next_ids)) > 0:
            logger.debug('we orphan share {} because either its parent is not on the chain or'
                         'some of its parents child are present.'.format(share.share))
            # must be orphaned
            make_share_orphaned(share)

    q = Q()
    shares = Share.objects.filter(balance__status="immature", block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                  status='solved', is_orphaned=False).distinct().order_by('block_height')
    for share in shares:
        txt_res = node_request('wallet/transactionById', params={'id': share.transaction_id})
        if txt_res['status'] != 'success':
            res = txt_res['response']
            if 'error' in res and res['error'] == 404 and 'reason' in res and res['reason'] == 'not-found':
                # transaction is not in the blockchain
                logger.debug('tx {} is not present so we orphan share {}.'.format(share.transaction_id, share.share))
                make_share_orphaned(share)

            logger.error('we ignore share: {}.'.format(share.share))
            continue

        txt_res = txt_res['response']
        tx_height = txt_res['inclusionHeight']

        tx_height_ok = tx_height == share.block_height
        tx_pow_ok = False
        if tx_height_ok:
            header = node_request('blocks/chainSlice',
                                  params={'fromHeight': share.block_height, 'toHeight': share.block_height})
            if header['status'] != 'success' or len(header['response']) == 0:
                logger.error("could not verify solved share at {} because could not get header from node,"
                             "skipping this share for now".format(share.block_height))
                continue

            header = header['response'][0]
            pow = header['powSolutions']
            to_hash = pow['w'] + pow['n'] + str(pow['d'])
            pow_identity = blake2b(to_hash.encode('utf-8'), digest_size=32).hexdigest()
            tx_pow_ok = pow_identity == share.pow_identity

        if not tx_pow_ok or not tx_height_ok:
            logger.debug('solved share was not verified because either height or pow dont match, share height: {}, {}'
                         .format(share.block_height, tx_height))
            make_share_orphaned(share)
            continue

        num_confirmations = txt_res['numConfirmations']

        if num_confirmations >= CONFIRMATION_LENGTH:
            logger.info('all ok for share {}, we run reward algorithm.'.format(share.share))
            RewardAlgorithm.get_instance().perform_logic(share)
            q |= Q(status="immature", share=share)

        else:
            logger.debug('share {} confirmation number is {}, we expect {}, ignoring this share for now.'.
                         format(share.share, num_confirmations, CONFIRMATION_LENGTH))

    if len(q) > 0:
        logger.info('maturing all balances related to ok solved shares, len: {}.'.format(len(q)))
        Balance.objects.filter(q).update(status="mature")


@app.task
def aggregate():
    """
    aggregates balances and shares
    shares before some round specified in settings will be aggregated
    aggregated shares before some round specified in settings will be deleted
    balances before some round specified in settings will be aggregated
    all deleted shares, balances and aggregated shares will be saved in their respective files
    """
    logger.info('running aggregate task.')
    # create necessary folders if not exist
    for file in [settings.BALANCE_DETAIL_FOLDER, settings.SHARE_DETAIL_FOLDER, settings.SHARE_AGGREGATE_FOLDER]:
        Path(os.path.join(settings.AGGREGATE_ROOT_FOLDER, file)).mkdir(parents=True, exist_ok=True)

    # output files
    date = str(datetime.now())
    shares_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                      settings.SHARE_DETAIL_FOLDER, date) + '.csv'
    shares_aggregate_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                         settings.SHARE_AGGREGATE_FOLDER, date) + '.csv'
    balance_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                       settings.BALANCE_DETAIL_FOLDER, date) + '.csv'

    solved = Share.objects.filter(status='solved').order_by('-created_at')
    # if there are balances to be aggregated
    if solved.count() > settings.KEEP_BALANCE_WITH_DETAIL_NUM:
        balance_solved_share = solved[settings.KEEP_BALANCE_WITH_DETAIL_NUM]
        bal_mature_aggregation = Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                                        status="mature") \
            .values('miner').annotate(balance=Sum('balance'), num=Count('id'))
        bal_withdraw_aggregation = Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                                          status="withdraw") \
            .values('miner').annotate(balance=Sum('balance'), num=Count('id'))

        # aggregate balances
        new_balances = [Balance(miner_id=bal['miner'], balance=bal['balance'], status="mature")
                        for bal in bal_mature_aggregation]
        new_balances += [Balance(miner_id=bal['miner'], balance=bal['balance'], status="withdraw")
                         for bal in bal_withdraw_aggregation]

        # removing previous balances and creating new aggregated ones
        with transaction.atomic():
            to_delete_balances = Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                                        status__in=["mature", "withdraw"])
            logger.info('we are going to delete {} balances.'.format(to_delete_balances.count()))
            to_delete_balances.to_csv(balance_detail_file)
            to_delete_balances.delete()
            logger.info('we create {} new balances.'.format(len(new_balances)))
            Balance.objects.bulk_create(new_balances)

    # nothing to do, we should keep all shares with detail
    if solved.count() <= settings.KEEP_SHARES_WITH_DETAIL_NUM:
        logger.info('there is nothing to aggregate with shares. quiting aggregate task.')
        return

    # aggregating shares
    statuses = ['valid', 'invalid', 'repetitious']
    with transaction.atomic():
        aggregated_shares = []
        last_share = solved[settings.KEEP_SHARES_WITH_DETAIL_NUM]
        to_be_aggregated = solved.filter(created_at__lte=last_share.created_at,
                                         is_aggregated=False)
        logger.info('{} solved shares can be aggregated.'.format(to_be_aggregated.count()))

        # nothing to do
        if to_be_aggregated.count() == 0:
            logger.info('there is nothing to aggregate with shares. quiting aggregate task.')
            return

        will_be_aggregated = Share.objects.filter(created_at__lte=to_be_aggregated.first().created_at,
                                                  status__in=statuses)
        logger.info('{} shares will be aggregated.'.format(will_be_aggregated.count()))
        will_be_aggregated.to_csv(shares_detail_file)
        # for each round
        for ind, share in enumerate(to_be_aggregated):
            miner_to_shares = dict()
            # for each status
            for status in statuses:
                # filtering all shares in this round
                shares = Share.objects.filter(created_at__lte=share.created_at, status=status) \
                    .values('miner').annotate(count=Count('status'), difficulty=Sum('difficulty'))
                if ind + 1 < to_be_aggregated.count():
                    nxt_share = to_be_aggregated[ind + 1]
                    shares = Share.objects.filter(created_at__lte=share.created_at,
                                                  created_at__gte=nxt_share.created_at, status=status) \
                        .values('miner').annotate(count=Count('status'), difficulty=Sum('difficulty'))

                # updating info for this round
                for cur_share in shares:
                    pk = cur_share['miner']
                    if pk not in miner_to_shares:
                        miner_to_shares[pk] = {'valid': 0, 'invalid': 0,
                                               'repetitious': 0, 'difficulty_sum': 0}

                    miner_to_shares[pk][status] = cur_share['count']
                    miner_to_shares[pk]['difficulty_sum'] += cur_share['difficulty']

            # adding this round objects for later bulk_creation
            aggregated_shares += [
                AggregateShare(miner_id=pk, valid_num=val['valid'], invalid_num=val['invalid'],
                               repetitious_num=val['repetitious'], difficulty_sum=val['difficulty_sum'],
                               solved_share=share)
                for pk, val in miner_to_shares.items()
            ]

        # create aggregate objects
        logger.info('we create AggregatedShare objects, {}.'.format(len(aggregated_shares)))
        AggregateShare.objects.bulk_create(aggregated_shares)

        # remove detail objects
        cur_delete = Share.objects.filter(created_at__lte=to_be_aggregated.first().created_at, status__in=statuses)
        logger.info('we remove all aggregated shares: {}.'.format(cur_delete.count()))
        cur_delete.delete()

        # update solved shares to aggregate
        to_be_aggregated.update(is_aggregated=True)

    # removing old aggregated shares
    if solved.count() > settings.KEEP_SHARES_WITH_DETAIL_NUM + settings.KEEP_SHARES_AGGREGATION_NUM:
        last_share = solved[settings.KEEP_SHARES_WITH_DETAIL_NUM + settings.KEEP_SHARES_AGGREGATION_NUM]
        to_be_deleted = AggregateShare.objects.filter(solved_share__created_at__lte=last_share.created_at)
        logger.info('we remove aggregated shares {}.'.format(to_be_deleted.count()))

        to_be_deleted.to_csv(shares_aggregate_file)
        to_be_deleted.delete()

    else:
        logger.info('no aggregated share to be deleted. done aggregating.')


@app.task
def get_ergo_price():
    """
    gets ergo price in usd and btc and save them in DB
    """
    try:
        res = CoinGeckoAPI().get_price(ids='ergo', vs_currencies=['usd', 'btc'])
        usd_price = res['ergo']['usd']
        btc_price = res['ergo']['btc']
        usd = ExtraInfo.objects.filter(key='ERGO_PRICE_USD').first()
        btc = ExtraInfo.objects.filter(key='ERGO_PRICE_BTC').first()

        if usd:
            logger.info('updating ergo price in usd.')
            usd.value = str(usd_price)
            usd.save()
        else:
            ExtraInfo.objects.create(key='ERGO_PRICE_USD', value=str(usd_price))
            logger.info('created ergo price in usd.')

        if btc:
            logger.info('updating ergo price in btc.')
            btc.value = str(btc_price)
            btc.save()
        else:
            ExtraInfo.objects.create(key='ERGO_PRICE_BTC', value=str(btc_price))
            logger.info('created ergo price in usd.')

    except Exception as e:
        logger.error('problem getting ergo price, {}.'.format(e))


@app.task
def periodic_verify_blocks():
    """
    A periodic task for checking transaction of shares to see if the transaction is valid,
     set transaction_valid True in case it is valid otherwise set False.
    """
    logger.info('running verify blocks task.')
    data_node = node_request('info')
    if data_node['status'] != 'success':
        logger.critical('can not get info from node! exiting.')
        return

    height = data_node['response']['fullHeight'] - 3

    # Get blocks solved lower than height with flag transaction_valid None
    shares = Share.objects.filter(
        Q(block_height__lte=height),
        Q(status='solved'),
        Q(transaction_valid=None)
    )
    # Check should be there is transaction_id in the wallet and at the same height
    for share in shares:
        data_node = node_request('wallet/transactionById', params={'id': share.transaction_id})
        if data_node['status'] == 'success':
            tx_height = data_node['response'][0]['inclusionHeight']
            if tx_height == share.block_height:
                logger.info('tx is valid.')
                share.transaction_valid = True
            else:
                logger.debug('tx {} is invalid, tx height: {}, share height: {}.'.format(tx_height, share.block_height,
                                                                                         share.transaction_id))
                share.transaction_valid = False

        elif data_node['status'] == 'not-found':
            logger.debug('tx {} is invalid, tx is not present, response: {}.'.format(share.transaction_id,
                                                                                     data_node))
            share.transaction_valid = False
        else:
            logger.error("got non 200 response from node while getting txs info by id {}, res: {}.".
                         format(share.transaction_id, data_node))

    logger.info('bulk updating transaction_valid field of shares, len: {}.'.format(shares.count()))
    Share.objects.bulk_update(shares, ['transaction_valid'])
    logger.info('done verifying blocks.')


@app.task
def periodic_calculate_hash_rate():
    """
    A periodic task for calculate hash_rate of network in pool in Half-hour.
    """
    logger.info('running calculating hash rate task')
    node_data = node_request('info')
    if node_data['status'] != 'success':
        logger.error('can not get info from node! exiting.')
        return
    to_height = int(node_data['response']['fullHeight'])
    i = 1
    network_difficulty = 0
    time_period = timezone.now() - timedelta(seconds=settings.PERIOD_DIAGRAM)
    # Calculate hash_rate of network with getting last block between now time and past PERIOD_DIAGRAM
    time_flag = True
    while time_flag:
        # Get blocks from node with for calculate hash_rate in PERIOD_DIAGRAM
        from_height = to_height - (settings.LIMIT_NUMBER_BLOCK * i)
        node_data = node_request('blocks/chainSlice', params={
            "fromHeight": from_height - 1,
            "toHeight": to_height
        })
        if node_data['status'] != 'success':
            logger.error("Can not resolve blocks from Node! exiting.")
            return
        items = list(node_data.get('response'))
        if not items:
            return
        items.reverse()
        for item in items:
            # Check time stamp of blocks that there is in time_period
            if time_period.timestamp() < (item['timestamp']/1000):
                network_difficulty += int(item['difficulty'])
            else:
                time_flag = False
        i += 1
        to_height = from_height

    # Calculate HashRate of pool
    pool_difficulty = Share.objects.aggregate(sum_total_difficulty=Sum('difficulty', filter=Q(
        created_at__gte=time_period
    ) & Q(
        status__in=['valid', 'solved']
    )))
    # Save hash_rate of network and pool between now time and past PERIOD_DIAGRAM
    HashRate.objects.create(
        network=int(network_difficulty / settings.PERIOD_DIAGRAM) or 1,
        pool=int((pool_difficulty.get("sum_total_difficulty") or 0) / settings.PERIOD_DIAGRAM) or 1
    )
    logger.info('done calculating hash rate of pool and network.')


@app.task(bind=True, max_retries=settings.NUMBER_OF_RETRIES_RUN_TASK)
def send_support_email(self, subject, message):
    num_tried = 0
    # after a problem arises tries to call logger.error the size of NUMBER_OF_LOG
    try:
        num_tried += 1
        send_mail(
            'Support-Email: ' + subject,
            message,
            settings.SENDER_EMAIL_ADDRESS,
            settings.RECEIVERS_EMAIL_ADDRESS
        )
        logger.info("send information of form support to admin system")
        return
    except TypeError as e:
        logger.error("failed send email to admin system, with this information: {}".format(message))
        logger.error(e)
    except:
        logger.error("failed send email to admin system, because can't connect to SMTP server,"
                     " with this information: {}".format(message))
        self.retry(countdown=settings.NUMBER_START_EXPONENTIAL_RETRIES ** self.request.retries)
