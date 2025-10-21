import argparse
from db_utils import add_transaction, list_alerts, list_transactions, list_devices

def cmd_add_transaction(args):
    txn_id, alerts = add_transaction(
        account_id=args.account,
        merchant_id=args.merchant,
        amount=args.amount,
        currency=args.currency,
        status=args.status,
        fingerprint=args.fingerprint,
        device_label=args.device_label,
    )
    print(f"Inserted transaction #{txn_id} (acct={args.account}, merch={args.merchant}, amt={args.amount:.2f} {args.currency})")
    if args.fingerprint:
        print(f" linked device fingerprint='{args.fingerprint}' label='{args.device_label or ''}'")
    if alerts:
        print("Alert(s) created:")
        for a in alerts:
            print(f"  - Alert #{a[0]} | rule={a[1]} | sev={a[2]} | status={a[3]} | at={a[4]} | details={a[5]}")
    else:
        print("No alerts created.")

def cmd_list_alerts(args):
    rows = list_alerts(args.limit)
    if not rows:
        print("No alerts.")
        return
    for r in rows:
        print(f"[{r['id']}] txn={r['transaction_id']} amt={r['amount']} rule={r['rule_code']} "
              f"sev={r['severity']} status={r['status']} at={r['created_ts']} "
              f"(acct={r['account_id']}, merch={r['merchant_id']}, device={r['device_id']})")

def cmd_list_transactions(args):
    rows = list_transactions(args.limit)
    if not rows:
        print("No transactions.")
        return
    for r in rows:
        print(f"[{r['id']}] acct={r['account_id']} merch={r['merchant_id']} device={r['device_id']} "
              f"amt={r['amount']} {r['currency']} status={r['status']} at={r['ts']}")

def cmd_list_devices(args):
    rows = list_devices(args.customer, args.limit)
    if not rows:
        print("No devices.")
        return
    for r in rows:
        print(f"[{r['id']}] cust={r['customer_id']} fp={r['fingerprint']} label={r['label']} "
              f"first={r['first_seen_ts']} last={r['last_seen_ts']}")

def main():
    p = argparse.ArgumentParser(description="Transaction Monitoring CLI (with device support)")
    sub = p.add_subparsers(required=True)

    p_add = sub.add_parser("add-transaction", help="Insert a transaction, link device (optional), and run rules")
    p_add.add_argument("--account", type=int, required=True)
    p_add.add_argument("--merchant", type=int, required=True)
    p_add.add_argument("--amount", type=float, required=True)
    p_add.add_argument("--currency", default="USD")
    p_add.add_argument("--status", default="approved", choices=["approved","declined","reversed"])
    p_add.add_argument("--fingerprint", help="Device fingerprint to link (optional)")
    p_add.add_argument("--device-label", help="Human label for device (optional)")
    p_add.set_defaults(func=cmd_add_transaction)

    p_alerts = sub.add_parser("list-alerts", help="List recent alerts")
    p_alerts.add_argument("--limit", type=int, default=20)
    p_alerts.set_defaults(func=cmd_list_alerts)

    p_txns = sub.add_parser("list-transactions", help="List recent transactions")
    p_txns.add_argument("--limit", type=int, default=20)
    p_txns.set_defaults(func=cmd_list_transactions)

    p_devs = sub.add_parser("list-devices", help="List devices (optionally for a customer)")
    p_devs.add_argument("--customer", type=int, default=None)
    p_devs.add_argument("--limit", type=int, default=20)
    p_devs.set_defaults(func=cmd_list_devices)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()