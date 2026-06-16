"""CLI-запуск для GitHub Actions: викликає розподіл і друкує лог у консоль Actions."""
from main import run_distribution

if __name__ == "__main__":
    result = run_distribution()
    print(result["log"])
    print()
    print(f"Партнерів: {result['partners']} | Карт: {result['cards']} | "
          f"Макс. карт на партнера: {result['max_cards_per_partner']}")
    print("✅ Готово: дані розподілено в Google Таблиці.")
