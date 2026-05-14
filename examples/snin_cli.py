#!/usr/bin/env python3
"""
snin-cli — SNIN Payment CLI
Отправка SNIN через Nostr (kind:30000)
Использование:
  python3 snin_cli.py send --to <npub|pubkey_hex> --amount 100 --memo "test"
  python3 snin_cli.py balance --pubkey <pubkey_hex>
  python3 snin_cli.py listen
"""
import asyncio, json, time, hashlib, sys, os, argparse, logging
sys.path.insert(0, '/home/agent/data/sites/relay')

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger('snin')

from nostr.key import PrivateKey
from nostr.event import Event as NostrEvent

RELAY_WS = "ws://localhost:8198"
RELAY_API = "http://localhost:8198"

# ── Keys ──
AGENT_KEYS = {
    "cryter": os.getenv("CRYTER_NSEC", "nsec1...УСТАНОВИТЕ CRYTER_NSEC..."),
}

async def cmd_send(args):
    """Отправить SNIN через kind:30000"""
    # Ключ
    if args.from_key:
        key = PrivateKey.from_nsec(args.from_key)
    elif args.from_name and args.from_name in AGENT_KEYS:
        key = PrivateKey.from_nsec(AGENT_KEYS[args.from_name])
    else:
        print("❌ Укажи --from_key или --from_name (cryter)")
        sys.exit(1)
    
    pubkey_hex = key.public_key.hex()
    
    # Адрес получателя
    to_pubkey = args.to
    to_solana = args.to_solana or "DbjSinRTBwxmh6qN4YpBCdDFv5zpFhshmPUofe8hj1zS"
    
    # Solana tx signature (имитация — реальная будет после токена)
    solana_tx = args.tx or f"demo_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:40]}"
    
    # Создаём kind:30000
    content = json.dumps({
        "amount": args.amount,
        "memo": args.memo or f"SNIN payment from {args.from_name or 'agent'}",
        "token": args.token or "SNIN"
    })
    tags = [
        ["p", to_pubkey],
        ["solana_tx", solana_tx],
        ["solana_addr", args.from_solana or "HyEAp2L4LweWnAJE13u3BxsqD2fagiqJUysgjsNdSjeA"]
    ]
    
    event = NostrEvent(
        public_key=pubkey_hex,
        content=content,
        kind=30000,
        tags=tags,
        created_at=int(time.time())
    )
    key.sign_event(event)
    
    event_dict = {
        "id": event.id, "pubkey": event.public_key,
        "created_at": event.created_at, "kind": event.kind,
        "tags": event.tags, "content": event.content, "sig": event.signature
    }
    
    print(f"📤 Отправка {args.amount} {args.token or 'SNIN'}")
    print(f"   От:     {args.from_name or pubkey_hex[:16]}...")
    print(f"   Кому:   {to_pubkey[:16]}...")
    print(f"   Tx:     {solana_tx[:24]}...")
    print(f"   Memo:   {args.memo or '-'}")
    
    # Отправка на relay
    try:
        import websockets
        async with websockets.connect(RELAY_WS) as ws:
            await ws.send(json.dumps(["EVENT", event_dict]))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            
            if len(resp) > 2 and resp[2]:
                print(f"✅ Платёж ПРИНЯТ! ID: {resp[1][:16]}...")
                if resp[0] == "OK":
                    return True
            else:
                reason = resp[3] if len(resp) > 3 else "unknown"
                print(f"❌ Отклонён: {reason}")
                return False
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")
        return False

async def cmd_balance(args):
    """Запросить баланс через kind:30001"""
    key = PrivateKey.from_nsec(args.from_key or AGENT_KEYS["cryter"])
    pubkey_hex = key.public_key.hex()
    
    event = NostrEvent(
        public_key=pubkey_hex,
        content=json.dumps({"token": args.token or "SNIN"}),
        kind=30001,
        tags=[["relay", "wss://relay-snin.v2.site"]],
        created_at=int(time.time())
    )
    key.sign_event(event)
    
    event_dict = {
        "id": event.id, "pubkey": event.public_key,
        "created_at": event.created_at, "kind": event.kind,
        "tags": event.tags, "content": event.content, "sig": event.signature
    }
    
    try:
        import websockets
        async with websockets.connect(RELAY_WS) as ws:
            await ws.send(json.dumps(["EVENT", event_dict]))
            print("📊 Запрос баланса отправлен, ответ relay:")
            resp = await asyncio.wait_for(ws.recv(), timeout=10.0)
            print(f"   {resp[:200]}")
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")

async def cmd_listen(args):
    """Слушать входящие kind:30000"""
    print("👂 Слушаю kind:30000...")
    print("   (нажми Ctrl+C для выхода)\n")
    
    try:
        import websockets
        async with websockets.connect(RELAY_WS) as ws:
            # Подписываемся на kind:30000
            sub = json.dumps(["REQ", "snin-pay", {"kinds": [30000]}])
            await ws.send(sub)
            print("   Подписка на kind:30000 отправлена\n")
            
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60.0))
                if msg[0] == "EVENT" and msg[1].get("kind") == 30000:
                    ev = msg[1]
                    content = json.loads(ev.get("content", "{}"))
                    print(f"💸 ПЛАТЁЖ {content.get('amount','?')} SNIN")
                    print(f"   От:  {ev['pubkey'][:16]}...")
                    print(f"   Tx:  {dict(ev.get('tags',[])).get('solana_tx','?')[:16]}...")
                    print(f"   Memo: {content.get('memo','-')}\n")
                elif msg[0] == "EOSE":
                    print("   EOSE получен, слушаю в реальном времени...\n")
    except KeyboardInterrupt:
        print("\n   Остановлено")
    except Exception as e:
        print(f"⚠️ {e}")

def main():
    parser = argparse.ArgumentParser(description="snin-cli — SNIN Payment Tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    # send
    p_send = sub.add_parser("send", help="Отправить SNIN")
    p_send.add_argument("--to", required=True, help="Nostr pubkey получателя (hex)")
    p_send.add_argument("--amount", type=int, required=True, help="Количество SNIN")
    p_send.add_argument("--memo", default="", help="Комментарий")
    p_send.add_argument("--token", default="SNIN", help="Токен (по умолч. SNIN)")
    p_send.add_argument("--from-name", default="cryter", help="Имя отправителя")
    p_send.add_argument("--from-key", help="Ключ отправителя (nsec)")
    p_send.add_argument("--from-solana", help="Solana адрес отправителя")
    p_send.add_argument("--to-solana", help="Solana адрес получателя")
    p_send.add_argument("--tx", help="Solana transaction signature")
    
    # balance
    p_bal = sub.add_parser("balance", help="Проверить баланс")
    p_bal.add_argument("--from-key", default=AGENT_KEYS["cryter"], help="Ключ (nsec)")
    p_bal.add_argument("--token", default="SNIN", help="Токен")
    
    # listen
    sub.add_parser("listen", help="Слушать платежи kind:30000")
    
    args = parser.parse_args()
    
    if args.cmd == "send":
        asyncio.run(cmd_send(args))
    elif args.cmd == "balance":
        asyncio.run(cmd_balance(args))
    elif args.cmd == "listen":
        asyncio.run(cmd_listen(args))

if __name__ == "__main__":
    main()
