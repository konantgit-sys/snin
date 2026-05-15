#!/usr/bin/env python3
"""SNIN ESP32 — Transport Abstraction Layer

Позволяет AgentMesh работать поверх любого транспорта: TCP, IPFS, HTTP, ESP-NOW.

Фаза 0.5 Roadmap: вынести Transport из phase0/transport.py в абстрактный класс.

Usage:
    from esp32.sdk.transport import Transport, TCPTransport, ESPNOWTransport

    mesh = AgentMesh("agent_x", ["ping"], transport=ESPNOWTransport(config))
    await mesh.start()
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import time
from typing import Callable

logger = logging.getLogger("snin.transport")


# ─── Message envelope ───────────────────────────────────────────
class TransportMessage:
    """Универсальный конверт для любого транспорта.
    Сериализуется в JSON, влазит в ESP-NOW (250B с запасом).
    """
    def __init__(
        self,
        topic: str,
        payload: dict,
        sender: str,
        signature: str = "",
        pubkey: str = "",
        seq: int = 0,
        ttl: int = 3,
    ):
        self.topic = topic
        self.payload = payload
        self.sender = sender
        self.signature = signature
        self.pubkey = pubkey
        self.seq = seq
        self.ts = time.time()
        self.ttl = ttl

    def encode(self) -> bytes:
        return json.dumps({
            "t": self.topic,
            "p": self.payload,
            "s": self.sender,
            "sig": self.signature,
            "pk": self.pubkey,
            "seq": self.seq,
            "ts": self.ts,
            "ttl": self.ttl,
        }).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "TransportMessage":
        obj = json.loads(data.decode("utf-8"))
        return cls(
            topic=obj["t"],
            payload=obj["p"],
            sender=obj["s"],
            signature=obj.get("sig", ""),
            pubkey=obj.get("pk", ""),
            seq=obj.get("seq", 0),
            ttl=obj.get("ttl", 3),
        )

    def __repr__(self) -> str:
        return f"<TM {self.topic} from={self.sender[:16]} seq={self.seq}>"


# ─── Abstract Transport ─────────────────────────────────────────
class Transport(abc.ABC):
    """Агностик-транспорт. Один интерфейс для TCP/IPFS/HTTP/ESP-NOW."""

    @abc.abstractmethod
    async def publish(self, topic: str, message: TransportMessage) -> bool:
        """Опубликовать сообщение в топик."""
        ...

    @abc.abstractmethod
    async def subscribe(self, topic: str, callback: Callable) -> None:
        """Подписаться на топик. callback(msg: TransportMessage)."""
        ...

    @abc.abstractmethod
    async def peers(self) -> list[dict]:
        """Список пиров: [{id, addr, rtt_ms, transport_type}]."""
        ...

    @abc.abstractmethod
    async def start(self) -> None:
        """Запустить транспорт."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """Остановить транспорт."""
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Имя транспорта (tcp, ipfs, http, espnow)."""
        ...


