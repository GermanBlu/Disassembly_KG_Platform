# Read-only demo deployment

A self-contained, **read-only** instance to explore one pre-filled,
enriched product and chat with the GraphRAG assistant, without being able to
change anything. No CAD pipeline, no cloud database.

## Run it (one command)

On a Linux server with Docker + Compose:

```bash
export OPENAI_API_KEY=sk-...                 # required — powers the chat
export NEO4J_PASSWORD=choose-a-password      # optional (default: demo_change_me, used by all three containers)
docker compose -f docker-compose.demo.yml up --build -d
```

Then open `http://<server>:5050`. Three services come up in order:
1. **neo4j**: self-hosted graph DB (data persists in a Docker volume).
2. **seed**: one-shot: builds + enriches the demo product, then exits.
3. **app**: the Flask UI/API with `DEMO_MODE=1`.

> Access: the demo itself has no login; its safety guarantee is that it is
> read-only. If exposing beyond a trusted network, put an authenticating reverse
> proxy (or VPN) in front.

## What "read-only" means (enforced server-side)

Not just hidden in the UI: the server **rejects every write**:
- All mutating endpoints (`POST/PUT/PATCH/DELETE`) return **403**, except the
  GraphRAG chat.
- The chat engine runs `read_only`: it answers questions but refuses any
  enrichment/reassignment, so a tester cannot modify the graph through chat.
- The UI shows a read-only banner and hides the create/delete controls.

`GET /api/config` returns `{ "demo_mode": true }`; the frontend reads it.

## The example product

`seed_demo_product.py` builds the **hypothetical product** (8 parts, 2 M8 screw
joints) from `sample_data/hypothetical_product.json` and enriches each component
with **material, mass, recyclability and end-of-life route** (and product-level
totals), so the assistant can answer questions like *"what is the holder made
of?"*, *"how do I take the shaft out?"*, *"how much of this is recyclable?"*.

To change the showcased data, edit the `ENRICHMENT` / `PRODUCT_PROPS` tables in
`seed_demo_product.py` and re-run the `seed` service
(`docker compose -f docker-compose.demo.yml run --rm seed`).

## Notes

- The image (`Dockerfile.demo`) installs **no pythonocc-core**: the STEP/CAD
  pipeline is disabled in the demo, so the image is small and runs headless.
- The chat requires a valid `OPENAI_API_KEY`; everything else works without it.
- The model is set with `OPENAI_MODEL` (default `gpt-5.4-mini`).
- Server setup, access and updates: [`server-deployment.md`](server-deployment.md).
