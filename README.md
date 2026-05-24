# Goviya — Automated Price Updates

This repository runs daily price scrapers for the Goviya app.

## What it does
Every weekday at 9:00 AM Sri Lanka time:
1. Downloads CBSL daily price PDF
2. Scrapes DOA InfoHub for 9 key vegetables
3. Saves all prices to Supabase

## Manual trigger
Go to Actions tab → Daily Price Update → Run workflow

## Secrets needed
- SUPABASE_URL
- SUPABASE_SERVICE_KEY
