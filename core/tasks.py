import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum, Count, Max, Min

from ErgoAccounting.celery import app
from core.models import Miner, Balance, Configuration, Share, AggregateShare, ExtraInfo
from core.serializers import BalanceSerializer, ShareSerializer, AggregateShareSerializer
from core.utils import node_request, get_miner_payment_address, RewardAlgorithm
from pycoingecko import CoinGeckoAPI

logger = logging.getLogger(__name__)


@app.task
def periodic_withdrawal():
    """
    A task which for every miner, calculates his balance and if it is above some threshold
    (whether default one or one specified by the miner), calls the generate_and_send_transaction
    to withdraw the balance.
    :return:
    """

    miners = Miner.objects.all()

    pk_to_miner = {
        miner.public_key: miner for miner in miners
    }

    # miners to their balances
    pk_to_total_balance = {
        miner.public_key: 0 for miner in miners
    }

    # update miners balances, balances with "withdraw", "pending_withdrawal" and "mature" status
    balances = Balance.objects.filter(status__in=["mature", "withdraw", "pending_withdrawal"])
    for balance in balances:
        pk_to_total_balance[balance.miner.public_key] += balance.balance

    DEFAULT_WITHDRAW_THRESHOLD = Configuration.objects.DEFAULT_WITHDRAW_THRESHOLD
    outputs = []
    # check every miners balances!
    for miner in miners:
        threshold = miner.periodic_withdrawal_amount
        if threshold is None:
            threshold = DEFAULT_WITHDRAW_THRESHOLD

        balance = pk_to_total_balance.get(miner.public_key)
        if balance >= threshold:
            # above threshold (whether default one or the one specified by the miner)
            outputs.append((miner.public_key, balance))

    # call the approprate function for withdrawal
    try:
        logger.info('Periodic withdrawal for #{} miners'.format(len(outputs)))
        # Creating balance object with pending_withdrawal status
        objects = [Balance(miner=pk_to_miner.get(pk), status="pending_withdrawal", balance=-balance) for pk, balance in
                   outputs]
        Balance.objects.bulk_create(objects)
        outputs = [(x[0], x[1], objects[i].pk) for i, x in enumerate(outputs)]
        outputs = sorted(outputs)
        generate_and_send_transaction(outputs)

    except:
        logger.critical('Could not periodically withdraw due to exception, probably in node connection')


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

    pk_to_miner = {
        miner.public_key: miner for miner in Miner.objects.filter(public_key__in=[x[0] for x in outputs])
    }

    # this function removes pending_withdrawal balances related to the outputs
    def remove_pending_balances(outputs):
        Balance.objects.filter(pk__in=[x[2] for x in outputs]).delete()

    # if output is empty
    if not outputs:
        return

    pk_to_address = {
        miner.public_key: get_miner_payment_address(miner) for _, miner in pk_to_miner.items()
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
        logger.critical('can not retrieve boxes from node')
        remove_pending_balances(outputs)
        return

    boxes = res['response']
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
                logger.critical('can not retrieve box info from node')
                to_use_box_ind += 1
                remove_pending_balances(outputs[chuck_start:])
                return

            byte = res['response']['bytes']
            to_use_boxes.append(byte)
            to_use_boxes_value_sum += box['box']['value']
            logger.debug(box['box']['value'])
            to_use_box_ind += 1

        if to_use_boxes_value_sum < needed_erg:
            logger.critical('Not enough boxes for withdrawal!')
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

        # create balances with status pending_withdrawal
        remove_pending_balances(chunk)
        balances = [Balance(miner=pk_to_miner[pk],
                            balance=-value, status="withdraw") for pk, value, _ in chunk]
        Balance.objects.bulk_create(balances)

        res = node_request('wallet/transaction/send', data=data, request_type='post')

        if res['status'] != 'success':
            Balance.objects.filter(id__in=[balance.id for balance in balances]).delete()
            logger.critical('can not create and send the transaction {}'.format(data))
            remove_pending_balances(outputs[chuck_start + MAX_NUMBER_OF_OUTPUTS:])
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
        logger.critical('can not get info from node! exiting.')
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
        logger.error('Can not get headers.json from node, exiting immature_to_mature!')
        return

    headers = res['response']
    ids = set(h['id'] for h in headers)

    for share in all_considered_shares:
        if share.parent_id not in ids or len(ids.intersection(share.next_ids)) > 0:
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
                make_share_orphaned(share)

            logger.error('can not get transaction info from node for id {}! exiting.'.format(share.transaction_id))
            continue

        txt_res = txt_res['response']
        num_confirmations = txt_res['numConfirmations']

        if num_confirmations >= CONFIRMATION_LENGTH:
            RewardAlgorithm.get_instance().perform_logic(share)
            q |= Q(status="immature", share=share)

    if len(q) > 0:
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
    # create necessary folders if not exist
    for file in [settings.BALANCE_DETAIL_FOLDER, settings.SHARE_DETAIL_FOLDER, settings.SHARE_AGGREGATE_FOLDER]:
        Path(os.path.join(settings.AGGREGATE_ROOT_FOLDER, file)).mkdir(parents=True, exist_ok=True)

    date = str(datetime.now())
    shares_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                      settings.SHARE_DETAIL_FOLDER, date) + '.json'
    shares_aggregate_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                         settings.SHARE_AGGREGATE_FOLDER, date) + '.json'
    balance_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                       settings.BALANCE_DETAIL_FOLDER, date) + '.json'
    solved = Share.objects.filter(status='solved').order_by('-created_at')
    if solved.count() > settings.KEEP_BALANCE_WITH_DETAIL_NUM:
        balance_solved_share = solved[settings.KEEP_BALANCE_WITH_DETAIL_NUM]
        bal_mature_aggregation = Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                                        status="mature") \
            .values('miner').annotate(balance=Sum('balance'), num=Count('id'))
        bal_withdraw_aggregation = Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                                          status="withdraw") \
            .values('miner').annotate(balance=Sum('balance'), num=Count('id'))

        new_balances = [Balance(miner_id=bal['miner'], balance=bal['balance'], status="mature")
                        for bal in bal_mature_aggregation]
        new_balances += [Balance(miner_id=bal['miner'], balance=bal['balance'], status="withdraw")
                         for bal in bal_withdraw_aggregation]

        # removing previous balances and creating new aggregated ones
        with transaction.atomic():
            to_delete_balances = Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                                        status__in=["mature", "withdraw"])
            details = [str(BalanceSerializer(balance).data) for balance in to_delete_balances]
            to_delete_balances.delete()
            Balance.objects.filter(created_at__lte=balance_solved_share.created_at,
                                   status__in=["mature", "withdraw"]).delete()
            Balance.objects.bulk_create(new_balances)

            if len(details) > 0:
                with open(balance_detail_file, 'a') as file:
                    file.write('\n'.join(details) + '\n')

        # nothing to do
        if solved.count() <= settings.KEEP_SHARES_WITH_DETAIL_NUM:
            return

        # aggregating shares
        statuses = ['valid', 'invalid', 'repetitious']
        with transaction.atomic():
            aggregated_shares = []
            last_share = solved[settings.KEEP_SHARES_WITH_DETAIL_NUM]
            to_be_aggregated = solved.filter(created_at__lte=last_share.created_at,
                                             is_aggregated=False)

            # nothing to do
            if to_be_aggregated.count() == 0:
                return

            will_be_aggregated = Share.objects.filter(created_at__lte=to_be_aggregated.first().created_at,
                                                      status__in=statuses)
            details = [str(ShareSerializer(share).data) for share in will_be_aggregated]
            for ind, share in enumerate(to_be_aggregated):
                miner_to_shares = dict()
                for status in statuses:
                    shares = Share.objects.filter(created_at__lte=share.created_at, status=status) \
                        .values('miner').annotate(count=Count('status'), difficulty=Sum('difficulty'))
                    if ind + 1 < to_be_aggregated.count():
                        nxt_share = to_be_aggregated[ind + 1]
                        shares = Share.objects.filter(created_at__lte=share.created_at,
                                                      created_at__gte=nxt_share.created_at, status=status) \
                            .values('miner').annotate(count=Count('status'), difficulty=Sum('difficulty'))

                    for cur_share in shares:
                        pk = cur_share['miner']
                        if pk not in miner_to_shares:
                            miner_to_shares[pk] = {'valid': 0, 'invalid': 0,
                                                   'repetitious': 0, 'difficulty_sum': 0}

                        miner_to_shares[pk][status] = cur_share['count']
                        miner_to_shares[pk]['difficulty_sum'] += cur_share['difficulty']

                aggregated_shares += [
                    AggregateShare(miner_id=pk, valid_num=val['valid'], invalid_num=val['invalid'],
                                   repetitious_num=val['repetitious'], difficulty_sum=val['difficulty_sum'],
                                   solved_share=share)
                    for pk, val in miner_to_shares.items()
                ]

            # create aggregate objects
            AggregateShare.objects.bulk_create(aggregated_shares)

            # remove detail objects
            Share.objects.filter(created_at__lte=to_be_aggregated.first().created_at, status__in=statuses).delete()

            # update solved shares to aggregate
            to_be_aggregated.update(is_aggregated=True)

            # writing details to file
            if len(details) > 0:
                with open(shares_detail_file, 'a') as file:
                    file.write('\n'.join(details) + '\n')

        # removing old aggregated shares
        if solved.count() > settings.KEEP_SHARES_WITH_DETAIL_NUM + settings.KEEP_SHARES_AGGREGATION_NUM:
            last_share = solved[settings.KEEP_SHARES_WITH_DETAIL_NUM + settings.KEEP_SHARES_AGGREGATION_NUM]
            to_be_deleted = AggregateShare.objects.filter(solved_share__created_at__lte=last_share.created_at)

            aggregated = [str(AggregateShareSerializer(aggregateShare).data) for aggregateShare in to_be_deleted]
            to_be_deleted.delete()
            # writing aggregated shares to file
            if len(aggregated) > 0:
                with open(shares_aggregate_file, 'a') as file:
                    file.write('\n'.join(aggregated) + '\n')


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

    except Exception as ex:
        print(ex)
        logger.error('problem getting ergo price!')
