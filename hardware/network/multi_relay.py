#!/usr/bin/env python3
"""
Phase E — Multi-Relay Daemon
Публикует NIP-80 события на 3 relay: локальный + 2 публичных.
Проверяет health, пишет статус для dashboard.
"""

import sys, os, json, time, asyncio, aiohttp, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hardware.crypto.nostr_signer import NostrSigner

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('multirelay')

RELAYS = [
    "ws://localhost:8198",
    "wss://nos.lol",
    "wss://relay.damus.io",
]

STATUS_FILE = "/home/agent/data/sites/cryter-dash/static/relay_status.json"
TEST_INTERVAL = 300  # 5 минут
PUBLISH_INTERVAL = 600  # 10 минут


class RelayHealth:
    def __init__(self, url: str):
        self.url = url
        self.name = url.replace("ws://", "").replace("wss://", "")
        self.online = False
        self.latency_ms = 0
        self.last_ok = 0
        self.last_error = 0
        self.error_msg = ""
        self.events_accepted = 0
        self.events_rejected = 0

    @property
    def status(self) -> str:
        if not self.online: return "offline"
        if time.time() - self.last_ok > 600: return "stale"
        return "online"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "online": self.online,
            "last_ok_ago": int(time.time() - self.last_ok) if self.last_ok else None,
            "last_error_ago": int(time.time() - self.last_error) if self.last_error else None,
            "error": self.error_msg,
            "accepted": self.events_accepted,
            "rejected": self.events_rejected,
            "updated": datetime.utcnow().isoformat(),
        }


class MultiRelayDaemon:
    def __init__(self):
        self.signer = NostrSigner()
        self.relays = [RelayHealth(u) for u in RELAYS]
        self.session: aiohttp.ClientSession | None = None
        self.publish_seq = 0

    async def connect(self, rh: RelayHealth) -> aiohttp.ClientWebSocketResponse | None:
        try:
            t0 = time.time()
            ws = await self.session.ws_connect(rh.url, timeout=5)
            rh.latency_ms = int((time.time() - t0) * 1000)
            rh.online = True
            rh.error_msg = ""
            return ws
        except Exception as e:
            rh.online = False
            rh.error_msg = str(e)[:80]
            return None

    async def publish_event(self, ws, rh: RelayHealth, event: dict) -> bool:
        try:
            await ws.send_json(["EVENT", event])
            msg = await ws.receive(timeout=10)
            data = msg.json() if hasattr(msg, 'json') else json.loads(msg.data)
            ok = isinstance(data, list) and len(data) >= 3 and data[2] is True
            if ok:
                rh.last_ok = time.time()
                rh.events_accepted += 1
            else:
                rh.last_error = time.time()
                rh.events_rejected += 1
                rh.error_msg = str(data[3])[:60] if len(data) > 3 else str(data)[:60]
            return ok
        except Exception as e:
            rh.last_error = time.time()
            rh.online = False
            rh.error_msg = str(e)[:80]
            return False

    async def health_check(self, rh: RelayHealth):
        """Проверка relay: подписка + получение EOSE."""
        ws = await self.connect(rh)
        if not ws:
            return
        try:
            t0 = time.time()
            await ws.send_json(["REQ", f"h_{rh.name[:8]}", {"kinds": [8010], "limit": 1}])
            msg = await ws.receive(timeout=5)
            rh.online = True
            rh.latency_ms = int((time.time() - t0) * 1000)
            rh.last_ok = time.time()
            await ws.close()
        except Exception as e:
            rh.online = False
            rh.error_msg = str(e)[:80]

    async def publish_cycle(self):
        """Публикует событие на все relay."""
        self.publish_seq += 1
        seq = self.publish_seq
        device_id = f"multirelay_{seq}"
        event = self.signer.create_kind_8010(device_id, 
                                               round(20 + seq % 15, 1),
                                               round(50 + seq % 30, 1),
                                               85 + seq % 15,
                                               seq)

        for rh in self.relays:
            ws = await self.connect(rh)
            if not ws:
                continue
            ok = await self.publish_event(ws, rh, event)
            log.info(f"  {'✅' if ok else '❌'} {rh.name:20s}  kind:8010 [{device_id}]")
            try:
                await ws.close()
            except:
                pass

    async def save_status(self):
        """Пишет статус relay в JSON для dashboard."""
        data = {
            "timestamp": datetime.utcnow().isoformat(),
            "pubkey": self.signer.pubkey[:16],
            "relays": [rh.to_dict() for rh in self.relays],
            "summary": {
                "total": len(self.relays),
                "online": sum(1 for r in self.relays if r.online),
                "accepted": sum(r.events_accepted for r in self.relays),
            }
        }
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        log.info(f"  📊 Status saved ({data['summary']['online']}/{data['summary']['total']} online)")

    async def run(self):
        log.info("═" * 60)
        log.info(" MULTI-RELAY DAEMON — Phase E")
        log.info(f" Relays: {len(self.relays)}")
        log.info(f" Interval: {PUBLISH_INTERVAL}s publish, {TEST_INTERVAL}s health")
        log.info(f" Status: {STATUS_FILE}")
        log.info("═" * 60)

        async with aiohttp.ClientSession() as session:
            self.session = session
            last_health = 0
            last_publish = 0

            while True:
                now = time.time()

                # Health check every TEST_INTERVAL
                if now - last_health >= TEST_INTERVAL:
                    log.info("\n[HEALTH CHECK]")
                    for rh in self.relays:
                        await self.health_check(rh)
                        log.info(f"  {'🟢' if rh.online else '🔴'} {rh.name:20s}  {rh.latency_ms}ms")
                    last_health = now
                    await self.save_status()

                # Publish every PUBLISH_INTERVAL
                if now - last_publish >= PUBLISH_INTERVAL:
                    log.info("\n[PUBLISH CYCLE]")
                    await self.publish_cycle()
                    last_publish = now
                    await self.save_status()

                await asyncio.sleep(30)  # tick every 30s


if __name__ == "__main__":
    daemon = MultiRelayDaemon()
    asyncio.run(daemon.run())
