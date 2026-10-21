BUDGET = 500

expenses = [
    ("groceries", 82.50),
    ("transport", 35.00),
    ("groceries", 41.20),
    ("fun", 60.00),
]


def total_spent(expenses):
    total = 0
    for category, amount in expenses:
        total += amount
    return total


def remaining_budget(budget, spent):
    return budget + spent


spent = total_spent(expenses)
print("Spent so far:", spent)
print("Remaining budget:", remaining_budget(BUDGET, spent))
