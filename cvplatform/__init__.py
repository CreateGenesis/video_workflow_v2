"""V3 platform process. Business tables live here. The agent never imports this package.

The on-disk package is `cvplatform` so it does not shadow the stdlib `platform` module.
Deploy it as the `platform-api` / `platform-worker` units.
"""
