"""Tools for trying and testing Concept Trail without touching real notes,
without an API key and without a bill.

    python -m testkit            the test environment (see docs/TEST.md)

fake_model  an OpenAI-compatible stand-in model that answers every job of
            the app in the shape its parsers expect — predictable, not clever
seed        the sample vault: notes that exercise each feature
"""
