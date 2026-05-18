# SNIN Mesh — Morpho Analysis v2.2 (Final)

> This document describes the architectural evolution of SNIN Mesh.

---

## Architecture Improvements (Implemented)

### 1. Removed 3 Duplicates

| Before | After | Why |
|--------|-------|-----|
| Gossip → RE directly (bypass CR) | Gossip → CR (through dedup) | Gossip bypassed deduplication → duplicate events in relay |
| Heartbeat from 3 sources (Gossip, RE, Mesh) | Heartbeat from 1 source (Relay Mesh) | Inconsistent heartbeat TTL across sources → unreliable agent health |
| 2 agent entry points (SR + Gossip) | 1 entry — Smart Router | Dual entry points made it possible to bypass circuit breaker |

### 2. Added Features

| Feature | Description |
|---------|-------------|
| Redis dedup in CR | Persistent dedup instead of in-memory (cross-instance safety) |
| Circuit Breaker | >500ms latency → 30s channel block. Prevents cascading failures |
| Consistent hashing for Gossip | 1 pubkey → 1 shard. Reliable agent-to-shard mapping |
| Backpressure | Queue >100 → 503 Retry-After:5. Prevents OOM |
| SQLite WAL tuning + VACUUM | WAL checkpoint size, auto-vacuum. Prevents db bloat |
| ESP32 reconnection | Exponential backoff (1s → 30s max). Reliable IoT reconnect |

### 3. Traffic Classes

| Class | Priority | Target Latency | Kind Range | Default Channel | Notes |
|-------|----------|---------------|------------|----------------|-------|
| Heartbeat | 0 (highest) | <2ms | 39000 | gossip | Agent liveness, Hello messages |
| DHT | 1 | <10ms | 39001 | gossip+direct | Routing table updates |
| Content | 2 | <100ms | 39002 | mesh+nostr | Agent messages, payloads |
| DAO | 3 | <500ms | 39010-39025 | mesh | Group proposals, voting |
| Payment | 4 | <1s | 30000 | chequebook | Solana settlement |
| Nostr text | 5 (lowest) | >1s | 1, 7, 9734 | nostr | Public messages, reactions |

### 4. Self-Learning Mechanism

- Each SmartRouter tracks latency per channel per agent (sliding window, 3 measurements)
- 20% faster channel → automatic switch
- Circuit breaker trip → fallback to next tier
- Stats: `ZADD sr:channel_stats:{agent_id} {timestamp} {latency}` + `ZRANGE` for window

### 5. Final Architecture

```
AGENTS ──► Smart Router (:9932) ──► {mesh, gossip, nostr} ──► CR (:9920, Redis dedup) ──► RE (:9910) ──► Relay Mesh (:9907) ──► {SQLite, Redis}
                                              ↑
                                         Heartbeat — ONLY from Relay Mesh
```

---

## Benchmark Results (Latest)

| Test | Phase | Result |
|------|-------|--------|
| Latency (mesh) | Pre-optimization | ~150ms |
| Latency (mesh) | Post-optimization | ~100ms |
| Gossip fan-out | 5 shards × 3 peers | 15x delivery |
| Dedup accuracy | In-memory | 100% (no FPs) |
| Redis failover | CR auto-standalone | <50ms recovery |
