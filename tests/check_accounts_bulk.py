"""Ответ `modules.accounts.add_accounts_bulk`: новые аккаунты против перезаписанных.

раньше существующий username ложился в `added` так же, как новый, и морда
писала «Добавлено аккаунтов: N», хотя строка со старым логином молча меняла
пароль, почту и 2FA. Теперь перезапись уходит в `updated` со списком заменённых
полей, а ключа «updated» в ответе нет, когда перезаписей не было.

accounts.json не трогается: подменяется путь на временный каталог.

    Run the corresponding check in tests/.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import accounts  # noqa: E402

T16 = "JBSWY3DPEHPK3PXP"
T26 = "KRSXG5CTMVRXEZLU"

failures = []


def expect(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name + (f" — {extra}" if extra else ""))
    if not cond:
        failures.append(name)


tmp = tempfile.TemporaryDirectory()
accounts.ACCOUNTS_FILE = Path(tmp.name) / "accounts.json"


def stored():
    raw = json.loads(accounts.ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return {a["username"]: a for a in raw["accounts"]}


# 1. вставка только новых: ключа updated нет, все имена в added
first = accounts.add_accounts_bulk("\n".join([
    f"kate1993:Test!Password9:{T16}",
    f"mailbox@example.invalid|anna2024|MailPass99|US|{T26}",
]))
expect("только новые: ключи added+errors", set(first) == {"added", "errors"}, str(sorted(first)))
expect("только новые: все имена в added",
       first["added"] == ["kate1993", "anna2024"], str(first["added"]))
expect("только новые: ошибок нет", first["errors"] == [], str(first["errors"]))

# 2. строки легли в файл (почта у anna2024 — из строки). Регион из строки не
#    берётся с f40b033: продавец пишет в строке что угодно, настоящий регион —
#    из кук сессии TikTok (store-country-code), см. accounts.list_accounts
rows = stored()
expect("в файле два аккаунта", sorted(rows) == ["anna2024", "kate1993"], str(sorted(rows)))
expect("регион из строки не берётся", not rows["anna2024"].get("region"),
       str(rows["anna2024"].get("region")))
expect("почта из строки", rows["anna2024"].get("email") == "mailbox@example.invalid")
expect("2FA из строки", rows["anna2024"].get("totp_secret") == T26)

# 3. повторная вставка: два перезаписанных и один новый, битая строка в errors
second = accounts.add_accounts_bulk("\n".join([
    f"kate1993:NewPass99:{T16}",
    f"anna2024:OtherPass1|GB|{T26}",
    f"fresh.user:pass1234:{T16}",
    "мусор",
]))
expect("повторная вставка: набор ключей другой",
       set(second) == {"added", "updated", "errors"}, str(sorted(second)))
expect("повторная вставка: в added только новый",
       second["added"] == ["fresh.user"], str(second["added"]))
replacements = {u["username"]: u["replaced"] for u in second["updated"]}
expect("kate1993: заменён только пароль",
       replacements.get("kate1993") == ["password"], str(replacements.get("kate1993")))
expect("anna2024: заменён только пароль (регион из строки не берётся)",
       replacements.get("anna2024") == ["password"],
       str(replacements.get("anna2024")))
expect("битая строка в errors", [e["line"] for e in second["errors"]] == [4],
       str(second["errors"]))

# 4. перезапись не потеряла поля, которых в строке не было
rows = stored()
expect("почта у anna2024 сохранилась", rows["anna2024"].get("email") == "mailbox@example.invalid")
expect("2FA у anna2024 не замена (та же)", rows["anna2024"].get("totp_secret") == T26)
expect("регион из второй строки тоже не записан", not rows["anna2024"].get("region"))
expect("пароль заменён", rows["kate1993"].get("password") == "NewPass99")
expect("всего аккаунтов три", sorted(rows) == ["anna2024", "fresh.user", "kate1993"],
       str(sorted(rows)))

# 5. секретов в ответе нет: ошибка называет номер и причину, но не строку
#    (в строке пароль и 2FA-секрет), а неразобранная строка была одна — 4-я
blob = json.dumps(second, ensure_ascii=False)
expect("в errors только line и reason",
       all(set(e) == {"line", "reason"} for e in second["errors"]), str(second["errors"]))
expect("содержимого строк с секретами в ответе нет",
       "NewPass99" not in blob and T16 not in blob and T26 not in blob, blob)

print()
if failures:
    print(f"ПРОВАЛ: {len(failures)}")
else:
    print("ок: ответ различает новые и перезаписанные")
sys.exit(1 if failures else 0)
