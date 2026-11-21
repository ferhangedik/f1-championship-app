#routes/common.py — Shared database helpers used across pages.

from flask import request
import db


def all_seasons():
    #Return all seasons ordered from newest to oldest.
    return db.query("SELECT season_id, year FROM hfg_seasons ORDER BY year DESC")


def resolve_season():
    #Pick the ?season=<id> from the URL, or the most recent season.

    seasons = all_seasons()
    sel_id = request.args.get("season", type=int)
    season = None
    if sel_id:
        season = next((s for s in seasons if s["season_id"] == sel_id), None)
    if season is None and seasons:
        season = seasons[0]  # most recent season thanks to year DESC
    return season, seasons