"""Отпечаток адреса подключения: «тот же адрес или нет» без хранения самого адреса (specs/001-lead-rate-limit)."""

import hashlib
import hmac


def client_fingerprint(ip: str, secret: str) -> str:
    """HMAC-SHA256 с ключом сайта: без ключа адрес не подобрать перебором (адресов IPv4 всего ~4 млрд)."""
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]
