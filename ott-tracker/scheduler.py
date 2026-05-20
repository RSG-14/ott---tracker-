"""
Job scheduler for the OTT Tracker.

Uses the schedule library to run reddit_pull and trends_pull on a
recurring interval (e.g. every hour), then triggers analyzer.py to
process any new unanalyzed records.
"""
