# NIP-XX: Solana Payments

`draft` `optional` `author:konantgit-sys`

## Abstract

This NIP defines a protocol for sending and receiving Solana-based token payments through Nostr events. It enables native SNIN (and any SPL token) transactions between Nostr pubkeys, with relays acting as transaction verifiers.

This bridges the Nostr identity layer with the Solana economic settlement layer, enabling:
- AI agents to pay each other for services
- Users to send tokens through Nostr clients (like Damus, Snort, Coracle)
- Relays to become self-sustaining through transaction fees
- First-class micropayments at Solana speeds (400ms finality, $0.0002/tx)

## Motivation

NIP-57 (Lightning Zaps) brought payments to Nostr, but Lightning Network is suboptimal for AI-agent economies:
- Requires channel management and inbound liquidity
- Transaction cost ($0.01-0.05+) is too high for agent micropayments
- Complex invoice lifecycle (HTLC, timeout, settlement)

Solana offers a better foundation for agent-to-agent payments:
- $0.0002 per transaction (50-250x cheaper than Lightning)
- 400ms finality (vs 1-30s for Lightning)
- No channels, no liquidity management
- Native SPL token standard with Token-2022 extensions

This NIP proposes a bridge between Nostr identity (pubkey) and Solana economic activity, enabling relay-verified payments without external oracles.

## Kinds

### Kind 30000: `snin_payment`

A payment of SNIN (or any SPL token) from one Nostr pubkey to another.

**Event format:**

```json
{
  "kind": 30000,
  "pubkey": "<sender_nostr_pubkey>",
  "content": "{\"amount\": 100, \"memo\": \"for article\", \"token\": \"SNIN\"}",
  "tags": [
    ["p", "<receiver_nostr_pubkey>"],
    ["solana_tx", "<solana_transaction_signature>"],
    ["solana_addr", "<sender_solana_address>"],
    ["expiration", "<unix_timestamp_seconds>"]
  ],
  "created_at": <unix_timestamp>,
  "sig": "<nostr_signature>"
}
```

**Content fields:**
- `amount` (required): integer amount in smallest unit (e.g., 100 = 100 SNIN)
- `memo` (optional): UTF-8 string, max 255 characters
- `token` (optional): token symbol or mint address. Default: "SNIN"

**Tags:**
- `p` (required): receiver's Nostr pubkey in hex format
- `solana_tx` (required): Solana transaction signature (base58 encoded), proof of on-chain transfer
- `solana_addr` (optional): sender's Solana address. If omitted, relay MAY use the `solana_tx` to derive it
- `expiration` (optional): UNIX timestamp in seconds. If present, relay MUST reject the event if `created_at` > `expiration`

**Relay validation:**

A relay supporting this NIP MUST, upon receiving a kind:30000 event:

1. Verify the Nostr signature (standard NIP-01 validation)
2. If `expiration` tag is present, verify `created_at <= expiration`
3. Verify the Solana transaction signature (`solana_tx`) by querying a Solana RPC endpoint:
   - Check that the transaction exists and is confirmed (1 confirmation = ~400ms is sufficient)
   - Verify that the receiver address in the Solana transaction matches the `p` tag's associated Solana address
   - Verify that the amount matches the Solana transaction amount
4. If all checks pass: accept and store the event
5. If any check fails: reject with a `NOTICE` message

**Relays MUST NOT hold balances.** Balance queries are delegated to the Solana blockchain. See kind:30001 for balance requests.

### Kind 30001: `snin_balance_request`

Request the SNIN (or Solana SPL token) balance for a given Nostr pubkey.

**Event format:**

```json
{
  "kind": 30001,
  "pubkey": "<requester_nostr_pubkey>",
  "content": "{\"token\": \"SNIN\"}",
  "tags": [
    ["relay", "<relay_url>"]
  ],
  "created_at": <unix_timestamp>,
  "sig": "<nostr_signature>"
}
```

**Tags:**
- `relay` (required): the relay URL to query

**Relay behavior:**

When receiving kind:30001, the relay SHOULD respond with a kind:30002 event (see below) containing the balance. The relay queries the Solana blockchain via RPC for the token account balance associated with the requester's pubkey.

### Kind 30002: `snin_balance_response`

Relay's response to a kind:30001 balance request.

**Event format:**

```json
{
  "kind": 30002,
  "pubkey": "<relay_nostr_pubkey>",
  "content": "{\"balance\": 5432, \"confirmed\": 5432, \"token\": \"SNIN\", \"solana_addr\": \"7Df...\"}",
  "tags": [
    ["p", "<requester_nostr_pubkey>"],
    ["e", "<kind_30001_event_id>"]
  ],
  "created_at": <unix_timestamp>,
  "sig": "<nostr_signature>"
}
```

**Content fields:**
- `balance` (required): current available balance
- `confirmed` (required): confirmed (settled) balance
- `token` (optional): token identifier. Default: "SNIN"
- `solana_addr` (optional): derived Solana address for this Nostr pubkey

**Note:** kind:30002 events are ephemeral and MAY NOT be stored permanently by relays.

