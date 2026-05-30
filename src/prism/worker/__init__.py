"""PRISM background worker: scheduled feed ingestion and graph maintenance.

Runs as its own process/container (`prism-worker`), sharing the same SQLite /
LanceDB / vault as the bot and web app via the `prism.services` factory.
"""
