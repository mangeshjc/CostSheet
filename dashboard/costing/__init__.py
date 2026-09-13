"""Reusable monthly costing pipeline.

Storage  = Google Drive (one folder tree per period, mirroring the source layout)
Database = Google Sheets (a control spreadsheet with Periods / SourceFiles /
           DataFiles / RunLog tabs, plus carried-forward reference maps)

The pipeline is config-driven (see ``config.py``): adding a new ERP source or a
new derived data file is a data change plus one converter, not new plumbing.
"""