# ─── Built-in: TCP Transport ────────────────────────────────────
class TCPTransport(Transport):
    """Прямое TCP-соединение между агентами. Zero зависимостей."""

    def __init__(self, host: str = "0.0.0.0", port: int = 0, peers: list[str] | None = None):
        self._host = host
        self._port = port
        self._peers_cfg = peers or []
        self._server: asyncio.Server | None = None
        self._subscriptions: dict[str, list[Callable]] = {}
        self._connections: dict[str, asyncio.StreamWriter] = {}

    @property
    def name(self) -> str:
        return "tcp"

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )
        port = self._server.sockets[0].getsockname()[1]
        logger.info(f"TCP transport started on port {port}")

        # Подключиться к пирам
        for peer in self._peers_cfg:
            host, port = peer.split(":")
            try:
                reader, writer = await asyncio.open_connection(host, int(port))
                self._connections[peer] = writer
                asyncio.create_task(self._read_peer(reader, peer))
                logger.info(f"Connected to peer {peer}")
            except Exception as e:
                logger.warning(f"Cannot connect to {peer}: {e}")

    async def stop(self) -> None:
        for writer in self._connections.values():
            writer.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def publish(self, topic: str, message: TransportMessage) -> bool:
        data = message.encode()
        for peer, writer in list(self._connections.items()):
            try:
                writer.write(len(data).to_bytes(4, "big"))
                writer.write(data)
                await writer.drain()
            except Exception as e:
                logger.warning(f"Write to {peer} failed: {e}")
                del self._connections[peer]
        return True

    async def subscribe(self, topic: str, callback: Callable) -> None:
        self._subscriptions.setdefault(topic, []).append(callback)

    async def peers(self) -> list[dict]:
        return [
            {"id": addr, "addr": addr, "rtt_ms": 0, "transport_type": "tcp"}
            for addr in self._connections
        ]

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info(f"New TCP connection from {addr}")
        self._connections[str(addr)] = writer
        try:
            while True:
                size_bytes = await reader.readexactly(4)
                size = int.from_bytes(size_bytes, "big")
                data = await reader.readexactly(size)
                msg = TransportMessage.decode(data)
                for callback in self._subscriptions.get(msg.topic, []):
                    asyncio.create_task(callback(msg))
        except asyncio.IncompleteReadError:
            pass
        finally:
            self._connections.pop(str(addr), None)
            writer.close()

    async def _read_peer(self, reader: asyncio.StreamReader, peer_id: str):
        try:
            while True:
                size_bytes = await reader.readexactly(4)
                size = int.from_bytes(size_bytes, "big")
                data = await reader.readexactly(size)
                msg = TransportMessage.decode(data)
                for callback in self._subscriptions.get(msg.topic, []):
                    asyncio.create_task(callback(msg))
        except asyncio.IncompleteReadError:
            logger.info(f"Peer {peer_id} disconnected")
            self._connections.pop(peer_id, None)


# ─── Built-in: HTTP Transport (через публичный relay) ──────────
class HTTPTransport(Transport):
    """HTTP-транспорт через mesh-relay.v2.site.
    Для bridge-нод, которые не могут держать TCP.
    """

    def __init__(self, relay_url: str = "https://mesh-relay.v2.site"):
        self._relay_url = relay_url.rstrip("/")
        self._callbacks: dict[str, list[Callable]] = {}
        self._running = False
        self._agent_id = ""

    @property
    def name(self) -> str:
        return "http"

    async def start(self) -> None:
        self._running = True
        logger.info(f"HTTP transport starting via {self._relay_url}")

    async def stop(self) -> None:
        self._running = False

    async def publish(self, topic: str, message: TransportMessage) -> bool:
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._relay_url}/api/send",
                    json={
                        "topic": topic,
                        "payload": message.payload,
                        "sender": message.sender,
                        "signature": message.signature,
                        "pubkey": message.pubkey,
                    },
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning(f"HTTP publish failed: {e}")
            return False

    async def subscribe(self, topic: str, callback: Callable) -> None:
        self._callbacks.setdefault(topic, []).append(callback)

    async def peers(self) -> list[dict]:
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._relay_url}/api/stats",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
                    return data.get("peers", [])
        except:
            return []


# ─── Factory ────────────────────────────────────────────────────
def create_transport(
    transport_type: str = "tcp",
    host: str = "0.0.0.0",
    port: int = 0,
    peers: list[str] | None = None,
    relay_url: str = "https://mesh-relay.v2.site",
) -> Transport:
    """Фабрика транспортов. transport_type: tcp | http | ipfs | espnow."""
    if transport_type == "tcp":
        return TCPTransport(host=host, port=port, peers=peers)
    elif transport_type == "http":
        return HTTPTransport(relay_url=relay_url)
    elif transport_type == "ipfs":
        from phase0.transport import IPFSTransport  # оригинал из p2p-agent-mesh
        return IPFSTransport()
    elif transport_type == "espnow":
        # ESP-NOW transport — будет загружен при наличии MicroPython
        raise NotImplementedError("ESPNOWTransport requires MicroPython or bridge")
    else:
        raise ValueError(f"Unknown transport: {transport_type}")
