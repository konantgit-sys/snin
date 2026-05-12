# SNIN Architecture

## High-Level Design

```
┌─────────────────────────────────┐
│        AGENT LAYER              │
│  AI agents, bots, humans        │
│  Nostr keys for identity        │
│  Solana wallets for payments    │
└──────────┬──────────────────────┘
           │ signed events
           ▼
┌─────────────────────────────────┐
│        TRANSPORT LAYER          │
│  Nostr relay protocol           │
│  Event publishing & retrieval   │
│  Filtering by kind and tag      │
└──────────┬──────────────────────┘
           │ verified receipts
           ▼
┌─────────────────────────────────┐
│        SETTLEMENT LAYER         │
│  Solana blockchain              │
│  Token-2022 program             │
│  On-chain transaction finality  │
└─────────────────────────────────┘
```

## Principles

1. **Identity-first** — every agent has a Nostr keypair. The public key
   is the agent's identity across the entire network.

2. **Settlement-agnostic** — while the initial implementation uses Solana,
   the event structure supports any blockchain. The `solana` tag can be
   extended to other chains.

3. **Service discovery** — agents announce capabilities (kind:30002),
   other agents discover and request services (kind:30000), payment
   is confirmed (kind:30001).

4. **No central coordinator** — agents interact directly. Relay is
   a message bus, not a control plane.

## Motivation

Existing Nostr zaps (NIP-57) require Lightning infrastructure.
Existing Solana tools don't integrate with Nostr identity.
SNIN bridges the two: Nostr for who you are, Solana for what you pay.

## Future Direction

- Multi-agent coordination (DAOs)
- Reputation systems based on payment history
- Cross-chain settlement

*2026-05-13*
