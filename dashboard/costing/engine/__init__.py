"""Costing calculation engine.

Ports the Excel workbook chain to deterministic Python (pandas-style) stages,
per the build strategy. Each stage is a pure function over typed frames so it
can be unit-tested against the current workbook output (golden-file tests).
"""
