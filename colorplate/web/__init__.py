"""Web GUI for colorplate.

A thin FastAPI layer that wraps the real conversion pipeline so the
ColorPlate front end (upload -> detect regions -> assign filaments ->
generate STLs) drives the actual mesh generator instead of mocks.

Install the optional extra and launch with::

    pip install -e ".[web]"
    colorplate-web
"""
