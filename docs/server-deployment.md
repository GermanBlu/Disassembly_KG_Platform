# Read-only demo on a server (Docker)

A self-contained, **read-only** instance of the KG-Platform: the Flask web UI, a
self-hosted Neo4j graph database (pre-seeded with one enriched demo product) and
the GraphRAG chat assistant. One command, one URL, no cloud database.

Everything is read-only (`DEMO_MODE=1`): every write endpoint returns 403 and the
chat cannot modify the graph: the only external call is the OpenAI API for the chat.

---

## Requirements

- A Linux host with **Docker Engine + the Docker Compose plugin**
  (`docker --version && docker compose version`).
- **Outbound internet** from the host: Docker Hub + PyPI (during the build) and
  `api.openai.com` (for the chat, at runtime).
- ~**4 GB RAM**, ~**40 GB disk**, one free TCP port (default **5050**).
- An **OpenAI API key** (only the chat needs it; everything else works without).

## Deploy (one command)

1. Clone the repository on the host and `cd` into it:
   ```bash
   git clone https://github.com/GermanBlu/Disassembly_KG_Platform.git KG_Platform
   cd KG_Platform
   ```
2. Create a `.env` file next to `docker-compose.demo.yml`:
   ```
   OPENAI_API_KEY=sk-...
   NEO4J_PASSWORD=choose-a-strong-password
   DEMO_PORT=5050
   ```
3. Build and start:
   ```bash
   docker compose -f docker-compose.demo.yml up --build -d
   ```
   Three services come up in order: **neo4j** → **seed** (loads + enriches the demo
   product, then exits) → **app** (the read-only web UI/API). The first build takes
   a few minutes (Python dependencies).

## Access

- On the host: `http://localhost:5050` (or whatever `DEMO_PORT` you set).
- From another machine, either open the port in the firewall/security group, or
  (recommended, no port needed) use an SSH tunnel:
  ```bash
  ssh -L 5050:localhost:5050 <user>@<server>      # then open http://localhost:5050
  ```
- The app has **no login**; its safety guarantee is that it is fully read-only.
  If exposing beyond a trusted network, put a VPN or an authenticating reverse
  proxy in front.

## Verify it is up

```bash
docker compose -f docker-compose.demo.yml ps
curl -s http://localhost:5050/api/config          # -> {"demo_mode": true}
```

## What the demo shows

One enriched product: the **Hypothetical Product** (8 parts, 2 M8 screw joints):

- **Per component**: material, mass, recyclability and end-of-life route.
- **Per disassembly task**: the required skill, the assigned **tool** (5 mm Allen
  key for the screws, pull-off tool for the press-fits, by hand for the loose fit),
  the **time**, difficulty, and the **cost broken into labor + tool usage**.
- **Product totals**: full-teardown time and cost (placeholder values), and the number
  of complete disassembly sequences (284; they can be executed in 360 orders).
- Interactive graph views, plus a **GraphRAG chat** that answers questions about
  all of the above (e.g. *"which tool removes the screws and what does the full
  teardown cost?"*).

## Update to a newer version

Run `git pull`, then re-run the same command. Docker rebuilds and restarts:

```bash
docker compose -f docker-compose.demo.yml up --build -d
```

## Housekeeping

- Data persists in a Docker volume (`neo4j_data`).
- Full reset (wipe the database and re-seed on next start):
  ```bash
  docker compose -f docker-compose.demo.yml down -v
  ```
- Logs: `docker compose -f docker-compose.demo.yml logs -f app`
