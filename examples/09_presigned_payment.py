"""
Pre-signed kind:30000 — готов к отправке, когда появится токен.
Использование:
  python3 presigned_payment.py
  → выведет событие. Реальную solana_tx подставить в --tx
"""
import asyncio, json, time, sys, argparse
sys.path.insert(0, '/home/agent/data/sites/relay')

from nostr.key import PrivateKey
from nostr.event import Event as NostrEvent

# ⚠️ Установи CRYTER_NSEC, ANTON_PUBKEY, ANTON_SOLANA в окружении
CRYTER_NSEC = os.getenv("CRYTER_NSEC", "nsec1...ВАШ_NSEC...")
ANTON_PUBKEY = os.getenv("ANTON_PUBKEY", "c2cc7057d9185e2d87aa27c74e881e812ea92e53aff5fe5a265872eda2484ff4")
ANTON_SOLANA = os.getenv("ANTON_SOLANA", "DbjSinRTBwxmh6qN4YpBCdDFv5zpFhshmPUofe8hj1zS")
CRYTER_SOLANA = "HyEAp2L4LweWnAJE13u3BxsqD2fagiqJUysgjsNdSjeA"

def build_event(amount=100, token="SNIN", memo="", solana_tx="REPLACE_ME", 
                to_pubkey=ANTON_PUBKEY, to_solana=ANTON_SOLANA):
    key = PrivateKey.from_nsec(CRYTER_NSEC)
    content = json.dumps({"amount": amount, "memo": memo, "token": token})
    tags = [
        ["p", to_pubkey],
        ["solana_tx", solana_tx],
        ["solana_addr", CRYTER_SOLANA]
    ]
    event = NostrEvent(
        public_key=key.public_key.hex(),
        content=content, kind=30000, tags=tags,
        created_at=int(time.time())
    )
    key.sign_event(event)
    return {
        "id": event.id, "pubkey": event.public_key,
        "created_at": event.created_at, "kind": event.kind,
        "tags": event.tags, "content": event.content, "sig": event.signature
    }

async def send_to_relay(event_dict):
    import websockets
    RELAY_WS = "ws://localhost:8198"
    async with websockets.connect(RELAY_WS) as ws:
        await ws.send(json.dumps(["EVENT", event_dict]))
        resp = await asyncio.wait_for(ws.recv(), timeout=10.0)
        return json.loads(resp)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--amount", type=int, default=100)
    parser.add_argument("--memo", default="first SNIN payment Cryter → Anton")
    parser.add_argument("--tx", default="REPLACE_WITH_REAL_SOLANA_TX")
    parser.add_argument("--send", action="store_true", help="отправить на relay")
    args = parser.parse_args()
    
    event = build_event(amount=args.amount, memo=args.memo, solana_tx=args.tx)
    
    print(f"📦 PRE-SIGNED kind:30000")
    print(f"   ID:      {event['id'][:20]}...")
    print(f"   От:      {event['pubkey'][:16]}... (Cryter)")
    print(f"   Кому:    {ANTON_PUBKEY[:16]}... (Anton)")
    print(f"   Сумма:   {args.amount} SNIN")
    print(f"   Tx:      {args.tx[:24]}..." if len(args.tx) > 24 else f"   Tx:      {args.tx}")
    print(f"   Solana:  {CRYTER_SOLANA} → {ANTON_SOLANA}")
    print(f"   Memo:    {args.memo}")
    print(f"\n   JSON готов к отправке ({len(json.dumps(event))} байт)")
    
    if args.send:
        print(f"\n→ Отправляю на relay...")
        resp = asyncio.run(send_to_relay(event))
        print(f"   Ответ: {resp}")
    
    # Сохраняем JSON для быстрой отправки
    with open("/tmp/last_payment_event.json", "w") as f:
        json.dump(event, f, indent=2)
    print(f"\n✅ Сохранён в /tmp/last_payment_event.json")
    print(f"   Отправить: curl -X POST http://localhost:8191/api/v1/send -d @/tmp/last_payment_event.json")
