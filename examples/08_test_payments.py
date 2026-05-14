"""
Unit-тесты для NIP-XX: Solana Payments
6 кейсов из Phase 1 Plan
"""
import asyncio, json, time, hashlib, sys, unittest, logging
sys.path.insert(0, '/home/agent/data/sites/relay')

logging.disable(logging.CRITICAL)

from snin_payments import handle_snin_payment, handle_balance_request, init_payments, get_seen_tx_count
from nostr.key import PrivateKey
from nostr.event import Event as NostrEvent

# ⚠️ Установи CRYTER_NSEC и ANTON_PUBKEY в окружении
CRYTER_NSEC = os.getenv("CRYTER_NSEC", "nsec1...ВАШ_NSEC...")
ANTON_PUBKEY = os.getenv("ANTON_PUBKEY", "c2cc7057d9185e2d87aa27c74e881e812ea92e53aff5fe5a265872eda2484ff4")
FAKE_SOLANA_TX = "5Ko9" + "a" * 40

def make_event(content: dict, tags: list, kind=30000) -> dict:
    """Создать подписанный kind:30000"""
    key = PrivateKey.from_nsec(CRYTER_NSEC)
    event = NostrEvent(
        public_key=key.public_key.hex(),
        content=json.dumps(content),
        kind=kind,
        tags=tags,
        created_at=int(time.time()) - 5
    )
    key.sign_event(event)
    return {
        "id": event.id, "pubkey": event.public_key,
        "created_at": event.created_at, "kind": event.kind,
        "tags": event.tags, "content": event.content, "sig": event.signature
    }

class TestSolanaPayments(unittest.TestCase):
    
    def setUp(self):
        init_payments(fee_address="7Df9Kf5qQKNmPYKnkYcXoG5nRJjxPqxNsdPWMnNvaZFG")
    
    # ── ТЕСТ 1: Валидный kind:30000 → REJECT (нет реальной Solana tx) ──
    def test_1_valid_format_no_solana_tx(self):
        """kind:30000 с валидной структурой, но без solana_tx"""
        result = asyncio.run(handle_snin_payment(make_event(
            {"amount": 100, "memo": "test", "token": "SNIN"},
            [["p", ANTON_PUBKEY]]
        )))
        self.assertFalse(result.get("accepted"))
        self.assertIn("missing required", result.get("reason", ""))
        print(f"✅ ТЕСТ 1: {result['reason']}")
    
    # ── ТЕСТ 2: kind:30000 с несуществующей Solana tx → REJECT ──
    def test_2_fake_solana_tx(self):
        """kind:30000 с фейковой solana_tx → reject от RPC"""
        result = asyncio.run(handle_snin_payment(make_event(
            {"amount": 100, "memo": "test", "token": "SNIN"},
            [["p", ANTON_PUBKEY], ["solana_tx", FAKE_SOLANA_TX]]
        )))
        self.assertFalse(result.get("accepted"))
        self.assertIn("RPC error", result.get("reason", ""))
        print(f"✅ ТЕСТ 2: RPC reject (ожидаемо — нет реальной tx)")
    
    # ── ТЕСТ 3: kind:30000 с истёкшим expiration → REJECT ──
    def test_3_expired(self):
        """kind:30000 с просроченным expiration"""
        result = asyncio.run(handle_snin_payment(make_event(
            {"amount": 100, "memo": "expired", "token": "SNIN"},
            [["p", ANTON_PUBKEY], ["solana_tx", FAKE_SOLANA_TX],
             ["expiration", str(int(time.time()) - 3600)]]
        )))
        self.assertFalse(result.get("accepted"))
        self.assertIn("expired", result.get("reason", ""))
        print(f"✅ ТЕСТ 3: {result['reason']}")
    
    # ── ТЕСТ 4: kind:30000 без amount → REJECT ──
    def test_4_no_amount(self):
        """kind:30000 без amount"""
        result = asyncio.run(handle_snin_payment(make_event(
            {"memo": "no amount"},
            [["p", ANTON_PUBKEY], ["solana_tx", FAKE_SOLANA_TX]]
        )))
        self.assertFalse(result.get("accepted"))
        self.assertIn("positive", result.get("reason", ""))
        print(f"✅ ТЕСТ 4: {result['reason']}")
    
    # ── ТЕСТ 5: kind:30000 с amount = 0 → REJECT ──
    def test_5_zero_amount(self):
        """kind:30000 с amount=0"""
        result = asyncio.run(handle_snin_payment(make_event(
            {"amount": 0, "memo": "zero"},
            [["p", ANTON_PUBKEY], ["solana_tx", FAKE_SOLANA_TX]]
        )))
        self.assertFalse(result.get("accepted"))
        self.assertIn("positive", result.get("reason", ""))
        print(f"✅ ТЕСТ 5: {result['reason']}")
    
    # ── ТЕСТ 6: kind:30001 balance request (проверяем структуру ответа) ──
    def test_6_balance_request_structure(self):
        """kind:30001 → kind:30002 с правильной структурой"""
        key = PrivateKey.from_nsec(CRYTER_NSEC)
        event = make_event(
            {"token": "SNIN"},
            [["relay", "wss://relay-snin.v2.site"]],
            kind=30001
        )
        result = asyncio.run(handle_balance_request(
            event, "wss://relay-snin.v2.site", key.public_key.hex()
        ))
        self.assertIsNotNone(result)
        self.assertEqual(result.get("kind"), 30002)
        print(f"✅ ТЕСТ 6: kind:30002 сформирован, структура валидна")

if __name__ == "__main__":
    print("=== NIP-XX: Solana Payments — 6 тестов ===\n")
    unittest.main(verbosity=0)
