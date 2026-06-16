import os
import json
import traceback
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, jsonify, render_template

SHEET_URL = os.environ.get(
    "SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1WER4lgVgsS4r-KuTiaai0EOJalc-WZbeYl4EoK0yi0M",
)
WORKSHEET_NAME = os.environ.get("WORKSHEET_NAME", "Розкидати карти")
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

app = Flask(__name__)


def colnum_to_letter(n):
    result = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def try_float(x):
    try:
        return float(str(x).replace('\xa0', '').replace(' ', '').strip())
    except Exception:
        return 0.0


def get_credentials():
    """Креди з Replit Secret GOOGLE_CREDENTIALS (вміст JSON) або з credentials.json."""
    raw = os.environ.get("GOOGLE_CREDENTIALS")
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPE)
    return Credentials.from_service_account_file("credentials.json", scopes=SCOPE)


def run_distribution():
    """Виконує розподіл і записує результат у таблицю. Повертає словник зі зведенням."""
    client = gspread.authorize(get_credentials())
    ws = client.open_by_url(SHEET_URL).worksheet(WORKSHEET_NAME)

    # Очищення попередніх результатів
    ws.batch_clear([
        "C2:C", "D2:D", "J6:J", "K6:K", "L6:L",
        "M2:M", "M3:M", "M4:M", "M5:M", "M6:Z", "A100:A",
    ])

    # Дані партнерів
    data_A = ws.col_values(1)[1:]
    data_B = ws.col_values(2)[1:]

    # Дані менеджерів
    F, E, G, H = ws.col_values(6)[1:], ws.col_values(5)[1:], ws.col_values(7)[1:], ws.col_values(8)[1:]
    N = max(len(F), len(E), len(G), len(H))

    names, cards, sums = [], [], []
    for i in range(N):
        name = F[i] if i < len(F) else ""
        summ = E[i] if i < len(E) else ""
        card = G[i].strip() if i < len(G) and G[i].strip() else (H[i].strip() if i < len(H) else "")
        names.append(name)
        cards.append(card)
        sums.append(summ)

    partner_names = data_A
    partner_amounts = [try_float(x) for x in data_B]
    manager_needs = [try_float(x) for x in sums]

    matrix = [[0.0] * N for _ in range(len(partner_amounts))]
    partner_balances = partner_amounts[:]

    # Розподіл: партнер платить в ОДНУ карту, якщо влазить; великий — максимум у 2.
    partner_order = sorted(
        range(len(partner_amounts)),
        key=lambda i: partner_balances[i],
        reverse=True,
    )

    for i in partner_order:
        while partner_balances[i] >= 1:
            open_cards = [j for j in range(N) if manager_needs[j] >= 1]
            if not open_cards:
                break
            fitting = [j for j in open_cards if manager_needs[j] >= partner_balances[i]]
            if fitting:
                j = min(fitting, key=lambda j: manager_needs[j])
            else:
                j = max(open_cards, key=lambda j: manager_needs[j])
            pay = min(partner_balances[i], manager_needs[j])
            matrix[i][j] += pay
            partner_balances[i] -= pay
            manager_needs[j] -= pay

    # Колонка C
    C_column = []
    for i in range(len(partner_names)):
        lines = []
        for j in range(min(N, len(matrix[i]), len(cards))):
            val = matrix[i][j]
            if val > 0:
                lines.append(f"{cards[j]}    {int(val)} грн")
        C_column.append(["\n".join(lines) if lines else ""])

    # Колонка D
    D_column = []
    for j in range(N):
        lines = []
        for i in range(min(len(matrix), len(data_A))):
            if j < len(matrix[i]):
                val = matrix[i][j]
                if val > 0:
                    lines.append(f"{data_A[i]}    {int(val)} грн")
        D_column.append(["\n".join(lines) if lines else ""])

    ws.update(f"C2:C{1 + len(C_column)}", C_column)
    ws.update(f"D2:D{1 + len(D_column)}", D_column)

    # Матриця
    output = []
    for row in matrix:
        output.append([int(x) if x and x.is_integer() else (x if x else 0) for x in row])

    batch_size = 5
    start_row = 6
    for i in range(0, len(output), batch_size):
        batch = output[i:i + batch_size]
        end_row = start_row + len(batch) - 1
        ws.update(
            range_name=f"M{start_row}:{colnum_to_letter(12 + N)}{end_row}",
            values=batch,
            value_input_option='USER_ENTERED',
        )
        start_row = end_row + 1

    ws.update("M2", [cards])
    ws.update("M3", [names])
    ws.update("M4", [[try_float(x) for x in sums]])
    formulas = [f"={colnum_to_letter(13 + i)}4-SUM({colnum_to_letter(13 + i)}6:{colnum_to_letter(13 + i)}276)" for i in range(N)]
    ws.update(f"M5:{colnum_to_letter(12 + N)}5", [formulas], value_input_option='USER_ENTERED')

    ws.update('J6', [[p] for p in partner_names])
    ws.update('K6', [[int(x)] for x in partner_amounts])
    last_column_letter = colnum_to_letter(12 + N)
    L_formulas = [[f"=K{r}-SUM(M{r}:{last_column_letter}{r})"] for r in range(6, 6 + len(partner_names))]
    ws.update(f"L6:L{5 + len(partner_names)}", L_formulas, value_input_option='USER_ENTERED')

    # ==== ЛОГ ====
    log_lines = [f"Останній запуск: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    log_lines.append("===== \U0001F7E0 Менеджери з недоплатою =====")
    count_miss = 0
    for name, need in zip(names, manager_needs):
        if need > 0:
            log_lines.append(f"{name}: {int(need)} грн")
            count_miss += 1
    log_lines.append("===== \U0001F535 Партнери з залишком =====")
    count_bal = 0
    for name, bal in zip(partner_names, partner_balances):
        if bal > 0:
            log_lines.append(f"{name}: {int(bal)} грн")
            count_bal += 1
    log_lines.append(f"===== ✅ Усього менеджерів з недоплатою: {count_miss} =====")
    log_lines.append(f"===== ✅ Усього партнерів з залишком: {count_bal} =====")

    ws.update("A100", [["\n".join(log_lines)]])

    # скільки карт у кожного партнера (для зведення на сторінці)
    cards_per_partner = []
    for i in range(len(partner_names)):
        used = sum(1 for j in range(N) if matrix[i][j] > 0)
        if used:
            cards_per_partner.append(used)
    max_cards = max(cards_per_partner) if cards_per_partner else 0

    return {
        "ok": True,
        "partners": len(partner_amounts),
        "cards": N,
        "managers_underpaid": count_miss,
        "partners_with_balance": count_bal,
        "max_cards_per_partner": max_cards,
        "log": "\n".join(log_lines),
        "finished_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


@app.route("/")
def index():
    return render_template("index.html", sheet_url=SHEET_URL)


@app.route("/run", methods=["POST"])
def run():
    try:
        return jsonify(run_distribution())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
