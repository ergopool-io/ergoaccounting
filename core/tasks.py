from celery import Celery
from ErgoAccounting.celery import app
from core.models import *
from core.utils import generate_and_send_transaction


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

