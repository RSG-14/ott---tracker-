"""
Reddit data collector for the OTT Tracker.

Uses PRAW to fetch posts and comments from relevant subreddits
(e.g. r/cordcutters, r/Netflix, r/DisneyPlus) and stores raw results
in the local SQLite database for downstream analysis.
"""