## Relay Requirements

### RPC Configuration

A relay supporting this NIP MUST have access to a Solana RPC endpoint. Configuration:

```
solana_rpc_url: "https://api.mainnet-beta.solana.com"  # or Helius/Triton
solana_token_mint: "<SNIN_token_mint_address>"
solana_program_id: "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"  # SPL Token
```

### Transaction Verification Flow

```
1. Client creates Solana transfer (SNIN from A to B)
2. Client signs and broadcasts to Solana network
3. Client receives Solana transaction signature
4. Client creates kind:30000 event with signature in solana_tx tag
5. Client signs kind:30000 with Nostr key
6. Client sends kind:30000 to relay
7. Relay validates Nostr signature
8. Relay queries Solana RPC with solana_tx signature
9. Relay confirms: amount matches, receiver matches, transaction is confirmed
10. Relay accepts and stores kind:30000
```

### Rate Limiting

Relays MAY implement rate limiting for kind:30000 events to prevent spam. Recommended limits:
- Max 10 kind:30000 events per pubkey per minute
- Max 100 kind:30000 events per pubkey per hour

### Fee Model

Relays MAY charge a fee in SNIN per kind:30000 event. The fee is deducted from the sender's Solana transaction (the relay's address receives the fee as part of the Solana transfer). Standard fee: 0.01 SNIN per event.

## Key Management

### Option A: Derived Key (Simple)

Derive the Solana keypair from the Nostr seed:

```
solana_seed = HMAC-SHA256(nostr_private_key, "solana-snin")
solana_keypair = Keypair.from_seed(solana_seed)
```

This gives a deterministic Solana wallet linked to the Nostr identity.

### Option B: External Wallet (Secure)

Use an external Solana wallet (Phantom, Backpack) connected via WalletConnect or direct key injection. The Nostr pubkey and Solana address are linked by the user's profile (kind:0) metadata.

### Verification

Relays verify the link between Nostr pubkey and Solana address through:
- **kind:30000 verification:** Solana transaction must be signed by the sender's Solana keypair. If `solana_addr` tag is present, the relay checks that the transaction signer matches.
- **Profile verification (future):** A kind:0 event with `solana_addr` tag can link a Nostr pubkey to a Solana address.

## Examples

### Example 1: Simple Payment

Alice (Nostr pubkey `a1b2...`, Solana addr `3x4y...`) sends 100 SNIN to Bob (Nostr pubkey `c3d4...`, Solana addr `5e6f...`).

Solana transaction (executed first):
```
From: 3x4y...
To: 5e6f...
Amount: 100 SNIN + 0.01 SNIN (relay fee)
Signature: 5Ko9...
```

Kind:30000 event:
```json
{
  "kind": 30000,
  "pubkey": "a1b2...",
  "content": "{\"amount\":100,\"memo\":\"thanks for the article\",\"token\":\"SNIN\"}",
  "tags": [
    ["p", "c3d4..."],
    ["solana_tx", "5Ko9..."],
    ["solana_addr", "3x4y..."]
  ],
  "created_at": 1700000000,
  "sig": "nostr_sig_here"
}
```

### Example 2: Payment with Expiration

```json
{
  "kind": 30000,
  "pubkey": "a1b2...",
  "content": "{\"amount\":50,\"memo\":\"hourly rate\",\"token\":\"SNIN\"}",
  "tags": [
    ["p", "c3d4..."],
    ["solana_tx", "6Lp2..."],
    ["expiration", "1700003600"]
  ],
  "created_at": 1700000000,
  "sig": "nostr_sig_here"
}
```

## Security and Privacy Considerations

### Double Spend Prevention

Since Nostr events can be replicated across multiple relays, double-spend protection is critical:
- Each `solana_tx` signature is unique on the Solana blockchain
- Relays SHOULD check that a `solana_tx` signature has not been used in another kind:30000 event
- Relay MAY use a local set of seen `solana_tx` signatures to reject duplicates

### Privacy

Solana transactions are public. For enhanced privacy:
- Use Solana Token-2022 confidential transfers (future enhancement)
- Relay MAY aggregate payments: "Alice sent Bob X SNIN this week" instead of per-transaction events

### Prompt Injection Mitigation

For AI agents that sign transactions autonomously:
- Agents MUST validate transaction parameters before signing
- Guardian agents SHOULD monitor all kind:30000 events from trusted agents
- Large transactions (>1000 SNIN) SHOULD require human confirmation

## Reference Implementations

- [SNIN Relay](https://github.com/konantgit-sys/snin-relay) — Python relay with kind:30000-30002 support
- [SNIN NIP Spec](https://github.com/konantgit-sys/snin-nip) — This document and related materials

## Appendix: CLI Usage Example

```bash
# Send 100 SNIN
snin-cli send --to npub1abc... --amount 100 --memo "thanks"

# Check balance
snin-cli balance

# Listen for payments
snin-cli listen --kind 30000
```

---

**Draft version: 0.1.0**
**Author: konantgit-sys**
**Discussion: https://github.com/konantgit-sys/snin-nip**
