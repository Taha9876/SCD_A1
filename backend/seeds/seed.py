"""Idempotent seed.

Run it twice and nothing changes. Idempotency is the whole point: a seed that
duplicates on a second run makes `docker compose up` destructive, and somebody
will run it twice on the demo machine ten minutes before the viva.

The mechanism is the content_hash column: each complaint's (text, location)
hashes to a stable key, so "already there?" is one indexed lookup, not a
fuzzy text comparison.

Triage runs through the real TriageService, so the seeded rows carry honest
triaged_by and triage_latency_ms values rather than hardcoded ones -- the
dashboard demo then shows the actual provider mix.

    python -m seeds.seed            # insert what is missing
    python -m seeds.seed --report   # show what would happen, change nothing
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.providers.cache import InMemoryCache, RedisCache
from app.providers.triage.base import content_hash
from app.providers.triage.factory import build_provider
from app.repositories.complaint_repo import ComplaintRepository, NewComplaint
from app.services.triage_service import TriageService

# Deliberately Urdu-influenced English, the register these forms actually
# receive. Mixed quality on purpose: some are precise, some are vague, some
# name a consequence and some do not -- that spread is what makes the triage
# demo meaningful rather than a keyword parade.
COMPLAINTS: list[tuple[str, str, str | None]] = [
    ("Burst water main flooding Street 12 since fajr, water is entering ground floors of three houses. Please send team urgently.", "Street 12, G-9/4, Islamabad", "0300-1234567"),
    ("Water supply is not coming since 5 days in our lane, tanker bhi nahi aa raha. Children are suffering.", "Lane 4, Gulshan-e-Iqbal Block 13, Karachi", "0321-9876543"),
    ("Main pipeline leakage near the mosque, clean water is wasting whole day on the road.", "Near Jamia Masjid, Model Town Link Road, Lahore", None),
    ("Water pressure is very low on first floor since the new construction started nearby.", "House 221, Phase 5 DHA, Lahore", "0333-4455661"),
    ("Sewerage water mixing with drinking water line, the water is smelling badly and my son got stomach infection.", "Street 7, Orangi Town Sector 11, Karachi", "0345-1122334"),
    ("Boring motor of the community tank is burnt, whole block is without water for two days.", "Block C, Satellite Town, Rawalpindi", None),

    ("Transformer is sparking badly at the corner pole, we are afraid it will catch fire. Live wire is hanging low.", "Corner of Street 9 and Main Boulevard, Johar Town, Lahore", "0301-5566778"),
    ("Load shedding is 14 hours daily in our area but bill is full. Is there any schedule?", "Sector I-10/2, Islamabad", "0311-2233445"),
    ("Electric wire has fallen on the footpath after last night rain, children go to school from this way. Very dangerous.", "Street 3, Chaklala Scheme 3, Rawalpindi", "0300-7788990"),
    ("Voltage is fluctuating too much, two of my appliances have burnt this month.", "Flat 4B, Askari 11, Lahore", None),
    ("Electricity meter is showing reading even when main switch is off, please send inspection team.", "House 88, Wapda Town Phase 1, Lahore", "0322-6677889"),
    ("Feeder trips every time it rains, whole street remains dark for hours.", "Street 21, F-11/3, Islamabad", None),

    ("Garbage has not been lifted from our lane since two weeks, kachra is spreading on the road and dogs are tearing bags.", "Lane 6, Nazimabad Block 2, Karachi", "0332-1234567"),
    ("Open manhole near the school gate, cover is missing since one month. Someone will fall inside.", "Opposite Govt Boys School, Peoples Colony, Faisalabad", "0300-9988776"),
    ("Sewer line is choked and gutter water is standing in front of our houses. Very bad smell, mosquitoes everywhere.", "Street 14, Ghauri Town Phase 4, Islamabad", None),
    ("Drain is overflowing near the vegetable market, sewage is coming out on the road where people walk.", "Sabzi Mandi Road, Sargodha", "0345-6655443"),
    ("Municipal sweeper has not come to our street for one month, we are paying the charges regularly.", "Street 2, Gulberg 3, Lahore", None),
    ("Solid waste dump has been made at the empty plot behind our house, they burn it at night and smoke enters our rooms.", "Plot 45, Korangi Sector 33, Karachi", "0311-8877665"),

    ("There is a very big pothole in the middle of the road, one motorcycle accident already happened here yesterday.", "Main Road near Chandni Chowk, Rawalpindi", "0300-4433221"),
    ("Road was dug by the gas company two months ago and never repaired. Now it is full of dust and stones.", "Street 5, Township Sector C1, Lahore", None),
    ("Footpath is completely broken and encroached by shops, pedestrians have to walk on the main road.", "Liberty Market outer road, Gulberg, Lahore", "0321-3344556"),
    ("Speed breaker is too high and unmarked, cars are scraping at night because there is no paint on it.", "Near Chowk Azam, University Road, Peshawar", None),
    ("Traffic signal at the intersection is not working since Eid, there is jam every morning.", "Kalma Chowk intersection, Lahore", "0333-2211009"),
    ("Manhole cover on the road has sunk two inches below the surface, every car hits it hard.", "Service Road West, I-8 Markaz, Islamabad", None),

    ("Street lights of our whole lane are not working since last month, it is completely dark after maghrib and ladies are afraid to walk.", "Lane 9, Bahria Town Phase 4, Rawalpindi", "0300-1199887"),
    ("Lamp post is broken and leaning towards the road, it can fall on parked cars anytime.", "Street 18, North Nazimabad Block H, Karachi", "0345-9900112"),
    ("Street light is remaining on the whole day also, electricity is wasting.", "Sector G-6/1, Islamabad", None),
    ("New poles were installed three months back but lights were never connected.", "Phase 7 Extension, DHA, Karachi", "0322-5544332"),
    ("Two street lights near the park are off, children play there till late and it becomes very dark.", "Model Town Park, Block B, Lahore", None),

    ("Stray dogs have increased a lot in our sector, one child was bitten near the park last week. Please arrange something.", "Sector B, Bahria Enclave, Islamabad", "0311-7766554"),
    ("Illegal construction is going on at the plot next to my house, they are working after midnight with machinery.", "Plot 12, Street 4, PECHS Block 6, Karachi", "0300-6655443"),
    ("Park benches and swings are broken, the children park has not been maintained for a long time.", "Iqbal Park, Sector 11B, Karachi", None),
    ("Water tanker mafia is not allowing the government tanker to enter our street.", "Lane 11, Lyari, Karachi", "0345-3322110"),
    ("Suggestion: please install a dustbin at the bus stop, people throw wrappers on the footpath.", "Pirwadhai Bus Stop, Rawalpindi", None),
    ("Noise from the marriage hall generator goes on till 2am every weekend, elderly people cannot sleep.", "Main Ferozepur Road, Lahore", "0321-1100998"),
    ("Sewerage and electricity both departments are blaming each other for the flooded transformer pit near our gate. Water is standing around live cables.", "Street 16, Askari 14, Rawalpindi", "0333-9988771"),
]


async def run(report_only: bool = False) -> int:
    settings = get_settings()

    # Import here so that `--report` against an unreachable database still
    # gives a useful error instead of an import-time connection attempt.
    from app.db import SessionLocal, dispose_engine

    cache = _build_cache(settings)
    triage = TriageService(
        provider=build_provider(settings), cache=cache, settings=settings
    )

    inserted = skipped = 0
    async with SessionLocal() as session:
        repo = ComplaintRepository(session)
        for text, location, contact in COMPLAINTS:
            digest = content_hash(text, location)
            if await repo.get_by_content_hash(digest) is not None:
                skipped += 1
                continue

            if report_only:
                inserted += 1
                continue

            outcome = await triage.triage(text, location)
            await repo.create(
                NewComplaint(
                    text=text,
                    location=location,
                    reporter_contact=contact,
                    category=outcome.result.category,
                    priority=outcome.result.priority,
                    ai_summary=outcome.result.summary,
                    triaged_by=outcome.triaged_by,
                    triage_latency_ms=outcome.latency_ms,
                    triage_confidence=outcome.result.confidence,
                    content_hash=digest,
                )
            )
            inserted += 1

    await cache.close()
    await dispose_engine()

    verb = "would insert" if report_only else "inserted"
    print(
        f"seed: {verb} {inserted}, skipped {skipped} already present "
        f"({len(COMPLAINTS)} defined, provider={settings.triage_provider})"
    )
    return 0


def _build_cache(settings):
    """Fall back to an in-process cache if Redis is not reachable.

    Seeding is a data operation; it should not fail because the cache is down.
    """
    try:
        return RedisCache(settings.redis_url)
    except Exception:
        print("seed: redis unavailable, using in-memory triage cache", file=sys.stderr)
        return InMemoryCache()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed CivicPulse with realistic complaints.")
    parser.add_argument(
        "--report",
        action="store_true",
        help="show what would be inserted without writing anything",
    )
    args = parser.parse_args()
    return asyncio.run(run(report_only=args.report))


if __name__ == "__main__":
    raise SystemExit(main())
