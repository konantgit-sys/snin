"""
Настройка профилей агентов (kind:0) с Solana адресами
Маппинг Nostr pubkey → Solana wallet для relay
"""
import asyncio, json, time, logging, sys, os
sys.path.insert(0, '/home/agent/data/sites/relay')

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('setup')

from nostr.key import PrivateKey
from nostr.event import Event as NostrEvent

RELAY_WS = "ws://localhost:8198"

# ── Агенты и их Solana адреса (devnet) ──
AGENTS = {
    "cryter": {
        "nsec": os.getenv("CRYTER_NSEC", "nsec1...ВАШ_NSEC..."),
        "name": "Cryter",
        "solana_addr": "HyEAp2L4LweWnAJE13u3BxsqD2fagiqJUysgjsNdSjeA",
        "about": "Gatekeeper — SNIN relay operator, 101 relays, NIP-XX Solana Payments"
    },
    "anton": {
        # ⚠️ Замени nsec_hex на свой приватный ключ перед запуском
        "nsec_hex": os.getenv("ANTON_NSEC_HEX", "ВАШ_NSEC_HEX_ЗДЕСЬ"),
        "name": "Anton",
        "solana_addr": os.getenv("ANTON_SOLANA_ADDR", "ВАШ_SOLANA_АДРЕС_ЗДЕСЬ"),
        "about": "Test agent — first SNIN payment recipient"
    }
}

async def main():
    log.info("=== НАСТРОЙКА ПРОФИЛЕЙ АГЕНТОВ (kind:0) ===\n")
    
    for name, cfg in AGENTS.items():
        if "nsec" in cfg:
            key = PrivateKey.from_nsec(cfg["nsec"])
        else:
            key = PrivateKey(bytes.fromhex(cfg["nsec_hex"]))
        pubkey_hex = key.public_key.hex()
        
        # Создаём профиль kind:0 с Solana адресом
        profile = {
            "name": cfg["name"],
            "about": cfg["about"],
            "display_name": cfg["name"],
            "website": "https://relay-snin.v2.site",
            "solana_addr": cfg["solana_addr"],  # ключевое поле для relay
            "nip05": f"{name.lower()}@nostr.v2app.ru"
        }
        
        event = NostrEvent(
            public_key=pubkey_hex,
            content=json.dumps(profile),
            kind=0,
            tags=[],
            created_at=int(time.time())
        )
        key.sign_event(event)
        
        log.info(f"✅ {cfg['name']}:")
        log.info(f"   Nostr pubkey: {pubkey_hex[:16]}...")
        log.info(f"   Solana addr:  {cfg['solana_addr']}")
        log.info(f"   kind:0 создан, content: {len(json.dumps(profile))} байт")
        
        # Отправляем на relay
        try:
            import websockets
            async with websockets.connect(RELAY_WS) as ws:
                event_dict = {
                    "id": event.id, "pubkey": event.public_key,
                    "created_at": event.created_at, "kind": event.kind,
                    "tags": event.tags, "content": event.content, "sig": event.signature
                }
                await ws.send(json.dumps(["EVENT", event_dict]))
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                log.info(f"   Relay: {resp}")
        except Exception as e:
            log.warning(f"   ⚠️ WS: {e}")
        
        log.info("")
    
    log.info("=== ГОТОВО ===")
    log.info("2 профиля с solana_addr сохранены в relay")
    log.info("Relay теперь может сопоставить Nostr pubkey → Solana wallet")

if __name__ == "__main__":
    asyncio.run(main())
