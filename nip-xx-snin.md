NIP-XX
======

Agent-to-Agent Payments on Solana

`draft` `optional`

## Abstract

This NIP defines events for direct payments between Nostr identities
settled on the Solana blockchain. It enables AI agents, automated
systems, and human users to transact value without intermediaries.

## Motivation

AI agents and automated systems need a native payment channel.
Existing zaps (NIP-57) settle on Lightning Network and require
a Lightning node. This NIP provides an alternative for agents
operating in the Solana ecosystem.

## Specification

### Events

Three event kinds are defined, all using parameterized replaceability:

#### Kind 30000: Agent Payment Request

A request from one agent to another for a payment.

- `content` must be a JSON object with:
  - `amount`: integer (in lamports, 1 SOL = 1_000_000_000 lamports)
  - `memo` (optional): string describing the purpose
- Tags:
  - `p`: pubkey of the recipient agent
  - `e` (optional): event the payment is for

Example:

```json
{
  "kind": 30000,
  "content": "{\"amount\": 100000000, \"memo\": \"compute: 1h inference\"}",
  "tags": [["p", "<recipient_pubkey>"]]
}
```

#### Kind 30001: Agent Payment Receipt

Confirmation that a payment was sent on-chain.

- `content` must be a JSON object with:
  - `tx_id`: Solana transaction signature (base58)
  - `amount`: integer (in lamports)
- Tags:
  - `p`: pubkey of the payer agent
  - `e`: event this receipt is in response to
  - `solana`: Solana transaction ID (indexed for relay search)

Example:

```json
{
  "kind": 30001,
  "content": "{\"tx_id\": \"5KtPn3...\", \"amount\": 100000000}",
  "tags": [
    ["p", "<payer_pubkey>"],
    ["e", "<kind_30000_event_id>"],
    ["solana", "5KtPn3..."]
  ]
}
```

#### Kind 30002: Agent Capability

An agent announces its capabilities and pricing.

- `content` must be a JSON object with:
  - `capabilities`: array of objects with:
    - `service`: string identifier
    - `price_per_unit`: integer (lamports)
    - `unit`: string (e.g., "call", "hour", "mb")
  - `solana_address`: the agent's Solana wallet (base58)
- Tags:
  - `d`: capability identifier (e.g., "snin-agent-capabilities")
  - `t`: service tags for discovery

Example:

```json
{
  "kind": 30002,
  "content": "{\"capabilities\": [{\"service\": \"text-inference\", \"price_per_unit\": 50000000, \"unit\": \"call\"}], \"solana_address\": \"Gx8...\"}",
  "tags": [["d", "snin-agent-capabilities"], ["t", "ai"], ["t", "inference"]]
}
```

### Relay Behavior

Relays SHOULD:

- Index kind:30000, 30001, 30002 events for search
- Allow filtering by `solana` tag
- Allow filtering by `t` tag
- Apply NIP-70 (protected events) to prevent unauthorized modification

### Client Behavior

Clients SHOULD:

- Display payment requests with on-chain verification status
- Show agent capabilities for service discovery
- Verify kind:30001 receipts against Solana RPC

## Security Considerations

- Agents MUST verify kind:30001 receipts by checking the Solana
  transaction on-chain before providing services
- Kind:30000 is a request, not a commitment — agents should not
  act before receiving a verified receipt
- Capabilities (kind:30002) should be treated as announcements,
  not guarantees

## References

- NIP-01: Basic protocol flow
- NIP-57: Lightning Zaps
- Solana: https://solana.com/docs
