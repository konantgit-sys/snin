# SNIN Mesh — Transport Architecture and Protocols

> Version: v2.0 | Date: 2026-05-16 | Status: ✅ Production

---

## 1. Architecture (7 layers)

```
┌──────────────────────────────────────────────────────────────────┐
│                      EXTERNAL WORLD                              │
│  Nostr (101 relays)     ESP32 / curl     SNIN agents            │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│  Layer 7: Smart Router   TCP :9932   (channel selection policy)  │
│  ┌────────┬────────┬──────────┬──────────┐                      │
│  │ direct │  mesh  │  gossip  │  nostr   │                      │
│  │  ~2ms  │ ~100ms │  ~50ms   │  ~1-5s   │                      │
│  └────┬───┴───┬────┴────┬─────┴────┬─────┘                      │
└───────┼───────┼─────────┼──────────┼────────────────────────────┘
        │       │         │          │
┌───────▼───────┴─────────┴──────────┴────────────────────────────┐
│  Layer 6: External Gateway   TCP :9931                          │
│  Nostr Protocol (WSS) + TCP raw → mesh format                   │
└─────────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│  Layer 5: Content Router + SQLite WAL    TCP :9920              │
│  Deduplication (5 sec window), Bloom filter, 5 parallel writers │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│  Layer 4: Route Engine + WS Data Channel    TCP :9910           │
│  Classification: kind:39000 bypass, batch → WS :9907            │
│  Flush rate: 59/sec (WS), batch size: 140-170                   │
└───────┬──────────────────────────────────────────────────────────┘
        │ WS :9907
┌───────▼──────────────────────────────────────────────────────────┐
│  Layer 3: Relay Mesh (Flask + HTTP Relay)    TCP :9907          │
│  NIP-42 AUTH, agent registration, device registry, SQLite       │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│  Layer 2: DHT Kademlia    UDP :9934                             │
│  K-buckets, XOR distance, Redis dual-write                      │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│  Layer 1: P2P Transport    TCP raw (Phase 0)                    │
│  WAL buffer, reconnect, relay mode, Ed25519 signatures          │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│  Layer 0: Physical Layer (TCP/IP, UDP)                          │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Component Details

### Layer 7: Smart Router (:9932)
- **Function:** Single entry point for all agents. Selects optimal delivery channel based on event kind and real-time latency measurements.
- **Channels:** direct (~2ms), mesh (~100ms, via Content Router), gossip (~50ms, 5 shards), nostr (~1-5s, external)
- **Self-learning:** Tracks latency per channel per agent. After 3 measurements (sliding window 60s), auto-switches if 20% faster channel available.
- **Circuit Breaker:** 3+ incidents >500ms within 60s → channel blocked for 30s.

### Layer 5: Content Router (:9920)
- **Function:** Deduplication layer. 7 parallel TCP writers to Route Engine.
- **Dedup:** In-memory FastDedup (O(1), TTL 5s, max 10k entries) + Bloom filter (1% FP, zero FN).
- **Redis hybrid:** Redis-backed dedup for cross-instance.

### Layer 4: Route Engine (:9910)
- **Function:** Classifies events by kind and routes accordingly.
- **Routing:** heartbeat → bypass to file, DHT → batch, DAO → immediate HTTP, mesh → batch via WS.
- **Batch window:** 100ms (10 flushes/sec).

### Layer 3: Relay Mesh (:9907)
- **Function:** HTTP API + WebSocket + NIP-42 AUTH.
- **Endpoints:** /health, /mesh/stats, /agents, /devices, /agents/register, /mesh/send.
- **Data:** SQLite (events, agents, devices), Redis (DHT, dedup).

### Layer 2: DHT Kademlia (:9934)
- **Function:** Distributed agent registry. Redis primary + Kademlia overlay.
- **K-buckets:** XOR distance, iterative lookup, store/find_value.
- **Refresh:** 3600s. Cleanup: 30s loop for dead agents (TTL 2h).

## 3. Traffic Classes

| Class | Priority | Target latency | Kind range | Default channel |
|-------|----------|---------------|------------|----------------|
| Heartbeat | 0 (highest) | <2ms | 39000 | gossip |
| DHT | 1 | <10ms | 39001 | gossip+direct |
| Content | 2 | <100ms | 39002 | mesh+nostr |
| DAO | 3 | <500ms | 39010-39025 | mesh |
| Payment | 4 | <1s | 30000 | chequebook |
| Nostr text | 5 (lowest) | >1s | 1, 7, 9734 | nostr |

## 4. Key Metrics

| Metric | Value |
|--------|-------|
| Max throughput (mesh) | ~100 msg/sec |
| Max throughput (gossip) | ~500 msg/sec |
| Dedup latency (in-memory) | ~0.5µs |
| Dedup latency (Redis) | ~150µs |
| Batch size (mesh) | 140-170 events |
| WS flush rate | 59/sec |
| Gossip fan-out | ×3 (random peers) |
| Anti-entropy interval | 60 seconds |
