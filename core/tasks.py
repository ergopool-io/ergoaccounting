import logging
from urllib.parse import urljoin

from ErgoAccounting.celery import app
from core.models import Miner, Balance, Configuration
from core.utils import node_request

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
    # miners to their balances
    pk_to_total_balance = {
        miner.public_key: 0 for miner in miners
    }

    # update miners balances
    balances = Balance.objects.filter(status__in=[2, 3])
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
            outputs.append((miner.public_key, int(balance * 1e9)))

    # call the approprate function for withdrawal
    try:
        logger.info('Periodic withdrawal for #{} miners'.format(len(outputs)))
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
    :param outputs: list of tuples (pk, value), value must be erg * 1e9. so for 10 ergs, value is 10e9
    :param subtract_fee: whether to subtract fee from each output or not
    :return: nothing
    :effect: creates balance for miners specified by each pk
    """
    # if output is empty
    if not outputs:
        return

    MAX_NUMBER_OF_OUTPUTS = Configuration.objects.MAX_NUMBER_OF_OUTPUTS
    TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE

    pk_to_miner = {
        miner.public_key: miner for miner in Miner.objects.filter(public_key__in=[x[0] for x in outputs])
    }

    # getting all unspent boxes
    res = node_request('wallet/boxes/unspent')
    if res['status'] != 'success':
        logger.critical('can not retrieve boxes from node')
        return

    boxes = res['response']
    # creating chunks of size MAX_NUMBER_OF_OUTPUT from outputs
    outputs = [outputs[i:i + MAX_NUMBER_OF_OUTPUTS] for i in range(0, len(outputs), MAX_NUMBER_OF_OUTPUTS)]

    to_use_box_ind = 0
    # generate and send transaction for each chunk
    for chunk in outputs:
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
                continue

            byte = res['response']['bytes']
            to_use_boxes.append(byte)
            to_use_boxes_value_sum += box['box']['value']
            logger.debug(box['box']['value'])
            to_use_box_ind += 1

        logger.critical(to_use_boxes_value_sum / 1e9)
        if to_use_boxes_value_sum < needed_erg:
            logger.critical('Not enough boxes for withdrawal!')
            return

        data = {
            'requests': [{
                'address': x[0],
                'value': x[1] - (TRANSACTION_FEE if subtract_fee else 0)
            } for x in chunk],
            'fee': TRANSACTION_FEE,
            'inputsRaw': to_use_boxes
        }

        # create balances with status pending_withdrawal
        balances = [Balance(miner=pk_to_miner[pk],
                            balance=-value/1e9, status=3) for pk, value in chunk]
        Balance.objects.bulk_create(balances)

        res = node_request('wallet/transaction/send', data=data, request_type='post')

        if res['status'] != 'success':
            Balance.objects.filter(id__in=[balance.id for balance in balances]).delete()
            logger.critical('can not create and send the transaction {}'.format(data))
            return

