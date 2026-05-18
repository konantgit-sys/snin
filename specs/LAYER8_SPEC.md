# SNIN Mesh — Layer 8 Specification v2.2 (final)

> Date: 2026-05-16 | Status: Approved

---

## Final Architecture (after all revisions)

```
AGENTS ──► Smart Router (:9932) ──► {mesh, gossip, nostr} ──► CR (:9920, Redis dedup) ──► RE (:9910) ──► Relay Mesh (:9907) ──► {SQLite, Redis}
                                              ↑
                                         Heartbeat — ONLY from Relay Mesh
```

## Removed 3 duplicates

| Before | After |
|--------|-------|
| Gossip → RE directly (bypass CR) | Gossip → CR (through dedup) |
| Heartbeat from 3 sources (Gossip, RE, Mesh) | Heartbeat from 1 source (Relay Mesh) |
| 2 agent entry points (SR + Gossip) | 1 entry — Smart Router |

## Added

- Redis dedup in CR (persistent dedup instead of in-memory)
- Circuit Breaker (>500ms → 30s ban)
- Consistent hashing for Gossip (1 pubkey → 1 shard)
- Backpressure (queue >100 → retry_after)
- SQLite WAL tuning + VACUUM
- ESP32 reconnection (exponential backoff)

## Agent Capabilities

| Channel | Target | Speed | Size | Duplicate |
|---------|--------|:----:|:----:|:--------:|
| direct | 1:1 | ~2ms | 64 KB | 1x |
| mesh | CR→RE | ~100ms | 500 B | 1-2x |
| gossip | all | ~50ms | 1 KB | ×15 |
| nostr | 21 relays | ~1-5s | 64 KB | 1x |

Per second: 100 msg (mesh) / 500 msg (gossip)
Priority: low=1 channel, normal=best, high=2 channels
Selection: self-learning + policy + congestion
