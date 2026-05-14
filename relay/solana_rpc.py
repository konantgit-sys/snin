"""
SNIN Relay V2 — Solana RPC Client
Лёгкий клиент для верификации Solana-транзакций через RPC.

Использует:
- httpx для HTTP-запросов к Solana RPC
- Без solders (только JSON-RPC)
- Без балансов в relay (только верификация tx)
"""

import json
import logging
import time
import httpx

logger = logging.getLogger('solana_rpc')

# ── Config ──
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
# Helius fallback (если основной недоступен)
SOLANA_RPC_FALLBACK = "https://rpc.ankr.com/solana"
SNIN_TOKEN_MINT = None  # будет установлен при инициализации
SOLANA_TX_CACHE = {}  # cache verified tx signatures
SOLANA_TX_CACHE_TTL = 3600  # 1 hour

# SPL Token program ID
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


async def verify_transaction(signature: str, expected_receiver: str = None, expected_amount: int = None) -> dict:
    """
    Проверить Solana транзакцию по сигнатуре.
    
    Args:
        signature: Solana tx signature (base58)
        expected_receiver: ожидаемый получатель (Solana адрес)
        expected_amount: ожидаемая сумма в lamports (1 SOL = 10^9 lamports)
    
    Returns:
        dict с результатом: {"valid": bool, "reason": str, "data": dict}
    """
    # Проверка кэша
    cached = SOLANA_TX_CACHE.get(signature)
    if cached and (time.time() - cached.get("verified_at", 0)) < SOLANA_TX_CACHE_TTL:
        return cached
    
    # Пытаемся подтвердить через RPC
    result = await _query_transaction(signature)
    
    if not result.get("valid"):
        # Пробуем fallback RPC
        logger.info(f"Primary RPC failed, trying fallback for tx {signature[:16]}...")
        # Временно меняем URL
        global SOLANA_RPC_URL
        original_url = SOLANA_RPC_URL
        SOLANA_RPC_URL = SOLANA_RPC_FALLBACK
        result = await _query_transaction(signature)
        SOLANA_RPC_URL = original_url
    
    # Кэшируем
    SOLANA_TX_CACHE[signature] = result
    SOLANA_TX_CACHE[signature]["verified_at"] = time.time()
    
    return result


async def _query_transaction(signature: str) -> dict:
    """Отправить JSON-RPC запрос к Solana для получения транзакции."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",  # 1 confirmation = ~400ms
                "maxSupportedTransactionVersion": 0
            }
        ]
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(SOLANA_RPC_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Solana RPC error: {e}")
        return {"valid": False, "reason": f"RPC error: {e}", "data": None}
    
    if "error" in data:
        logger.warning(f"Solana RPC error response: {data['error']}")
        return {"valid": False, "reason": f"RPC error: {data['error'].get('message', str(data['error']))}", "data": None}
    
    if "result" not in data or data["result"] is None:
        return {"valid": False, "reason": "Transaction not found (not confirmed yet or invalid)", "data": None}
    
    tx_data = data["result"]
    
    # Проверяем статус
    if tx_data.get("meta", {}).get("err") is not None:
        err = tx_data["meta"]["err"]
        return {"valid": False, "reason": f"Transaction failed: {err}", "data": tx_data}
    
    # Успешно подтверждена
    return {"valid": True, "reason": "confirmed", "data": tx_data}


async def get_token_balance(address: str, mint: str = None) -> dict:
    """
    Получить баланс SPL токена для адреса.
    
    Args:
        address: Solana адрес
        mint: mint адрес токена (если None — ищем SNIN)
    
    Returns:
        {"balance": int, "address": str, "mint": str}
    """
    target_mint = mint or SNIN_TOKEN_MINT
    if not target_mint:
        return {"balance": 0, "address": address, "mint": None, "error": "mint not configured"}
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            address,
            {"mint": target_mint},
            {"encoding": "jsonParsed"}
        ]
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(SOLANA_RPC_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Solana RPC balance error: {e}")
        return {"balance": 0, "address": address, "mint": target_mint, "error": str(e)}
    
    if "error" in data:
        return {"balance": 0, "address": address, "mint": target_mint, "error": str(data["error"])}
    
    accounts = data.get("result", {}).get("value", [])
    if not accounts:
        return {"balance": 0, "address": address, "mint": target_mint, "token_account": None}
    
    # Берем первый аккаунт с токеном
    account = accounts[0]
    amount = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {}).get("amount", "0")
    
    return {
        "balance": int(amount),
        "address": address,
        "mint": target_mint,
        "token_account": account.get("pubkey"),
        "decimals": account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {}).get("decimals", 9)
    }


def extract_transfer_info(tx_data: dict, mint: str = None) -> dict:
    """
    Извлечь информацию о переводе из данных транзакции Solana.
    Возвращает отправителя, получателя, сумму, mint.
    """
    # Парсим инструкции транзакции
    tx = tx_data.get("transaction", {})
    message = tx.get("message", {})
    instructions = message.get("instructions", [])
    
    # Находим SPL Transfer инструкцию
    for ix in instructions:
        program = ix.get("programId", "")
        if program == TOKEN_PROGRAM_ID:  # с сомнением
            parsed = ix.get("parsed", {})
            if parsed.get("type") == "transfer":
                info = parsed.get("info", {})
                return {
                    "source": info.get("source"),
                    "destination": info.get("destination"),
                    "amount": int(info.get("amount", 0)),
                    "mint": info.get("mint"),
                    "authority": info.get("authority"),
                }
    
    # Fallback: пытаемся найти в meta
    pre_balances = tx_data.get("meta", {}).get("preTokenBalances", [])
    post_balances = tx_data.get("meta", {}).get("postTokenBalances", [])
    
    if pre_balances and post_balances:
        # Сравниваем pre и post балансы
        for pre in pre_balances:
            for post in post_balances:
                if pre.get("owner") != post.get("owner") and pre.get("mint") == post.get("mint"):
                    # Разные владельцы — перевод
                    diff = int(post.get("uiTokenAmount", {}).get("amount", 0)) - int(pre.get("uiTokenAmount", {}).get("amount", 0))
                    if diff < 0:
                        sender = pre.get("owner")
                        # Ищем получателя
                        for post2 in post_balances:
                            for pre2 in pre_balances:
                                if post2.get("owner") != pre2.get("owner") and post2.get("mint") == post.get("mint"):
                                    if post2.get("uiTokenAmount", {}).get("amount", "0") != pre2.get("uiTokenAmount", {}).get("amount", "0"):
                                        return {
                                            "source": sender,
                                            "destination": post2.get("owner"),
                                            "amount": abs(diff),
                                            "mint": pre.get("mint"),
                                        }
    
    return {"source": None, "destination": None, "amount": 0, "mint": None}


async def get_recent_priority_fee() -> int:
    """
    Получить актуальный priority fee для Solana (микро-лампорты).
    Для микро-транзакций используем static fee = 0.
    """
    return 0  # Агенты не платят priority fees — используем static


def set_mint_address(address: str):
    """Установить mint адрес SNIN токена."""
    global SNIN_TOKEN_MINT
    SNIN_TOKEN_MINT = address
    logger.info(f"SNIN token mint set: {address}")


def set_rpc_url(url: str):
    """Установить кастомный RPC URL."""
    global SOLANA_RPC_URL
    SOLANA_RPC_URL = url
    logger.info(f"Solana RPC URL set: {url}")
