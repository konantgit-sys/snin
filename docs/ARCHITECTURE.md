# SNIN Architecture — Layer Map

╔══════════════════════════════════════════════════════════╗
║              5. IoT / DEVICE LAYER                       ║
║  ESP32, Arduino, sensors, smart devices                 ║
║  Status: ❌ Not started                                  ║
╚══════════════════════════════════════════════════════════╝
                        ↕
╔══════════════════════════════════════════════════════════╗
║              4. RANKED CHANNEL LAYER                     ║
║  Priority channels (ranked):                             ║
║  Tier 1: direct (latency 1ms)                            ║
║  Tier 2: mesh (10ms)                                     ║
║  Tier 3: gossip (50ms)                                   ║
║  Tier 4: nostr broadcast (500ms+)                        ║
║  Status: ◐ Channel selection in SR exists,              ║
║    but no ranking and adaptive selection                 ║
╚══════════════════════════════════════════════════════════╝
                        ↕
╔══════════════════════════════════════════════════════════╗
║              3. NOSTR / FEDERATION LAYER                 ║
║  Nostr relays, federation, external subscribers         ║
║  External Gateway (nostr ↔ mesh bridge)                 ║
║  Status: ◐ Keys created, kind:0 published,              ║
║    External Gateway — legacy, not integrated            ║
╚══════════════════════════════════════════════════════════╝
                        ↕
╔══════════════════════════════════════════════════════════╗
║    2. AGENT / SELF-LEARNING LAYER                        ║
║  Routing matrix — each agent knows topology             ║
║  Status: ◐ Self-learning exists (SmartRouter stats),    ║
║    but no agent-to-agent matrix exchange                ║
╚══════════════════════════════════════════════════════════╝
                        ↕
╔══════════════════════════════════════════════════════════╗
║    1. P2P / MESH LAYER                                   ║
║  TCP pub/sub, Kademlia DHT, WAL buffer                  ║
║  Phase0 transport: handshake, identity, sig_gate        ║
║  Status: ✅ Working (3 agents, 17 nodes DHT, relay-mesh :9907)║
╚══════════════════════════════════════════════════════════╝
                        ↕
╔══════════════════════════════════════════════════════════╗
║    0. RELAY / SETTLEMENT LAYER                           ║
║  Nostr relay for settlement (Solana kind:30000)         ║
║  Consensus for DAO (kind:39000-39003)                   ║
║  Status: ✅ relay-snin :8198 live,                      ║
║    2175 events, 126 authors, DAO groups (572 events)    ║
╚══════════════════════════════════════════════════════════╝

---

## Development Directions

**1. Full Node.js/WebSockets support for public relay-mesh**
- Current: Python-only (Flask-Sock, websockets). Target: JS client + browser agents.

**2. Layered Self-Learning: agent → mesh → global**
- Each agent learns its piece of topology
- Spreads aggregated stats via gossip
- DHT aggregator for non-mesh agents

**3. IoT Discovery: mDNS + NIP-80**
- Auto device registration via kind:8010-8017
- ESP32 firmware bootstrap

**4. Circuit Breaker for each channel**
- Per-channel failure detection
- DHT aggregator fallback for non-mesh agents
