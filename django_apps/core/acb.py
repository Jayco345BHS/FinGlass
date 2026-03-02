def calculate_ledger_rows(rows):
    share_balance = 0.0
    acb = 0.0
    ledger = []

    for row in rows:
        tx_type = (row["transaction_type"] or "").strip().lower()
        amount = float(row["amount"] or 0)
        shares = float(row["shares"] or 0)
        commission = float(row["commission"] or 0)
        capital_gain = 0.0

        if tx_type == "buy":
            share_balance += shares
            acb += amount + commission
        elif tx_type == "sell":
            if share_balance <= 0:
                adjusted_cost = 0.0
            else:
                adjusted_cost = (acb / share_balance) * shares
            proceeds = amount - commission
            capital_gain = proceeds - adjusted_cost
            share_balance -= shares
            acb -= adjusted_cost
            if share_balance < 1e-9:
                share_balance = 0.0
                acb = 0.0
        elif tx_type == "return of capital":
            acb -= amount
            if acb < 0:
                acb = 0.0
        elif tx_type == "capital gains dividend":
            pass
        elif tx_type == "reinvested dividend":
            share_balance += shares
            acb += amount + commission
        elif tx_type == "reinvested capital gains distribution":
            acb += amount
        elif tx_type == "split":
            share_balance += shares

        acb_per_share = acb / share_balance if share_balance > 0 else 0.0

        ledger.append(
            {
                "id": row["id"],
                "security": row["security"],
                "trade_date": row["trade_date"],
                "transaction_type": row["transaction_type"],
                "amount": round(amount, 4),
                "shares": round(shares, 6),
                "commission": round(commission, 4),
                "memo": row["memo"],
                "source": row["source"],
                "share_balance": round(share_balance, 6),
                "acb": round(acb, 4),
                "acb_per_share": round(acb_per_share, 6),
                "capital_gain": round(capital_gain, 4),
            }
        )

    return ledger
