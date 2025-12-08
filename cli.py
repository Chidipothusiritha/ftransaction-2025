# cli.py
"""
Transaction Monitoring CLI (with device support)

Usage examples:

  python cli.py add-transaction --account 1 --merchant 2 --amount 500 \
      --currency USD --status approved --fingerprint hash_abc123 --device-label "Mac Safari"

  python cli.py list-alerts --limit 20
  python cli.py list-transactions --limit 20
  python cli.py list-devices --customer 1 --limit 10
"""

import argparse

from app import create_app
from app.db_utils import (
    get_customer_id_for_account,
    get_or_create_device,
    list_alerts,
    list_transactions,
    list_devices,
    list_alerts_for_transaction,
)
from app.services.alerts import insert_transaction


# --------- CLI command handlers ---------
def cmd_add_transaction(args):
    """
    Insert a transaction, optionally link a device by fingerprint, and run rules.
    """
    device_id = None
    if args.fingerprint:
        customer_id = get_customer_id_for_account(args.account)
        device_id = get_or_create_device(customer_id, args.fingerprint, args.device_label)

    txn_id = insert_transaction(
        account_id=args.account,
        merchant_id=args.merchant,
        device_id=device_id,
        amount=args.amount,
        currency=args.currency,
        status=args.status,
        ts_iso=None,  # you can add a --ts flag later if you want
    )

    print(
        f"Inserted transaction #{txn_id} "
        f"(acct={args.account}, merch={args.merchant}, amt={args.amount:.2f} {args.currency})"
    )

    if args.fingerprint:
        print(
            f" linked device fingerprint='{args.fingerprint}' "
            f"label='{args.device_label or ''}'"
        )

    alerts = list_alerts_for_transaction(txn_id)
    if alerts:
        print("Alert(s) created:")
        for a in alerts:
            print(
                f"  - Alert #{a['id']} | rule={a['rule_code']} | "
                f"sev={a['severity']} | status={a['status']} | "
                f"at={a['created_ts']} | details={a.get('details')}"
            )
    else:
        print("No alerts created.")


def cmd_list_alerts(args):
    rows = list_alerts(args.limit)
    if not rows:
        print("No alerts.")
        return
    for r in rows:
        print(
            f"[{r['id']}] txn={r['transaction_id']} amt={r['amount']} "
            f"rule={r['rule_code']} sev={r['severity']} status={r['status']} "
            f"at={r['created_ts']} "
            f"(acct={r['account_id']}, merch={r['merchant_id']}, device={r['device_id']})"
        )


def cmd_list_transactions(args):
    rows = list_transactions(args.limit)
    if not rows:
        print("No transactions.")
        return
    for r in rows:
        print(
            f"[{r['id']}] acct={r['account_id']} merch={r['merchant_id']} "
            f"device={r['device_id']} amt={r['amount']} {r['currency']} "
            f"status={r['status']} at={r['ts']}"
        )


def cmd_list_devices(args):
    rows = list_devices(args.customer, args.limit)
    if not rows:
        print("No devices.")
        return
    for r in rows:
        print(
            f"[{r['id']}] cust={r['customer_id']} fp={r['fingerprint']} "
            f"label={r['label']} first={r['first_seen_ts']} last={r['last_seen_ts']}"
        )


# --------- main ---------
def main():
    """
    Create the Flask app so we can reuse DB config (PGHOST, etc.),
    then run the CLI commands inside an app context so app.db + services
    work normally.
    """
    app = create_app()

    with app.app_context():
        p = argparse.ArgumentParser(
            description="Transaction Monitoring CLI (with device support)"
        )
        sub = p.add_subparsers(required=True)

        # add-transaction
        p_add = sub.add_parser(
            "add-transaction",
            help="Insert a transaction, link device (optional), and run rules",
        )
        p_add.add_argument("--account", type=int, required=True)
        p_add.add_argument("--merchant", type=int, required=True)
        p_add.add_argument("--amount", type=float, required=True)
        p_add.add_argument("--currency", default="USD")
        p_add.add_argument(
            "--status",
            default="approved",
            choices=["approved", "declined", "reversed"],
        )
        p_add.add_argument(
            "--fingerprint", help="Device fingerprint to link (optional)"
        )
        p_add.add_argument(
            "--device-label", help="Human label for device (optional)"
        )
        p_add.set_defaults(func=cmd_add_transaction)

        # list-alerts
        p_alerts = sub.add_parser("list-alerts", help="List recent alerts")
        p_alerts.add_argument("--limit", type=int, default=20)
        p_alerts.set_defaults(func=cmd_list_alerts)

        # list-transactions
        p_txns = sub.add_parser("list-transactions", help="List recent transactions")
        p_txns.add_argument("--limit", type=int, default=20)
        p_txns.set_defaults(func=cmd_list_transactions)

        # list-devices
        p_devs = sub.add_parser(
            "list-devices", help="List devices (optionally for a customer)"
        )
        p_devs.add_argument("--customer", type=int, default=None)
        p_devs.add_argument("--limit", type=int, default=20)
        p_devs.set_defaults(func=cmd_list_devices)

        args = p.parse_args()
        args.func(args)


if __name__ == "__main__":
    main()
